"""Synchronous Python facade for one local Sawyer operations session."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import threading
import time

from .operations import Operations
from .trajectories import Trajectory


_TERMINAL = {'completed', 'cancelled', 'stopped', 'failed', 'rejected'}


class Robot:
    @classmethod
    def connect(cls):
        return cls()

    def __init__(self):
        self._loop = None
        self._thread = None
        self._context = None
        self._operations = None
        self.force_torque = _ForceTorque(self)

    def __enter__(self):
        ready = threading.Event()
        self._loop = asyncio.new_event_loop()

        def run_loop():
            asyncio.set_event_loop(self._loop)
            ready.set()
            self._loop.run_forever()

        self._thread = threading.Thread(target=run_loop, name='sawyer-operations', daemon=True)
        self._thread.start()
        ready.wait()
        try:
            self._context = Operations.connect()
            self._operations = self._await(self._context.__aenter__())
        except Exception:
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join()
            self._loop.close()
            self._loop = self._thread = self._context = None
            raise
        return self

    def __exit__(self, *exc):
        if self._context is not None:
            self._await(self._context.__aexit__(*exc))
        loop, thread = self._loop, self._thread
        loop.call_soon_threadsafe(loop.stop)
        thread.join()
        loop.close()
        self._loop = self._thread = self._context = self._operations = None

    def load_trajectory(self, path):
        trajectory = path if isinstance(path, Trajectory) else Trajectory.load(Path(path))
        result = self._invoke(self._operations.load, trajectory)
        return LoadedTrajectory(self, result['id'], trajectory)

    @property
    def state(self):
        return self.wait_for_state()

    def wait_for_state(self, timeout_s=10.0):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            state = self._invoke(self._operations.latest_state)
            if state is not None:
                return state
            time.sleep(.02)
        raise RuntimeError('Timed out waiting for the first robot state')

    def show_preview(self, trajectory):
        self._invoke(self._operations.preview, _trajectory_id(trajectory))

    def start_recording(self, name='Recording'):
        result = self._invoke(self._operations.start_recording, name)
        return Recording(self, result['id'])

    def stop_recording(self):
        return self._invoke(self._operations.stop_recording)

    def open_gripper(self):
        return self._await(self._operations.command('open'))

    def close_gripper(self):
        return self._await(self._operations.command('close'))

    def stop(self):
        return self._await(self._operations.command('stop'))

    def stream(self, trajectory):
        result = self._await(self._operations.start_stream(_trajectory_id(trajectory)))
        return TrajectoryRun(self, result['id'])

    def _run(self, identity):
        return self._invoke(lambda: next(run for run in self._operations.streams.snapshot() if run['id'] == identity))

    def _invoke(self, function, *args):
        async def invoke():
            return function(*args)
        return self._await(invoke())

    def _await(self, coroutine):
        if self._loop is None:
            raise RuntimeError('Use Robot.connect() as a context manager')
        return asyncio.run_coroutine_threadsafe(coroutine, self._loop).result()


@dataclass(frozen=True)
class LoadedTrajectory:
    robot: Robot
    id: str
    data: Trajectory


class Recording:
    def __init__(self, robot, identity):
        self._robot = robot
        self.id = identity
        self.closed = False

    def stop(self):
        if not self.closed:
            self._robot.stop_recording()
            self.closed = True

    close = stop


class TrajectoryRun:
    def __init__(self, robot, identity):
        self._robot = robot
        self.id = identity

    @property
    def status(self):
        return self._robot._run(self.id)

    def cancel(self):
        return self._robot._await(self._robot._operations.cancel_stream(self.id))

    def wait(self, timeout=None):
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            status = self.status
            if status['phase'] in _TERMINAL:
                return status
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError('Trajectory stream is still active')
            time.sleep(.02)


class _ForceTorque:
    def __init__(self, robot):
        self._robot = robot

    def enable(self):
        return self._robot._await(self._robot._operations.enable_force_torque())


def _trajectory_id(trajectory):
    if not isinstance(trajectory, LoadedTrajectory):
        raise TypeError('Use robot.load_trajectory() before previewing or streaming')
    return trajectory.id
