#!/usr/bin/env python3
"""Run one stored trajectory through the local operations session."""
import argparse
from pathlib import Path

from sawyer_operations import Robot


def main():
    parser = argparse.ArgumentParser(description='Stream one Sawyer trajectory with recording and guards.')
    parser.add_argument('trajectory', type=Path)
    parser.add_argument('--recording')
    parser.add_argument('--force-torque', action='store_true')
    parser.add_argument('--preview', action='store_true')
    args = parser.parse_args()

    with Robot.connect() as robot:
        trajectory = robot.load_trajectory(args.trajectory)
        if args.force_torque:
            robot.force_torque.enable()
        if args.preview:
            robot.show_preview(trajectory)
        recording = robot.start_recording(args.recording) if args.recording else None
        run = robot.stream(trajectory)
        try:
            result = run.wait()
        except KeyboardInterrupt:
            result = run.cancel()
        finally:
            if recording is not None:
                recording.stop()
        print(result['phase'], result['reason'])


if __name__ == '__main__':
    main()
