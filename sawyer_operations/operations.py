"""Shared operations session, usable directly from Python or through HTTP."""
from __future__ import annotations

from collections import deque
import copy
from pathlib import Path
import time
import uuid

from sawyer_control.v1 import control_pb2 as pb

from .executor import StreamExecutor
from .recordings import Recorder
from .trajectories import Trajectory


class Operations:
    def __init__(self, api, directory):
        self.api = api
        self.directory = Path(directory).expanduser().resolve()
        self.trajectories = {}
        self.selected = None
        self.events = deque(maxlen=200)
        self.revision = 0
        self.recorder = Recorder(self.directory / 'recordings')
        self._state = None
        self._state_received_ns = None
        self._state_sequence = 0
        self.streams = StreamExecutor(api, self._latest_state, self.event, self._record_command)
        for path in sorted((self.directory / 'trajectories').glob('*.json')):
            self.trajectories[path.stem] = Trajectory.load(path)

    def event(self, kind, **data):
        self.revision += 1
        event = {'revision': self.revision, 'timestamp_s': time.time(), 'type': kind, 'data': data}
        self.events.append(event)
        try:
            self.recorder.event(kind, data)
        except (OSError, ValueError):
            pass  # Recorder exposes the write error; a robot command must not be retried.
        return event

    def load(self, trajectory):
        if not isinstance(trajectory, Trajectory):
            trajectory = Trajectory.from_dict(trajectory)
        identity = uuid.uuid4().hex
        directory = self.directory / 'trajectories'
        directory.mkdir(parents=True, exist_ok=True)
        trajectory.save(directory / f'{identity}.json')
        self.trajectories[identity] = trajectory
        self.event('trajectory.loaded', id=identity, **trajectory.summary())
        return {'id': identity, **trajectory.summary()}

    def preview(self, identity):
        if identity is not None:
            trajectory = self.trajectories[identity]
            if not trajectory.summary()['previewable']:
                raise ValueError('Position samples are required for a geometric preview')
        self.selected = identity
        self.event('preview.selected', id=identity)

    async def command(self, action):
        names = {'stop': 'Stop', 'enable': 'Enable', 'disable': 'Disable', 'reset': 'Reset',
                 'open': 'OpenGripper', 'close': 'CloseGripper'}
        if action not in names:
            raise ValueError('Unknown robot command')
        request = pb.StopRequest() if action == 'stop' else pb.Empty()
        result = await getattr(self.api, names[action])(request, timeout=15)
        self.event('command.result', action=action, success=result.success, message=result.message)
        if not result.success:
            raise RuntimeError(result.message or 'Robot did not acknowledge command')
        return {'success': True, 'action': action}

    def start_recording(self, name='Recording'):
        result = self.recorder.start(name, metadata={
            'trajectories': {k: v.to_dict() for k, v in self.trajectories.items()}})
        self.event('recording.started', **result)
        return result

    def stop_recording(self):
        result = self.recorder.stop()
        self.event('recording.finished', **result)
        return result

    def telemetry(self, state, gripper):
        self._state = copy.deepcopy(state)
        self._state_received_ns = time.monotonic_ns()
        self._state_sequence += 1
        try:
            self.recorder.sample(state, gripper)
        except (OSError, ValueError):
            pass

    def observe(self, stream, values, source_timestamp_s=None):
        try:
            self.recorder.observation(stream, values, source_timestamp_s)
        except (OSError, ValueError):
            pass

    async def start_stream(self, identity):
        return await self.streams.start(identity, self.trajectories[identity])

    async def cancel_stream(self, identity):
        return await self.streams.cancel(identity)

    async def enable_force_torque(self):
        await self.link.enable_force_torque()
        self.event('force_torque.enabled')

    def _latest_state(self):
        return self._state, self._state_received_ns, self._state_sequence

    def latest_state(self):
        return copy.deepcopy(self._state)

    def _record_command(self, *args, **kwargs):
        try:
            self.recorder.command(*args, **kwargs)
        except (OSError, ValueError):
            pass

    def snapshot(self):
        return {'revision': self.revision, 'selected_trajectory': self.selected,
                'trajectories': [{'id': k, **v.summary()} for k, v in self.trajectories.items()],
                'streams': self.streams.snapshot(),
                'recording': copy.deepcopy(self.recorder.active), 'recording_error': self.recorder.error,
                'events': list(self.events)}

    async def close(self):
        await self.streams.close()
        if self.recorder.active:
            self.stop_recording()

    @classmethod
    def connect(cls, address='127.0.0.1:50051', directory='~/.local/share/sawyer-operations'):
        """Return a context manager owning telemetry and the control connection."""
        from .session import session
        return session(address, directory)
