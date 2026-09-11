"""Uniformly sampled Sawyer trajectories in radians, seconds and Nm."""
from __future__ import annotations

import csv
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path

from sawyer_control.types import ControlMode, JointCommandSample, JointVector

ARM_JOINTS = tuple(f'right_j{i}' for i in range(7))
SCHEMA_VERSION = 3
RATE_HZ = 100.0      # The robot's command rate, and the default for every trajectory.
MIN_RATE_HZ = 1.0    # Below this a motion is too sparse to command.
REQUIRED_FIELDS = {ControlMode.POSITION: ('position',), ControlMode.VELOCITY: ('velocity',),
                   ControlMode.TORQUE: ('effort',),
                   ControlMode.TRAJECTORY: ('position', 'velocity', 'acceleration')}
FIELDS = ('position', 'velocity', 'effort', 'acceleration')
UNITS = {'position': 'rad', 'velocity': 'rad/s', 'effort': 'Nm', 'acceleration': 'rad/s^2'}


@dataclass(frozen=True)
class Trajectory:
    mode: ControlMode
    samples: tuple[JointCommandSample, ...]
    rate_hz: float = RATE_HZ

    def __post_init__(self):
        object.__setattr__(self, 'mode', ControlMode(self.mode))
        object.__setattr__(self, 'rate_hz', float(self.rate_hz))
        if not MIN_RATE_HZ <= self.rate_hz <= RATE_HZ:
            raise ValueError(f'rate_hz must be between {MIN_RATE_HZ:g} and {RATE_HZ:g}; '
                             f'the robot is commanded at {RATE_HZ:g} Hz')
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
        allowed = {'schema_version', 'mode', 'joint_names', 'units', 'samples'}
        optional = {'rate_hz'}
        if not isinstance(value, dict):
            raise ValueError(f'Required trajectory fields: {sorted(allowed)}')
        if value.get('schema_version') != SCHEMA_VERSION:
            raise ValueError(f'Expected trajectory schema_version {SCHEMA_VERSION}. Earlier versions '
                             f'carried a name field; a trajectory is identified by the ID it is '
                             f'stored under.')
        if not allowed.issubset(value):
            raise ValueError(f'Required trajectory fields: {sorted(allowed)}')
        if set(value) - allowed - optional:
            raise ValueError(f'Unknown trajectory fields: {set(value) - allowed - optional}')
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
        return cls(ControlMode(value['mode']), tuple(samples), value.get('rate_hz', RATE_HZ))

    @classmethod
    def load(cls, path):
        return cls.from_dict(json.loads(Path(path).read_text()))

    def save(self, path):
        with Path(path).open('x') as stream:
            json.dump(self.to_dict(), stream, allow_nan=False)

    @classmethod
    def from_csv(cls, text, *, mode, rate_hz=RATE_HZ):
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
