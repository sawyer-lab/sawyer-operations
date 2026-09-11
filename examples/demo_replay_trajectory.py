#!/usr/bin/env python3
"""Import a recorded replay table, resample it to the command rate, and run it.

The table in data/replay_results.csv is sampled at 1000 Hz, ten times the rate
the robot is commanded at. It is imported at its own rate, resampled once and
explicitly to 100 Hz, and previewed. If the arm is not already at the first
sample, a slow quintic approach move is previewed and accepted separately
before the replay itself is offered. Nothing moves without an explicit accept.
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _demo_support import close_window, ensure_workspace, open_window, save_run  # noqa: E402

from sawyer_control.types import ControlMode, JointCommandSample, JointVector  # noqa: E402
from sawyer_operations import COMMAND_RATE_HZ, Robot, Trajectory  # noqa: E402
from sawyer_operations.interop import POSITION_LIMITS_RAD, import_table  # noqa: E402
from sawyer_operations.trajectories import ARM_JOINTS  # noqa: E402

TABLE = Path(__file__).resolve().parents[1] / 'data' / 'replay_results.csv'
SOURCE_RATE_HZ = 1000.0


def approach_trajectory(start, target, mode, max_speed_rad_s):
    """A slow quintic move from the arm's pose to the first sample of the replay.

    The quintic starts and ends at rest, and its peak speed is 1.875*delta/T,
    which is what sizes the duration.
    """
    deltas = [end - begin for begin, end in zip(start, target)]
    travel = max(abs(delta) for delta in deltas)
    if travel == 0:
        return None
    duration_s = max(1.875 * travel / max_speed_rad_s, 1.5)
    count = round(duration_s * COMMAND_RATE_HZ) + 1
    samples = []
    for index in range(count):
        u = index / (count - 1)
        blend = 10*u**3 - 15*u**4 + 6*u**5
        speed = (30*u**2 - 60*u**3 + 30*u**4) / duration_s
        rate = (60*u - 180*u**2 + 120*u**3) / duration_s**2
        position = JointVector(begin + delta * blend for begin, delta in zip(start, deltas))
        if mode is ControlMode.TRAJECTORY:
            samples.append(JointCommandSample(
                position=position,
                velocity=JointVector(delta * speed for delta in deltas),
                acceleration=JointVector(delta * rate for delta in deltas)))
        else:
            samples.append(JointCommandSample(position=position))
    return Trajectory(mode, tuple(samples), COMMAND_RATE_HZ)


def offer(robot, preview, trajectory, label):
    """Preview one trajectory and stream it only if it is accepted."""
    item = preview.load(trajectory)
    preview.preview(item['id'])
    print(f'\nPreviewing {label}: {trajectory.span_s:.2f} s in the viewer.')
    if input(f'[a]ccept and run {label}, or [q]uit: ').strip().lower() != 'a':
        return None
    approved = robot.load_trajectory(trajectory)
    run = None
    try:
        run = robot.stream(approved)
        result = run.wait()
    except KeyboardInterrupt:
        if run is None:
            raise
        result = run.cancel()
    print(f"{label}: {result['phase']} {result['reason']}")
    return result


def describe(trajectory, label):
    summary = trajectory.summary()
    print(f"{label}: {summary['samples']} samples at {summary['rate_hz']:g} Hz, "
          f"{trajectory.span_s:.2f} s")
    return summary


def report_limits(trajectory):
    print('Joint travel against the arm limits:')
    for joint, name in enumerate(ARM_JOINTS):
        values = [sample.position.values[joint] for sample in trajectory.samples]
        low, high = POSITION_LIMITS_RAD[joint]
        print(f'  {name}: {min(values):+.4f} .. {max(values):+.4f} rad   '
              f'limit [{low}, {high}]   margin {min(min(values)-low, high-max(values)):+.4f}')


def report_start(robot, trajectory):
    """The executor refuses to start unless the arm already sits at the first sample."""
    target = trajectory.samples[0].position.values
    state = robot.state
    print('\nStart pose the trajectory begins at:')
    print('  ' + '  '.join(f'{value:+.3f}' for value in target))
    if state is None:
        print('  No robot state is available; the stream would be rejected.')
        return None
    error = max(abs(a - b) for a, b in zip(state['positions'], target))
    print('Arm is now at:')
    print('  ' + '  '.join(f'{value:+.3f}' for value in state['positions']))
    print(f'Largest joint error: {error:.4f} rad')
    if error > .05:
        print('  This exceeds the 0.05 rad start guard, so an approach move is offered first.')
    return error


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--table', type=Path, default=TABLE)
    parser.add_argument('--source-rate', type=float, default=SOURCE_RATE_HZ,
                        help=f'rate the rows are at (default {SOURCE_RATE_HZ:g})')
    parser.add_argument('--rate', type=float, default=COMMAND_RATE_HZ,
                        help=f'rate to resample to (default {COMMAND_RATE_HZ:g})')
    parser.add_argument('--speed', type=float, default=1.0,
                        help='play slower or faster; 0.5 is half speed, and scales the '
                             'velocity and acceleration to match')
    parser.add_argument('--mode', default='trajectory', choices=('position', 'trajectory'))
    parser.add_argument('--units', default='rad', choices=('rad', 'deg'))
    parser.add_argument('--browser', default='auto')
    parser.add_argument('--run-name', default='replay')
    parser.add_argument('--approach-speed', type=float, default=.2,
                        help='peak joint speed of the approach move in rad/s (default 0.2)')
    parser.add_argument('--no-approach', action='store_true',
                        help='assume the arm is already at the first sample')
    parser.add_argument('--dry-run', action='store_true',
                        help='import, resample and report without a robot or a viewer')
    args = parser.parse_args()
    if args.browser != 'auto' and shutil.which(args.browser) is None:
        parser.error(f'Browser executable not found: {args.browser}')
    if not args.table.is_file():
        raise SystemExit(f'No table at {args.table}')

    source = import_table(args.table, mode=args.mode, units=args.units, rate_hz=args.source_rate)
    describe(source, f'Imported {args.table.name}')
    trajectory = source.resampled_to(args.rate)
    describe(trajectory, f'Resampled to {args.rate:g} Hz')
    if args.speed != 1.0:
        trajectory = trajectory.at_speed(args.speed)
        describe(trajectory, f'At {args.speed:g}x speed')
    report_limits(trajectory)
    if trajectory.rate_hz > COMMAND_RATE_HZ:
        raise SystemExit(f'{trajectory.rate_hz:g} Hz is above the {COMMAND_RATE_HZ:g} Hz command '
                         f'rate; streaming would be rejected. Choose a lower --rate.')
    if args.dry_run:
        return

    preview = ensure_workspace()
    window = open_window(args.browser, 'preview=1')
    recording = None
    try:
        item = preview.load(trajectory)
        preview.preview(item['id'])
        print(f"\nPreviewing {trajectory.span_s:.2f} s of motion in the viewer.")
        with Robot.connect() as robot:
            robot.force_torque.enable()
            robot.wait_for_state()
            error = report_start(robot, trajectory)
            if error is None:
                return
            if error > .05 and not args.no_approach:
                approach = approach_trajectory(robot.state['positions'],
                                               trajectory.samples[0].position.values,
                                               trajectory.mode, args.approach_speed)
                result = offer(robot, preview, approach, 'the approach move')
                if result is None:
                    return
                if result['phase'] != 'completed':
                    print('The approach did not complete; not running the replay.')
                    return
                robot.wait_for_state()
                report_start(robot, trajectory)
            recording = robot.start_recording(args.run_name)
            try:
                result = offer(robot, preview, trajectory, 'the replay')
            finally:
                recording.stop()
            if result is None:
                return
            paths = save_run(preview, recording.id, trajectory, args.run_name)
            print('Saved ' + ' and '.join(str(path) for path in paths))
            print(f"Read it back with: python {Path(__file__).with_name('demo_read_recording.py')} "
                  f'--run-name {args.run_name}')
    finally:
        close_window(window)
        if recording is not None and recording.closed:
            open_window(args.browser, f'analysis={recording.id}')


if __name__ == '__main__':
    main()
