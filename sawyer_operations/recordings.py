"""Append-only, time-correlated telemetry and command records."""
from __future__ import annotations

import json
from pathlib import Path
import time
import uuid

from .trajectories import ARM_JOINTS

SIGNALS = ('positions', 'velocities', 'efforts', 'pose', 'enabled', 'stopped', 'gripper')


class Recorder:
    def __init__(self, directory):
        self.directory = Path(directory).expanduser().resolve()
        self.active = None
        self._stream = None
        self.error = None
        self._sequence = 0

    def start(self, name='Recording', metadata=None):
        if self.active:
            raise RuntimeError('A recording is already running')
        json.dumps(metadata or {}, allow_nan=False)
        self.directory.mkdir(parents=True, exist_ok=True)
        identity = uuid.uuid4().hex
        self._stream = (self.directory / f'{identity}.jsonl').open('x', buffering=1)
        self.active = {'id': identity, 'name': name, 'signals': list(SIGNALS),
                       'started_at': time.time(), 'samples': 0}
        self.error = None
        self._sequence = 0
        self._write({'type': 'metadata', 'schema_version': 2, **self.active,
                     'joint_names': ARM_JOINTS, 'units': {'positions': 'rad', 'velocities': 'rad/s',
                     'efforts': 'Nm', 'pose.position': 'm'}, 'metadata': metadata or {},
                     'clock': _clock(),
                     'timestamp_semantics': 'source_time_ns is supplied by a source when available; received times describe arrival at operations'})
        return dict(self.active)

    def _write(self, row):
        try:
            row.setdefault('sequence', self._sequence)
            self._sequence += 1
            self._stream.write(json.dumps(row, allow_nan=False)+'\n')
        except (OSError, ValueError) as exc:
            self.error = str(exc)
            self._stream.close()
            self._stream = None
            self.active = None
            raise

    def sample(self, state, gripper):
        if self.active:
            values = {signal: gripper if signal == 'gripper' else state.get(signal)
                      for signal in self.active['signals']}
            self.observation('robot.state', values, state.get('timestamp_s'))
            self.active['samples'] += 1

    def event(self, kind, data):
        if self.active:
            self._write({'type': 'event', 'event': kind, 'data': data, 'clock': _clock()})

    def observation(self, stream, values, source_timestamp_s=None):
        if self.active:
            clock = _clock()
            if source_timestamp_s is not None:
                clock['source_time_ns'] = round(float(source_timestamp_s) * 1_000_000_000)
            self._write({'type': 'observation', 'stream': stream, 'values': values, 'clock': clock})

    def command(self, stage, run_id, sample_index, scheduled_monotonic_ns,
                wall_time_ns, monotonic_ns, sample, success=None, message=None):
        if self.active:
            values = {field: list(getattr(sample, field).values) for field in
                      ('position', 'velocity', 'effort', 'acceleration') if getattr(sample, field) is not None}
            row = {'type': 'command', 'stage': stage, 'run_id': run_id,
                   'sample_index': sample_index, 'scheduled_monotonic_ns': scheduled_monotonic_ns,
                   'values': values, 'clock': {'wall_time_ns': wall_time_ns, 'monotonic_ns': monotonic_ns}}
            if success is not None:
                row['success'] = success
            if message:
                row['message'] = message
            self._write(row)

    def stop(self):
        if not self.active:
            raise RuntimeError('No recording is running')
        result = {**self.active, 'finished_at': time.time()}
        self._write({'type': 'end', **result, 'clock': _clock()})
        self._stream.close()
        self._stream = None
        self.active = None
        return result

    def path(self, identity):
        if len(identity) != 32 or any(c not in '0123456789abcdef' for c in identity):
            raise ValueError('Invalid recording ID')
        path = self.directory / f'{identity}.jsonl'
        if not path.is_file():
            raise KeyError(identity)
        return path

    def list(self):
        rows = []
        for path in sorted(self.directory.glob('*.jsonl')):
            with path.open() as stream:
                header = json.loads(stream.readline())
            rows.append({**header, 'bytes': path.stat().st_size,
                         'recording': bool(self.active and self.active['id'] == path.stem)})
        return rows


def read_recording(path):
    """Yield metadata, samples and events without loading the full recording."""
    with Path(path).open() as stream:
        for line in stream:
            yield json.loads(line)


def _clock():
    return {'wall_time_ns': time.time_ns(), 'monotonic_ns': time.monotonic_ns()}
