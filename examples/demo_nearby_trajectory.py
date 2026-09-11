#!/usr/bin/env python3
"""Preview, approve and execute a small smooth motion from the current pose."""
import argparse
import random
import shutil
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError

from sawyer_control import JointCommandSample, JointVector
from sawyer_operations import Robot, Trajectory, Workspace


RATE_HZ = 50.0
ROOT = Path(__file__).resolve().parents[1]


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


def open_window(browser, query):
    return subprocess.Popen([sys.executable, '-m', 'sawyer_operations.browser',
                             '--browser', browser, '--url', f'http://127.0.0.1:8001/?{query}'],
                            cwd=ROOT, start_new_session=True)


def previewer(browser):
    client = Workspace()
    try:
        client.state()
    except (RuntimeError, URLError):
        subprocess.Popen([sys.executable, '-m', 'uvicorn',
                          'sawyer_operations.server:app', '--host', '127.0.0.1', '--port', '8001'], cwd=ROOT,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                client.state()
                break
            except (RuntimeError, URLError):
                time.sleep(.25)
        else:
            raise RuntimeError('Previewer did not start at http://127.0.0.1:8001')
    window = open_window(browser, 'preview=1')
    return client, window


def close_preview(window):
    if window.poll() is None:
        window.terminate()
        try:
            window.wait(timeout=8)
        except subprocess.TimeoutExpired:
            window.kill()


def main():
    parser = argparse.ArgumentParser(description='Preview and approve a small nearby Sawyer trajectory.')
    parser.add_argument('--joint', type=int, default=0, choices=range(7))
    parser.add_argument('--distance-rad', type=float, default=.08)
    parser.add_argument('--duration-s', type=float, default=1.0)
    parser.add_argument('--browser', default='auto', help='Browser executable, e.g. chromium or firefox')
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
                recording = robot.start_recording('nearby_trajectory')
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
                return
    finally:
        close_preview(preview_window)
        if recording is not None and recording.closed:
            open_window(args.browser, f'analysis={recording.id}')


if __name__ == '__main__':
    main()
