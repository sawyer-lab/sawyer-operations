"""Mapping of foreign joint tables onto canonical trajectories.

Columns are mapped explicitly; nothing is derived, resampled or repaired. The
source trajectory is assumed correct and uniformly sampled. The rate defaults
to the robot's 100 Hz command rate; Trajectory accepts 1 Hz to 100 Hz.
"""
from __future__ import annotations

import csv
import json
import math
from pathlib import Path

from sawyer_control.types import ControlMode

from .trajectories import ARM_JOINTS, FIELDS, RATE_HZ, SCHEMA_VERSION, UNITS, Trajectory

MODE_FIELDS = {ControlMode.POSITION: ('position',), ControlMode.VELOCITY: ('velocity',),
               ControlMode.TRAJECTORY: ('position', 'velocity', 'acceleration'),
               ControlMode.TORQUE: ('effort',)}
ANGLE_FIELDS = ('position', 'velocity', 'acceleration')
ALIASES = {'position': ('q', 'pos', 'position', 'theta', 'j'),
           'velocity': ('dq', 'qd', 'vel', 'velocity', 'omega'),
           'acceleration': ('ddq', 'qdd', 'acc', 'acceleration'),
           'effort': ('tau', 'torque', 'effort', 'u')}
SHORT = {'position': 'q', 'velocity': 'dq', 'acceleration': 'ddq', 'effort': 'tau'}

# right_j0 through right_j6 ranges as published by the MuJoCo description that
# the workspace model is built from. Re-derive with:
#   grep 'joint name="right_j' \
#     /home/fausto/Projects/tossing/packages/description/description/models/arms/sawyer/sawyer_base.xml
POSITION_LIMITS_RAD = ((-3.0503, 3.0503), (-3.8095, 2.2736), (-3.0426, 3.0426), (-3.0439, 3.0439),
                       (-2.9761, 2.9761), (-2.9761, 2.9761), (-4.7124, 4.7124))


def normalize(name):
    return ''.join(character for character in str(name).lower() if character.isalnum())


def number(cell):
    try:
        return float(str(cell).strip())
    except (TypeError, ValueError):
        return None


def read_table(path):
    """Return (headers or None, data rows). Accepts .csv, .txt and .xlsx."""
    path = Path(path)
    rows = _read_xlsx(path) if path.suffix.lower() in ('.xlsx', '.xlsm') else _read_csv(path)
    rows = [row for row in rows if any(str(cell).strip() for cell in row)]
    if not rows:
        raise ValueError(f'{path} contains no rows')
    headers = None
    if any(number(cell) is None for cell in rows[0]):
        headers, rows = [str(cell).strip() for cell in rows[0]], rows[1:]
    if not rows:
        raise ValueError(f'{path} contains a header but no data rows')
    return headers, rows


def _read_csv(path):
    text = path.read_text()
    first = text.splitlines()[0] if text.splitlines() else ''
    if ';' in first:  # semicolon export, comma decimals
        return [[cell.replace(',', '.') for cell in row]
                for row in csv.reader(text.splitlines(), delimiter=';')]
    return list(csv.reader(text.splitlines()))


def _read_xlsx(path):
    try:
        from openpyxl import load_workbook
    except ImportError as error:
        raise ValueError('Reading .xlsx needs openpyxl: pip install openpyxl') from error
    sheet = load_workbook(path, read_only=True, data_only=True).active
    return [['' if cell is None else cell for cell in row] for row in sheet.values]


def suggest(headers, field, joint):
    """Index of the header naming this field and joint, by alias, or None."""
    wanted = {alias + str(joint) for alias in ALIASES[field]}
    for index, header in enumerate(headers or ()):
        if normalize(header) in wanted:
            return index
    return None


def suggest_mapping(headers, fields):
    """Suggest a column per joint, accepting q0..q6 and one-based q1..q7 headers."""
    mapping = {}
    for field in fields:
        columns = [suggest(headers, field, joint) for joint in range(7)]
        if any(column is None for column in columns):
            shifted = [suggest(headers, field, joint + 1) for joint in range(7)]
            if all(column is not None for column in shifted):
                columns = shifted
        mapping[field] = columns
    return mapping


def check_limits(samples):
    for number_, sample in enumerate(samples, start=1):
        for joint, value in enumerate(sample.get('position', ())):
            low, high = POSITION_LIMITS_RAD[joint]
            if not low <= value <= high:
                raise ValueError(
                    f'Row {number_}: {ARM_JOINTS[joint]} = {value:.4f} rad is outside its limit '
                    f'[{low}, {high}]. Check the declared units and the mapped column.')


