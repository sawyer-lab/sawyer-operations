"""Load and preview a trajectory in the running workspace; no robot commands."""
import argparse

from sawyer_operations import Workspace

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('trajectory', help='Trajectory JSON file')
parser.add_argument('--address', default='http://127.0.0.1:8001')
args = parser.parse_args()
workspace = Workspace(args.address)
loaded = workspace.load(args.trajectory)
workspace.preview(loaded['id'])
print('Selected preview:', loaded)
