"""Interactive command line for importing and exporting joint tables."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from sawyer_control.types import ControlMode

from .interop import (MODE_FIELDS, export, load_profile, normalize, read_table,
                      resolve, save_profile, suggest_mapping, to_trajectory)
from .trajectories import ARM_JOINTS, COMMAND_RATE_HZ, MIN_RATE_HZ, Trajectory

MODES = tuple(mode.value for mode in MODE_FIELDS)


def _ask(prompt, default=None):
    answer = input(prompt).strip()
    if not answer and default is not None:
        return default
    if not answer:
        raise ValueError('An answer is required')
    return answer


def _choose_mode():
    menu = '  '.join(f'[{index}] {mode}' for index, mode in enumerate(MODES, start=1))
    while True:
        answer = _ask(f'Mode? {menu}\n> ').lower()
        if answer in MODES:
            return answer
        if answer.isdigit() and 1 <= int(answer) <= len(MODES):
            return MODES[int(answer) - 1]
        print('Answer with a number or a mode name.')


def _choose_units():
    while True:
        answer = _ask('Units of the angle columns? [deg/rad]\n> ').lower()
        if answer in ('deg', 'rad'):
            return answer
        print("Answer 'deg' or 'rad'. Nothing is guessed; a wrong answer commands wrong motion.")


def _choose_rate():
    while True:
        answer = _ask('Samples per second in this table?\n> ')
        try:
            rate = float(answer)
        except ValueError:
            rate = 0
        if rate > 0:
            if rate > COMMAND_RATE_HZ:
                print(f'  Noted. {rate:g} Hz is above the {COMMAND_RATE_HZ:g} Hz the robot is '
                      f'commanded at, so resample it before streaming.')
            return rate
        print('Answer with a positive number. Nothing is assumed; the rows carry no rate.')


def _show_columns(headers, rows):
    names = headers or [f'col{index}' for index in range(len(rows[0]))]
    print('\nColumns:')
    for start in range(0, len(names), 8):
        print('  ' + '  '.join(f'{index}:{name}'
                               for index, name in enumerate(names[start:start + 8], start=start)))
    return names


def _map_columns(names, fields, suggested):
    """Ask for one column per joint per field; Enter accepts the suggestion."""
    print('\nAnswer with a column number or name; Enter accepts the suggestion.')
    mapping = {}
    for field in fields:
        indices = []
        for joint in range(7):
            hint = suggested[field][joint]
            label = f'  {field} {ARM_JOINTS[joint]}'
            hint_text = f'  [{hint}:{names[hint]}]' if hint is not None else ''
            while True:
                try:
                    answer = _ask(f'{label}{hint_text} > ', default=hint)
                except ValueError:
                    print('    No suggestion for this joint; give a column number or name.')
                    continue
                if isinstance(answer, int):
                    index = answer
                elif answer.isdigit() and int(answer) < len(names):
                    index = int(answer)
                else:
                    matches = [position for position, name in enumerate(names)
                               if normalize(name) == normalize(answer)]
                    if not matches:
                        print(f'    No column named {answer!r}.')
                        continue
                    index = matches[0]
                indices.append(index)
                break
        mapping[field] = indices
    return mapping


def _import(args):
    headers, rows = read_table(args.table)
    profile = load_profile(args.profile) if args.profile else None
    mode = args.mode or (profile or {}).get('mode') or _choose_mode()
    fields = MODE_FIELDS[ControlMode(mode)]
    units = args.units or (profile or {}).get('units')
    if units is None:
        units = _choose_units() if any(field != 'effort' for field in fields) else 'rad'
    rate_hz = args.rate or (profile or {}).get('rate_hz')
    if rate_hz is None:
        if args.auto or not sys.stdin.isatty():
            raise ValueError('Pass --rate: the sample rate is never assumed')
        rate_hz = _choose_rate()
    if profile:
        mapping = resolve(profile, headers)
        if set(mapping) != set(fields):
            raise ValueError(f'The profile maps {sorted(mapping)}, but {mode} mode needs {list(fields)}')
        names = headers or [f'col{index}' for index in range(len(rows[0]))]
    else:
        names = headers or [f'col{index}' for index in range(len(rows[0]))]
        suggested = suggest_mapping(headers, fields)
        if args.auto or not sys.stdin.isatty():
            missing = {field: [ARM_JOINTS[joint] for joint, column in enumerate(columns)
                               if column is None] for field, columns in suggested.items()}
            if any(missing.values()):
                raise ValueError(f'No column matched {missing}; map it interactively or with '
                                 f'--profile. Headers: {names}')
            mapping = suggested
        else:
            names = _show_columns(headers, rows)
            mapping = _map_columns(names, fields, suggested)
    trajectory = to_trajectory(rows, mapping, mode=mode, units=units, rate_hz=rate_hz)
    trajectory.save(args.output)
    conversion = 'deg -> rad' if units == 'deg' else 'rad'
    print(f'\nRead {len(rows)} rows, {trajectory.rate_hz:g} Hz, {trajectory.duration_s:.2f} s, {conversion}.')
    print(f'Mapped ' + ', '.join(f'{field}={[names[column] for column in columns]}'
                                 for field, columns in mapping.items()))
    print(f'Wrote {args.output}')
    if args.save_profile:
        save_profile(args.save_profile, mode=mode, units=units, rate_hz=rate_hz,
                     mapping=mapping, headers=headers)
        print(f'Wrote {args.save_profile}')


def _export(args):
    export(Trajectory.load(args.trajectory), args.output, units=args.units)
    print(f'Wrote {args.output}')


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog='sawyer-traj', description='Map joint tables to and from canonical trajectories. '
        'Sampling is uniform at the rate you give; it is never assumed, and any time '
        'column is ignored.')
    commands = parser.add_subparsers(dest='command', required=True)

    importer = commands.add_parser('import', help='map a csv or xlsx table into trajectory JSON')
    importer.add_argument('table')
    importer.add_argument('-o', '--output', required=True, help='trajectory JSON to create')
    importer.add_argument('--mode', choices=MODES, help='skip the mode prompt')
    importer.add_argument('--units', choices=('deg', 'rad'), help='skip the units prompt')
    importer.add_argument('--rate', type=float,
                          help='samples per second the rows are at; skips the prompt and is '
                               'required with --auto')
    importer.add_argument('--auto', action='store_true',
                          help='accept every alias-matched column without prompting')
    importer.add_argument('--profile', help='replay a saved mapping instead of prompting')
    importer.add_argument('--save-profile', help='record this mapping for the next table')
    importer.set_defaults(function=_import)

    exporter = commands.add_parser('export', help='write a flat t, q0..q6 table')
    exporter.add_argument('trajectory')
    exporter.add_argument('-o', '--output', required=True)
    exporter.add_argument('--units', choices=('deg', 'rad'), default='rad')
    exporter.set_defaults(function=_export)

    args = parser.parse_args(argv)
    try:
        args.function(args)
    except FileExistsError as error:
        print(f'{error.filename or error} already exists; files are never overwritten.', file=sys.stderr)
        return 1
    except (ValueError, KeyboardInterrupt, EOFError) as error:
        print(f'{error or "cancelled"}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
