import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from sawyer_operations.server import app
from sawyer_operations import Operations


def link():
    api = SimpleNamespace(OpenGripper=AsyncMock(return_value=SimpleNamespace(success=True, message='')),
                          CloseGripper=AsyncMock(return_value=SimpleNamespace(success=False, message='tool down')))
    return SimpleNamespace(api=api, command_lock=asyncio.Lock(), gripper={'state':'down'},
                           snapshot=lambda: {'connected':False})


def test_page_and_status_are_passive():
    app.state.link = link()
    client = TestClient(app)
    assert client.get('/').status_code == 200
    assert client.get('/api/health').json()['connected'] is False
    app.state.link.api.OpenGripper.assert_not_called()
    app.state.link.api.CloseGripper.assert_not_called()


def test_explicit_commands_and_failure_are_forwarded_without_retry(tmp_path, monkeypatch):
    app.state.link = link()
    monkeypatch.setattr(app.state, 'operations', Operations(app.state.link.api, tmp_path), raising=False)
    client = TestClient(app)
    assert client.post('/api/gripper',json={'action':'open'}).status_code == 200
    failed = client.post('/api/gripper',json={'action':'close'})
    assert failed.status_code == 502 and failed.json()['detail'] == 'tool down'
    app.state.link.api.OpenGripper.assert_awaited_once()
    app.state.link.api.CloseGripper.assert_awaited_once()
    assert client.post('/api/gripper',json={'action':'enable'}).status_code == 422