def to_trajectory(rows, mapping, *, mode, units, rate_hz=RATE_HZ):
    """Build a trajectory from data rows and a field to seven-column-index mapping."""
    mode = ControlMode(mode)
    fields = MODE_FIELDS[mode]
    if set(mapping) != set(fields):
        raise ValueError(f'{mode.value} mode requires exactly these mapped fields: {list(fields)}')
    if any(len(columns) != 7 or any(column is None for column in columns)
           for columns in mapping.values()):
        raise ValueError('Every mapped field needs seven column indices')
    if units not in ('rad', 'deg'):
        raise ValueError("units must be 'rad' or 'deg'")
    samples = []
    for index, row in enumerate(rows, start=1):
        sample = {}
        for field in fields:
            values = []
            for column in mapping[field]:
                if column >= len(row):
                    raise ValueError(f'Row {index} has no column {column}')
                value = number(row[column])
                if value is None:
                    raise ValueError(f'Row {index}, column {column} is not a number: {row[column]!r}')
                values.append(math.radians(value) if units == 'deg' and field in ANGLE_FIELDS
                              else value)
            sample[field] = values
        samples.append(sample)
    check_limits(samples)
    return Trajectory.from_dict({'schema_version': SCHEMA_VERSION, 'mode': mode.value,
                                 'rate_hz': float(rate_hz), 'joint_names': list(ARM_JOINTS),
                                 'units': UNITS, 'samples': samples})


def save_profile(path, *, mode, units, mapping, headers=None):
    """Record answers so the next table in the same layout needs no prompts."""
    columns = {field: [headers[column] if headers else column for column in indices]
               for field, indices in mapping.items()}
    Path(path).write_text(json.dumps(
        {'schema_version': 1, 'mode': ControlMode(mode).value, 'units': units,
         'columns': columns}, indent=2) + '\n')


def load_profile(path):
    value = json.loads(Path(path).read_text())
    if value.get('schema_version') != 1 or set(value) != {'schema_version', 'mode', 'units', 'columns'}:
        raise ValueError('Expected an import profile with schema_version 1')
    return value


def resolve(profile, headers):
    """Turn a profile's recorded column names or indices into indices for this table."""
    lookup = {normalize(header): index for index, header in enumerate(headers or ())}
    mapping = {}
    for field, columns in profile['columns'].items():
        indices = []
        for column in columns:
            if isinstance(column, int):
                indices.append(column)
            elif normalize(column) in lookup:
                indices.append(lookup[normalize(column)])
            else:
                raise ValueError(f'The profile maps {field} to a missing column: {column!r}')
        mapping[field] = indices
    return mapping


def export(trajectory, path, *, units='rad'):
    """Write a flat t, q0..q6, dq0..dq6 table for use outside this project."""
    if units not in ('rad', 'deg'):
        raise ValueError("units must be 'rad' or 'deg'")
    fields = [field for field in FIELDS if getattr(trajectory.samples[0], field) is not None]
    rows = [['t'] + [f'{SHORT[field]}{joint}' for field in fields for joint in range(7)]]
    for index, sample in enumerate(trajectory.samples):
        row = [f'{index / trajectory.rate_hz:.6f}']
        for field in fields:
            for value in getattr(sample, field).values:
                row.append(f'{math.degrees(value) if units == "deg" and field in ANGLE_FIELDS else value:.9g}')
        rows.append(row)
    path = Path(path)
    if path.suffix.lower() in ('.xlsx', '.xlsm'):
        _write_xlsx(path, rows)
    else:
        with path.open('x', newline='') as stream:
            csv.writer(stream).writerows(rows)
    return path


def _write_xlsx(path, rows):
    try:
        from openpyxl import Workbook
    except ImportError as error:
        raise ValueError('Writing .xlsx needs openpyxl: pip install openpyxl') from error
    if path.exists():
        raise FileExistsError(path)
    book = Workbook()
    for index, row in enumerate(rows):
        book.active.append(row if index == 0 else [float(cell) for cell in row])
    book.save(path)


def import_table(path, *, mode, units, mapping=None, rate_hz=RATE_HZ):
    """Non-interactive import for scripts. Columns are matched by alias when not given."""
    headers, rows = read_table(path)
    fields = MODE_FIELDS[ControlMode(mode)]
    if mapping is None:
        mapping = suggest_mapping(headers, fields)
        missing = {field: [joint for joint, column in enumerate(columns) if column is None]
                   for field, columns in mapping.items()}
        if any(missing.values()):
            raise ValueError(f'No column matched {missing}; supply mapping explicitly. '
                             f'Headers: {headers}')
    return to_trajectory(rows, mapping, mode=mode, units=units, rate_hz=rate_hz)


export_table = export
