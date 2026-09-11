"""Uniformly sampled Sawyer trajectories in radians, seconds and Nm."""
from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass, replace
from pathlib import Path

from sawyer_control.types import ControlMode, JointCommandSample, JointVector

ARM_JOINTS = tuple(f'right_j{i}' for i in range(7))
SCHEMA_VERSION = 3
COMMAND_RATE_HZ = 100.0  # The robot's command rate. Streaming enforces it; a trajectory may
MIN_RATE_HZ = 1.0        # hold any positive rate, and be resampled into range deliberately.
REQUIRED_FIELDS = {ControlMode.POSITION: ('position',), ControlMode.VELOCITY: ('velocity',),
                   ControlMode.TORQUE: ('effort',),
                   ControlMode.TRAJECTORY: ('position', 'velocity', 'acceleration')}
FIELDS = ('position', 'velocity', 'effort', 'acceleration')
UNITS = {'position': 'rad', 'velocity': 'rad/s', 'effort': 'Nm', 'acceleration': 'rad/s^2'}


@dataclass(frozen=True)
class Trajectory:
    mode: ControlMode
    samples: tuple[JointCommandSample, ...]
    rate_hz: float

    def __post_init__(self):
        object.__setattr__(self, 'mode', ControlMode(self.mode))
        object.__setattr__(self, 'rate_hz', float(self.rate_hz))
        if not math.isfinite(self.rate_hz) or self.rate_hz <= 0:
            raise ValueError('rate_hz must be a finite positive number of samples per second')
        required = REQUIRED_FIELDS
        samples = tuple(self.samples)
        if not samples:
            raise ValueError('A trajectory needs at least one sample')
        object.__setattr__(self, 'samples', samples)
        for sample in samples:
            if any(getattr(sample, field) is None for field in required[self.mode]):
                raise ValueError(f'{self.mode.value} requires {required[self.mode]} in every sample')

    @property
    def duration_s(self):
        return len(self.samples) / self.rate_hz

    @property
    def span_s(self):
        """Time of the last sample. One shorter than duration_s by a single period."""
        return (len(self.samples) - 1) / self.rate_hz

    def resampled_to(self, rate_hz):
        """The same motion at another rate, interpolating linearly between samples.

        Downsampling and upsampling are both supported and the ratio need not be
        a whole number. The motion keeps its wall-clock span; only how densely it
        is sampled changes, so velocities and accelerations are resampled as they
        stand and are not rescaled. Sampling below twice the fastest content in a
        signal aliases it, and no filter is applied.
        """
        rate_hz = float(rate_hz)
        if rate_hz == self.rate_hz:
            return self
        if len(self.samples) == 1:
            return replace(self, rate_hz=rate_hz)
        return replace(self, samples=resample_samples(self.samples, self.rate_hz, rate_hz),
                       rate_hz=rate_hz)

    def at_speed(self, speed):
        """The same samples played at `speed` times the original rate.

        Half speed doubles the wall-clock span, so the joints really do move at
        half the velocity: velocity is scaled by `speed` and acceleration by its
        square to stay consistent with the positions. Torque is refused, because
        effort under time scaling depends on the arm's dynamics rather than on
        any single factor.
        """
        speed = float(speed)
        if not speed > 0 or speed == float('inf'):
            raise ValueError('speed must be a positive, finite factor')
        if self.mode is ControlMode.TORQUE:
            raise ValueError('Torque cannot be time-scaled: effort depends on the arm dynamics, '
                             'not on the playback factor. Regenerate the trajectory instead.')
        scale = {'velocity': speed, 'acceleration': speed * speed}
        samples = tuple(JointCommandSample(**{
            field: JointVector(value * scale.get(field, 1.0) for value in vector.values)
            for field in FIELDS if (vector := getattr(sample, field)) is not None})
            for sample in self.samples)
        return replace(self, samples=samples, rate_hz=self.rate_hz * speed)

    def to_dict(self):
        return {'schema_version': SCHEMA_VERSION, 'mode': self.mode.value, 'rate_hz': self.rate_hz,
                'joint_names': list(ARM_JOINTS), 'units': UNITS,
                'samples': [{field: list(getattr(sample, field).values) for field in FIELDS
                             if getattr(sample, field) is not None}
                            for sample in self.samples]}

    def summary(self):
        return {'mode': self.mode.value, 'rate_hz': self.rate_hz,
                'samples': len(self.samples), 'duration_s': self.duration_s,
                'previewable': all(s.position is not None for s in self.samples)}

    @classmethod
    def from_dict(cls, value):
        allowed = {'schema_version', 'mode', 'rate_hz', 'joint_names', 'units', 'samples'}
        if not isinstance(value, dict):
            raise ValueError(f'Required trajectory fields: {sorted(allowed)}')
        if value.get('schema_version') != SCHEMA_VERSION:
            raise ValueError(f'Expected trajectory schema_version {SCHEMA_VERSION}. Earlier versions '
                             f'carried a name field; a trajectory is identified by the ID it is '
                             f'stored under.')
        if not allowed.issubset(value):
            raise ValueError(f'Required trajectory fields: {sorted(allowed)}')
        if set(value) - allowed:
            raise ValueError(f'Unknown trajectory fields: {set(value) - allowed}')
        if tuple(value.get('joint_names', ())) != ARM_JOINTS:
            raise ValueError('joint_names must be right_j0 through right_j6 in order')
        if value.get('units') != UNITS:
            raise ValueError(f'Expected units {UNITS}; no implicit conversion is performed')
        samples = []
        if not isinstance(value['samples'], list):
            raise ValueError('Expected a list of samples')
        for row in value['samples']:
            if not isinstance(row, dict) or any(not isinstance(v, (list, tuple)) for v in row.values()):
                raise ValueError('Each sample must map field names to seven-element arrays')
            if set(row) - set(FIELDS):
                raise ValueError(f'Unknown sample fields: {set(row) - set(FIELDS)}')
            samples.append(JointCommandSample(**{key: JointVector(val) for key, val in row.items()}))
        return cls(ControlMode(value['mode']), tuple(samples), value['rate_hz'])

    @classmethod
    def load(cls, path):
        return cls.from_dict(json.loads(Path(path).read_text()))

    def save(self, path):
        with Path(path).open('x') as stream:
            json.dump(self.to_dict(), stream, allow_nan=False)

    @classmethod
    def from_csv(cls, text, *, mode, rate_hz):
        """Columns are position.right_j0, velocity.right_j0, etc.; SI units only."""
        reader = csv.DictReader(io.StringIO(text))
        columns = set(reader.fieldnames or ())
        fields = [field for field in FIELDS if any(c.startswith(field+'.') for c in columns)]
        expected = {f'{field}.{joint}' for field in fields for joint in ARM_JOINTS}
        if not fields or columns != expected or len(reader.fieldnames) != len(expected):
            raise ValueError('CSV needs exactly seven named columns per supplied field')
        rows = []
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise ValueError('CSV row does not match its header')
            rows.append(JointCommandSample(**{
                field: JointVector(float(row[f'{field}.{joint}']) for joint in ARM_JOINTS)
                for field in fields}))
        return cls(mode, tuple(rows), rate_hz)


def resample_samples(samples, from_hz, to_hz):
    """Linearly resample a sample sequence, keeping its wall-clock span."""
    samples = tuple(samples)
    if from_hz == to_hz or len(samples) < 2:
        return samples
    count = round((len(samples) - 1) / from_hz * to_hz) + 1
    return tuple(_interpolate_sample(samples, index / to_hz * from_hz) for index in range(count))


def _interpolate_sample(samples, position):
    """Linearly interpolate the sample at a fractional index into `samples`."""
    low = max(0, min(int(position), len(samples) - 2))
    blend = min(max(position - low, 0.0), 1.0)
    first, second = samples[low], samples[low + 1]
    return JointCommandSample(**{
        field: JointVector(a + (b - a) * blend
                           for a, b in zip(getattr(first, field).values,
                                           getattr(second, field).values))
        for field in FIELDS if getattr(first, field) is not None})
