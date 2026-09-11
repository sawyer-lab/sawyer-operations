"""Record through the shared service until Ctrl-C, then download the JSONL file."""
import argparse
import time

from sawyer_operations import Workspace

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('output', help='New JSONL output file')
parser.add_argument('--address', default='http://127.0.0.1:8001')
args = parser.parse_args()
workspace = Workspace(args.address)
recording = workspace.start_recording('Python recording')
try:
    print('Recording', recording['id'], '— Ctrl-C to finish')
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    workspace.stop_recording()
    workspace.download_recording(recording['id'], args.output)
    print('Saved', args.output)
