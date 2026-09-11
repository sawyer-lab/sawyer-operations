import asyncio
from contextlib import asynccontextmanager
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import pytest
from sawyer_control.types import JointCommandSample, JointVector
from sawyer_control.v1 import control_pb2 as pb
from sawyer_operations import Operations, Robot, Trajectory, read_recording
from sawyer_operations.server import app


def trajectory(mode='position'):
    return Trajectory('Example', mode, 10, (
        JointCommandSample(position=JointVector([0]*7)),
        JointCommandSample(position=JointVector([.1]*7))))


def api():
    return SimpleNamespace(Stop=AsyncMock(return_value=pb.CommandResult(success=True)),
                           CommandJoints=AsyncMock(return_value=pb.CommandResult(success=True)))


def test_validation_and_csv():
    value = trajectory().to_dict()
    assert Trajectory.from_dict(value).to_dict() == value
    value['samples'][0]['position'][2] = float('nan')
    with pytest.raises(ValueError):
        Trajectory.from_dict(value)
    with pytest.raises(ValueError):
        trajectory('trajectory')
    text = ','.join('position.right_j'+str(i) for i in range(7))+'\n'+','.join(['0']*7)
    assert Trajectory.from_csv(text, name='CSV', mode='position', rate_hz=10).summary()['samples'] == 1
    with pytest.raises(ValueError):
        Trajectory.from_csv('j0,j1\n0,0', name='CSV', mode='position', rate_hz=10)


def test_preview_is_passive_and_catalog_survives_restart(tmp_path):
    bridge = api()
    ops = Operations(bridge, tmp_path)
    loaded = ops.load(trajectory())
    ops.preview(loaded['id'])
    assert ops.snapshot()['selected_trajectory'] == loaded['id']
    bridge.Stop.assert_not_called()
    restored = Operations(bridge, tmp_path)
    assert restored.trajectories[loaded['id']].to_dict() == trajectory().to_dict()
    assert restored.selected is None


def test_recording_selection_events_and_no_overwrite(tmp_path):
    ops = Operations(api(), tmp_path)
    recording = ops.start_recording('Trace')
    ops.telemetry({'timestamp_s': 123, 'positions': [0]*7, 'efforts': [4]*7}, {'state': 'ready'})
    ops.event('annotation', text='first sample')
    result = ops.stop_recording()
    assert result['samples'] == 1
    rows = list(read_recording(ops.recorder.path(recording['id'])))
    sample = next(row for row in rows if row['type'] == 'observation')
    assert sample['clock']['source_time_ns'] == 123_000_000_000
    assert set(sample['values']) == {'positions', 'velocities', 'efforts', 'pose', 'enabled', 'stopped', 'gripper'}
    assert any(row.get('event') == 'annotation' for row in rows)
    assert rows[-1]['type'] == 'end'
    with pytest.raises(ValueError):
        ops.recorder.path('../outside')


def test_stream_rejects_an_initial_pose_mismatch(tmp_path):
    async def run():
        bridge = api()
        ops = Operations(bridge, tmp_path)
        ops.telemetry({'timestamp_s': 1, 'positions': [.1]*7}, {})
        loaded = ops.load(trajectory())
        result = await ops.start_stream(loaded['id'])
        assert result['phase'] == 'rejected'
        assert result['reason'] == 'start_mismatch'
        bridge.CommandJoints.assert_not_awaited()
    asyncio.run(run())


def test_stream_cancellation_stops_future_publication_and_records_commands(tmp_path):
    async def run():
        bridge = api()
        ops = Operations(bridge, tmp_path)
        ops.telemetry({'timestamp_s': 1, 'positions': [0]*7}, {})
        loaded = ops.load(Trajectory('Slow', 'position', 1, (
            JointCommandSample(position=JointVector([0]*7)),
            JointCommandSample(position=JointVector([.01]*7)),
        )))
        recording = ops.start_recording('Stream')
        stream = await ops.start_stream(loaded['id'])
        await asyncio.sleep(.01)
        result = await ops.cancel_stream(stream['id'])
        ops.stop_recording()
        assert result['phase'] == 'cancelled'
        assert bridge.CommandJoints.await_count <= 1
        rows = list(read_recording(ops.recorder.path(recording['id'])))
        stages = [row['stage'] for row in rows if row['type'] == 'command']
        assert stages[:3] == ['scheduled', 'attempted', 'acknowledged']
        assert stages.count('attempted') == 1
    asyncio.run(run())


