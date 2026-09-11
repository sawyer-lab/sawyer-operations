from contextlib import asynccontextmanager, suppress
import asyncio
import time

import grpc
from sawyer_control.v1 import control_pb2 as pb, control_pb2_grpc as rpc

from .operations import Operations


class RobotLink:
    def __init__(self, address, operations=None):
        self.channel = grpc.aio.insecure_channel(address)
        self.api = rpc.RobotControlStub(self.channel)
        self.force_torque_api = rpc.ForceTorqueStub(self.channel)
        self.operations = operations
        self.state = None
        self.received = 0.0
        self.error = 'Connecting to robot bridge'
        self.gripper = {'state': 'connecting', 'position': None}
        self.command_lock = asyncio.Lock()
        self.force_torque = {'enabled': False}
        self._force_torque_task = None

    async def telemetry(self):
        while True:
            try:
                async for state in self.api.StreamState(pb.StreamStateRequest(rate_hz=30)):
                    self.state = {'positions': list(state.positions.values),
                                  'velocities': list(state.velocities.values),
                                  'efforts': list(state.efforts.values),
                                  'pose': {'position': [state.pose.position.x, state.pose.position.y, state.pose.position.z],
                                           'orientation': [state.pose.orientation.x, state.pose.orientation.y,
                                                           state.pose.orientation.z, state.pose.orientation.w]},
                                  'enabled': state.enabled, 'stopped': state.stopped,
                                  'timestamp_s': state.timestamp_s}
                    self.received = time.monotonic()
                    self.error = None
                    if self.operations:
                        self.operations.telemetry(self.state, self.gripper)
            except grpc.RpcError as exc:
                self.error = exc.details() or exc.code().name
            await asyncio.sleep(1)

    async def gripper_telemetry(self):
        while True:
            try:
                state = await self.api.GetGripperState(pb.Empty(), timeout=12)
                self.gripper = {'state': state.state, 'position': state.position if state.position >= 0 else None}
            except grpc.RpcError as exc:
                self.gripper = {'state': 'unavailable', 'position': None, 'error': exc.details() or exc.code().name}
            await asyncio.sleep(.5)

    async def enable_force_torque(self):
        if self._force_torque_task is None:
            self.force_torque = {'enabled': True}
            self._force_torque_task = asyncio.create_task(self.force_torque_telemetry())

    async def force_torque_telemetry(self):
        try:
            async for reading in self.force_torque_api.StreamReadings(pb.StreamReadingsRequest(rate_hz=100)):
                if self.operations:
                    self.operations.observe('force_torque', {
                        'fx': reading.fx, 'fy': reading.fy, 'fz': reading.fz,
                        'tx': reading.tx, 'ty': reading.ty, 'tz': reading.tz,
                        'status': reading.status, 'source_sequence': reading.sequence,
                    }, reading.timestamp_s)
        except grpc.RpcError as exc:
            self.force_torque['error'] = exc.details() or exc.code().name
        finally:
            self._force_torque_task = None

    def snapshot(self):
        age = time.monotonic() - self.received if self.received else None
        return {'connected': age is not None and age < 2 and self.error is None,
                'age_ms': round(age*1000) if age is not None else None,
                'robot': self.state, 'gripper': self.gripper, 'force_torque': self.force_torque,
                'error': self.error}

    async def close(self):
        if self._force_torque_task is not None:
            self._force_torque_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._force_torque_task
        await self.channel.close()


@asynccontextmanager
async def session(address, directory):
    link = RobotLink(address)
    operations = Operations(link.api, directory)
    operations.link = link
    link.operations = operations
    tasks = [asyncio.create_task(link.telemetry()), asyncio.create_task(link.gripper_telemetry())]
    try:
        yield operations
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        await operations.close()
        await link.close()
