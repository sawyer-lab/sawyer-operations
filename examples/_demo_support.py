"""Shared helpers for the example scripts.

Holds the local workspace connection, viewer windows and the untracked `runs/`
directory the demos write their latest run into.
"""
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError

from sawyer_operations import Workspace

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / 'runs'
ADDRESS = 'http://127.0.0.1:8001'


def ensure_workspace(timeout_s=15):
    """Return a client for the local workspace, starting the server if it is down."""
    client = Workspace(ADDRESS)
    try:
        client.state()
        return client
    except (RuntimeError, URLError):
        pass
    subprocess.Popen([sys.executable, '-m', 'uvicorn', 'sawyer_operations.server:app',
                      '--host', '127.0.0.1', '--port', '8001'], cwd=ROOT,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            client.state()
            return client
        except (RuntimeError, URLError):
            time.sleep(.25)
    raise RuntimeError(f'Workspace did not start at {ADDRESS}')


def open_window(browser, query):
    return subprocess.Popen([sys.executable, '-m', 'sawyer_operations.browser',
                             '--browser', browser, '--url', f'{ADDRESS}/?{query}'],
                            cwd=ROOT, start_new_session=True)


def close_window(window):
    if window is not None and window.poll() is None:
        window.terminate()
        try:
            window.wait(timeout=8)
        except subprocess.TimeoutExpired:
            window.kill()


def run_paths(name):
    """Fixed paths for the latest run, so repeated demo runs replace one another."""
    RUNS.mkdir(exist_ok=True)
    return RUNS / f'{name}.jsonl', RUNS / f'{name}.json'


def save_run(client, recording_id, trajectory, name):
    """Copy a finished recording and its trajectory into runs/, replacing the last run."""
    recording_path, trajectory_path = run_paths(name)
    recording_path.unlink(missing_ok=True)
    trajectory_path.unlink(missing_ok=True)
    client.download_recording(recording_id, recording_path)
    trajectory.save(trajectory_path)
    return recording_path, trajectory_path