def test_stream_stops_after_sustained_tracking_divergence(tmp_path):
    async def run():
        bridge = api()
        ops = Operations(bridge, tmp_path)
        ops.telemetry({'timestamp_s': 1, 'positions': [0]*7}, {})
        loaded = ops.load(Trajectory('Guarded', 'position', 20, tuple(
            JointCommandSample(position=JointVector([0]*7)) for _ in range(20))))
        stream = await ops.start_stream(loaded['id'])
        for timestamp in range(2, 5):
            ops.telemetry({'timestamp_s': timestamp, 'positions': [1]*7}, {})
            await asyncio.sleep(.06)
        result = await ops.cancel_stream(stream['id'])
        assert result['phase'] == 'stopped'
        assert result['reason'] == 'tracking_diverged'
    asyncio.run(run())


def test_robot_facade_owns_a_direct_session(tmp_path, monkeypatch):
    class Streams:
        def snapshot(self):
            return [{'id': 'run-1', 'phase': 'completed', 'reason': 'all_samples_published'}]

    class FakeOperations:
        def __init__(self):
            self.streams = Streams()
            self.previewed = None
            self.force_torque_enabled = False
            self.recording_stopped = False

        def load(self, value):
            self.trajectory = value
            return {'id': 'trajectory-1'}

        def preview(self, identity):
            self.previewed = identity

        def start_recording(self, name):
            return {'id': 'recording-1', 'name': name}

        def stop_recording(self):
            self.recording_stopped = True

        async def start_stream(self, identity):
            return {'id': 'run-1'}

        async def cancel_stream(self, identity):
            return {'id': identity, 'phase': 'cancelled'}

        async def command(self, action):
            return {'action': action}

        async def enable_force_torque(self):
            self.force_torque_enabled = True

    fake = FakeOperations()

    class Context:
        async def __aenter__(self):
            return fake

        async def __aexit__(self, *exc):
            return None

    monkeypatch.setattr('sawyer_operations.robot.Operations.connect', classmethod(lambda cls: Context()))
    path = tmp_path / 'trajectory.json'
    trajectory().save(path)
    with Robot.connect() as robot:
        loaded = robot.load_trajectory(path)
        robot.show_preview(loaded)
        robot.force_torque.enable()
        recording = robot.start_recording('Trial')
        assert robot.stream(loaded).wait()['phase'] == 'completed'
        recording.stop()
    assert fake.previewed == 'trajectory-1'
    assert fake.force_torque_enabled and fake.recording_stopped


def test_api_and_websocket_share_submissions(tmp_path, monkeypatch):
    bridge = api()
    @asynccontextmanager
    async def lifespan(application):
        ops = Operations(bridge, tmp_path)
        application.state.operations = ops
        application.state.link = SimpleNamespace(snapshot=lambda: {'connected': False})
        yield
        await ops.close()
        del application.state.operations

    monkeypatch.setattr(app.router, 'lifespan_context', lifespan)
    with TestClient(app) as client:
        loaded = client.post('/api/trajectories', json=trajectory().to_dict()).json()
        assert client.post('/api/preview', json={'id': loaded['id']}).status_code == 200
        with client.websocket_connect('/api/live') as socket:
            state = socket.receive_json()
            assert state['workspace']['selected_trajectory'] == loaded['id']
        record = client.post('/api/recordings', json={'name': 'HTTP recording'}).json()
        assert client.post('/api/recordings/stop').status_code == 200
        content = client.get('/api/recordings/'+record['id']+'/download').text
        assert any(json.loads(line).get('event') == 'recording.started' for line in content.splitlines())
    bridge.Stop.assert_not_called()
