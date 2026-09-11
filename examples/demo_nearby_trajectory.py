#!/usr/bin/env python3
"""Preview, approve and execute a small smooth motion from the current pose."""
import argparse
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _demo_support import close_window, ensure_workspace, open_window, save_run  # noqa: E402

from sawyer_control import JointCommandSample, JointVector  # noqa: E402
from sawyer_operations import Robot, Trajectory  # noqa: E402


RATE_HZ = 50.0


def trajectory_from(q0, joint, delta, duration_s):
    count = round(duration_s * RATE_HZ) + 1
    samples = []
    for index in range(count):
        u = index / (count - 1)
        blend = 10*u**3 - 15*u**4 + 6*u**5
        velocity = (30*u**2 - 60*u**3 + 30*u**4) / duration_s
        acceleration = (60*u - 180*u**2 + 120*u**3) / duration_s**2
        q = list(q0)
        dq = [0.0] * 7
        ddq = [0.0] * 7
        q[joint] += delta * blend
        dq[joint] = delta * velocity
        ddq[joint] = delta * acceleration
        samples.append(JointCommandSample(position=JointVector(q), velocity=JointVector(dq),
                                          acceleration=JointVector(ddq)))
    return Trajectory(f'Nearby J{joint} move', 'trajectory', RATE_HZ, tuple(samples))


def previewer(browser):
    client = ensure_workspace()
    return client, open_window(browser, 'preview=1')


def main():
    parser = argparse.ArgumentParser(description='Preview and approve a small nearby Sawyer trajectory.')
    parser.add_argument('--joint', type=int, default=0, choices=range(7))
    parser.add_argument('--distance-rad', type=float, default=.08)
    parser.add_argument('--duration-s', type=float, default=1.0)
    parser.add_argument('--browser', default='auto', help='Browser executable, e.g. chromium or firefox')
    parser.add_argument('--run-name', default='nearby_trajectory',
                        help='Base name under runs/; the same name replaces the previous run')
    args = parser.parse_args()
    if args.distance_rad <= 0 or args.duration_s <= 0:
        parser.error('--distance-rad and --duration-s must be positive')
    if args.browser != 'auto' and shutil.which(args.browser) is None:
        parser.error(f'Browser executable not found: {args.browser}')

    preview, preview_window = previewer(args.browser)
    recording = None
    randomizer = random.SystemRandom()
    try:
        with Robot.connect() as robot:
            robot.force_torque.enable()
            state = robot.state
            if state is None:
                raise RuntimeError('No robot state is available')
            q0 = state['positions']
            while True:
                delta = randomizer.choice((-args.distance_rad, args.distance_rad))
                trajectory = trajectory_from(q0, args.joint, delta, args.duration_s)
                preview_item = preview.load(trajectory)
                preview.preview(preview_item['id'])
                print(f'Previewing J{args.joint}: {q0[args.joint]:+.3f} → {q0[args.joint] + delta:+.3f} rad')
                choice = input('[a]ccept, [r]epeat, or [q]uit: ').strip().lower()
                if choice == 'q':
                    return
                if choice == 'r':
                    continue
                if choice != 'a':
                    print('Choose a, r, or q.')
                    continue
                approved = robot.load_trajectory(trajectory)
                recording = robot.start_recording(args.run_name)
                run = None
                try:
                    run = robot.stream(approved)
                    result = run.wait()
                except KeyboardInterrupt:
                    if run is None:
                        raise
                    result = run.cancel()
                finally:
                    recording.stop()
                print(result['phase'], result['reason'])
                recording_path, trajectory_path = save_run(
                    preview, recording.id, trajectory, args.run_name)
                print(f'Saved {recording_path} and {trajectory_path}')
                print(f'Read it back with: python {Path(__file__).with_name("demo_read_recording.py")}')
                return
    finally:
        close_window(preview_window)
        if recording is not None and recording.closed:
            open_window(args.browser, f'analysis={recording.id}')


if __name__ == '__main__':
    main()
