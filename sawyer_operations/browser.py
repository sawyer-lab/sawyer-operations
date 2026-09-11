"""Launch an independently owned browser window for local viewers."""
import argparse
import os
import shutil
import signal
import subprocess
import tempfile
import webbrowser


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--browser', default='auto')
    parser.add_argument('--url', default='http://127.0.0.1:8001/?preview=1')
    args = parser.parse_args()
    name = args.browser
    if name == 'auto':
        name = next((x for x in ('chromium', 'chromium-browser', 'google-chrome', 'firefox')
                     if shutil.which(x)), None)
    if name is None:
        print('Opening the default browser; close its tab manually when finished.', flush=True)
        if not webbrowser.open(args.url):
            raise SystemExit(f'Open {args.url} in a WebGL browser')
        return
    executable = shutil.which(name)
    if executable is None:
        raise SystemExit(f'Browser executable not found: {name}')
    if not any(x in os.path.basename(executable) for x in ('chromium', 'chrome', 'firefox')):
        raise SystemExit('Use a Chromium-based browser or Firefox for an independently owned window')
    with tempfile.TemporaryDirectory(prefix='sawyer-viewer-') as profile:
        command = ([executable, '--no-remote', '--profile', profile, '--new-window', args.url]
                   if 'firefox' in os.path.basename(executable) else
                   [executable, f'--user-data-dir={profile}', '--no-first-run',
                    '--no-default-browser-check', f'--app={args.url}'])
        child = subprocess.Popen(command, start_new_session=True)
        def stop(*_):
            raise KeyboardInterrupt
        signal.signal(signal.SIGTERM, stop)
        try:
            child.wait()
        except KeyboardInterrupt:
            pass
        finally:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()


if __name__ == '__main__':
    main()
