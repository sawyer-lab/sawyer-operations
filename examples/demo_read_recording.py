#!/usr/bin/env python3
"""Summarize the recording saved by demo_nearby_trajectory.py and open the viewer.

The motion demo writes its latest run to runs/<name>.jsonl. This script reads
that file row by row, prints what it contains, and opens the same recording in
the browser analysis view. It sends no robot command and needs no robot.
"""
import argparse
import collections
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _demo_support import close_window, ensure_workspace, open_window, run_paths  # noqa: E402

from sawyer_operations import Trajectory, read_recording  # noqa: E402


def summarize(path):
    """Walk the recording once, keeping only counts and the first and last rows."""
    metadata = end = None
    types, streams, stages, events = (collections.Counter() for _ in range(4))
    for row in read_recording(path):
        types[row['type']] += 1
        if row['type'] == 'metadata':
            metadata = row
        elif row['type'] == 'end':
            end = row
        elif row['type'] == 'observation':
            streams[row['stream']] += 1
        elif row['type'] == 'command':
            stages[row['stage']] += 1
        elif row['type'] == 'event':
            events[row['event']] += 1
    return metadata, end, types, streams, stages, events


def report(path, trajectory_path):
    metadata, end, types, streams, stages, events = summarize(path)
    if metadata is None:
        raise SystemExit(f'{path} has no metadata header; it is not a recording')
    print(f'{path}  ({path.stat().st_size / 1024:.0f} KiB)')
    print(f"  name      {metadata['name']}  id {metadata['id']}")
    print(f"  started   {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(metadata['started_at']))}")
    print(f"  signals   {', '.join(metadata['signals'])}")
    if end is None:
        print('  end       missing: the recording was not finalized')
    else:
        print(f"  duration  {end['finished_at'] - metadata['started_at']:.2f} s"
              f"  over {types.total()} rows")
    for label, counter in (('rows', types), ('observations', streams),
                           ('commands', stages), ('events', events)):
        if counter:
            print(f"  {label:<13}" + ', '.join(f'{name} {count}' for name, count in counter.items()))
    if trajectory_path.is_file():
        trajectory = Trajectory.load(trajectory_path)
        summary = trajectory.summary()
        print(f"{trajectory_path}\n  {summary['mode']} mode, {summary['samples']} samples at "
              f"{summary['rate_hz']:g} Hz, {summary['duration_s']:.2f} s")
    return metadata['id']


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--run-name', default='nearby_trajectory',
                        help='Base name under runs/ to read')
    parser.add_argument('--browser', default='auto', help='Browser executable, e.g. chromium')
    parser.add_argument('--no-viewer', action='store_true', help='Print the summary only')
    args = parser.parse_args()
    if args.browser != 'auto' and shutil.which(args.browser) is None:
        parser.error(f'Browser executable not found: {args.browser}')

    recording_path, trajectory_path = run_paths(args.run_name)
    if not recording_path.is_file():
        raise SystemExit(f'No recording at {recording_path}. '
                         'Run demo_nearby_trajectory.py and accept a motion first.')
    identity = report(recording_path, trajectory_path)
    if args.no_viewer:
        return

    client = ensure_workspace()
    if not any(row['id'] == identity for row in client.recordings()):
        print(f'\nThe workspace no longer stores recording {identity}, so the analysis view '
              'cannot open it. The saved file above is still complete.')
        return
    print('\nOpening the analysis view. Close the window, or press Ctrl-C, to finish.')
    window = open_window(args.browser, f'analysis={identity}')
    try:
        window.wait()
    except KeyboardInterrupt:
        pass
    finally:
        close_window(window)


if __name__ == '__main__':
    main()
