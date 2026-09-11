"""Timed, cancellable publication of immediate Sawyer joint commands."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import time
import uuid

from sawyer_control.v1 import control_pb2 as pb

from .trajectories import Trajectory


@dataclass(frozen=True)
class StreamGuard:
    start_max_error_rad: float = 0.05
    tracking_max_error_rad: float = 0.15
    divergence_frames: int = 3
    max_state_age_s: float = 0.25
    max_lateness_s: float = 0.05


class StreamExecutor:
    def __init__(self, api, state, event, command):
        self._api = api
        self._state = state
        self._event = event
        self._command = command
        self._runs = {}
        self._active = None

    @property
    def runs(self):
        return self._runs

    def snapshot(self):
        return [_public(run) for run in self._runs.values()]

    async def start(self, trajectory_id, trajectory):
        guard = StreamGuard()
        if self._active is not None:
            raise RuntimeError('A stream is already active')
        if any(sample.position is None for sample in trajectory.samples):
            raise ValueError('Streaming requires position data in every sample')
        state, received_ns, _ = self._state()
        now_mono_ns = time.monotonic_ns()
        if state is None or received_ns is None or (now_mono_ns - received_ns) / 1_000_000_000 > guard.max_state_age_s:
            return self._reject(trajectory_id, 'no_state', 'No robot state is available')
        initial_error = _max_error(state['positions'], trajectory.samples[0].position.values)
        if initial_error > guard.start_max_error_rad:
            return self._reject(trajectory_id, 'start_mismatch',
                                f'Initial joint error {initial_error:.4f} rad exceeds {guard.start_max_error_rad:.4f} rad')
        identity = uuid.uuid4().hex
        now_wall_ns = time.time_ns()
        run = {'id': identity, 'trajectory_id': trajectory_id, 'phase': 'starting',
               'reason': None, 'started_wall_time_ns': now_wall_ns,
               'started_monotonic_ns': now_mono_ns, 'samples_sent': 0,
               'guard': guard.__dict__.copy()}
        self._runs[identity] = run
        self._active = identity
        run['_cancel_event'] = asyncio.Event()
        self._event('stream.started', **_public(run))
        task = asyncio.create_task(self._run(run, trajectory, guard))
        run['_task'] = task
        return _public(run)

    async def cancel(self, identity):
        run = self._runs[identity]
        if run['phase'] in {'completed', 'cancelled', 'stopped', 'failed', 'rejected'}:
            return _public(run)
        run['_cancel_event'].set()
        self._event('stream.cancel_requested', id=identity)
        task = run.get('_task')
        if task is not None:
            await task
        return _public(run)

    async def close(self):
        if self._active is not None:
            await self.cancel(self._active)

    async def _run(self, run, trajectory, guard):
        run['phase'] = 'running'
        self._event('stream.running', **_public(run))
        start_ns = run['started_monotonic_ns']
        seen_state = -1
        divergence = 0
        try:
            for index, sample in enumerate(trajectory.samples):
                if run['_cancel_event'].is_set():
                    return self._finish(run, 'cancelled', 'cancelled')
                deadline_ns = start_ns + round(index * 1_000_000_000 / trajectory.rate_hz)
                self._command('scheduled', run['id'], index, deadline_ns, time.time_ns(), time.monotonic_ns(), sample)
                delay_s = (deadline_ns - time.monotonic_ns()) / 1_000_000_000
                if delay_s > 0:
                    try:
                        await asyncio.wait_for(run['_cancel_event'].wait(), delay_s)
                    except asyncio.TimeoutError:
                        pass
                now_ns = time.monotonic_ns()
                if run['_cancel_event'].is_set():
                    return self._finish(run, 'cancelled', 'cancelled')
                if (now_ns - deadline_ns) / 1_000_000_000 > guard.max_lateness_s:
                    return self._finish(run, 'stopped', 'schedule_late')
                state, received_ns, state_id = self._state()
                if state is None or received_ns is None or (now_ns - received_ns) / 1_000_000_000 > guard.max_state_age_s:
                    return self._finish(run, 'stopped', 'telemetry_stale')
                if state_id != seen_state:
                    seen_state = state_id
                    expected = _interpolate_position(trajectory, (received_ns - start_ns) / 1_000_000_000)
                    error = _max_error(state['positions'], expected)
                    divergence = divergence + 1 if error > guard.tracking_max_error_rad else 0
                    if divergence >= guard.divergence_frames:
                        return self._finish(run, 'stopped', 'tracking_diverged')
                await self._publish(run, index, sample, deadline_ns, trajectory)
            self._finish(run, 'completed', 'all_samples_published')
        except Exception as error:
            self._finish(run, 'failed', str(error))

    async def _publish(self, run, index, sample, deadline_ns, trajectory):
        command = pb.JointCommandSample()
        for field in ('position', 'velocity', 'effort', 'acceleration'):
            value = getattr(sample, field)
            if value is not None:
                getattr(command, field).CopyFrom(pb.JointVector(values=value.values))
        request = pb.JointCommandRequest(mode=getattr(pb, trajectory.mode.value.upper()), sample=command)
        attempted_wall_ns = time.time_ns()
        attempted_mono_ns = time.monotonic_ns()
        self._command('attempted', run['id'], index, deadline_ns, attempted_wall_ns, attempted_mono_ns, sample)
        result = await self._api.CommandJoints(request, timeout=1)
        acknowledged_wall_ns = time.time_ns()
        acknowledged_mono_ns = time.monotonic_ns()
        self._command('acknowledged', run['id'], index, deadline_ns, acknowledged_wall_ns, acknowledged_mono_ns,
                      sample, success=result.success, message=result.message)
        if not result.success:
            raise RuntimeError(result.message or 'Bridge rejected joint command')
        run['samples_sent'] += 1

    def _reject(self, trajectory_id, reason, message):
        run = {'id': uuid.uuid4().hex, 'trajectory_id': trajectory_id, 'phase': 'rejected',
               'reason': reason, 'message': message, 'samples_sent': 0,
               'finished_wall_time_ns': time.time_ns()}
        self._runs[run['id']] = run
        self._event('stream.rejected', **run)
        return _public(run)

    def _finish(self, run, phase, reason):
        if run['phase'] not in {'running', 'starting'}:
            return
        run.update(phase=phase, reason=reason, finished_wall_time_ns=time.time_ns(),
                   finished_monotonic_ns=time.monotonic_ns())
        if self._active == run['id']:
            self._active = None
        self._event('stream.finished', **_public(run))


def _interpolate_position(trajectory, elapsed_s):
    index = max(0.0, min(elapsed_s * trajectory.rate_hz, len(trajectory.samples) - 1))
    left = int(index)
    right = min(left + 1, len(trajectory.samples) - 1)
    fraction = index - left
    a = trajectory.samples[left].position.values
    b = trajectory.samples[right].position.values
    return tuple((1 - fraction) * x + fraction * y for x, y in zip(a, b))


def _max_error(actual, expected):
    if len(actual) != 7 or len(expected) != 7:
        raise ValueError('Robot state must contain seven joint positions')
    return max(abs(a - b) for a, b in zip(actual, expected))


def _public(run):
    return {key: value for key, value in run.items() if not key.startswith('_')}
