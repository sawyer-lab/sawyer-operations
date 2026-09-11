"""Synchronous Python client for a shared operations service."""
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .trajectories import Trajectory


class Workspace:
    def __init__(self, address='http://127.0.0.1:8001', timeout=20):
        self.address = address.rstrip('/')
        self.timeout = timeout

    def _request(self, path, value=None):
        data = json.dumps(value, allow_nan=False).encode() if value is not None else None
        request = Request(self.address+'/api'+path, data=data,
                          headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            raise RuntimeError(json.loads(exc.read()).get('detail', str(exc))) from exc

    def state(self):
        return self._request('/workspace')

    def load(self, trajectory):
        if isinstance(trajectory, (str, Path)):
            trajectory = Trajectory.load(trajectory)
        return self._request('/trajectories', trajectory.to_dict())

    def preview(self, trajectory_id):
        return self._request('/preview', {'id': trajectory_id})

    def command(self, action):
        return self._request('/robot/command', {'action': action})

    def stop(self):
        return self.command('stop')

    def start_recording(self, name='Recording'):
        return self._request('/recordings', {'name': name})

    def stop_recording(self):
        return self._request('/recordings/stop', {})

    def recordings(self):
        return self._request('/recordings')

    def download_recording(self, recording_id, path):
        with urlopen(self.address+'/api/recordings/'+recording_id+'/download', timeout=self.timeout) as response:
            with Path(path).open('xb') as output:
                while chunk := response.read(1024*1024):
                    output.write(chunk)
