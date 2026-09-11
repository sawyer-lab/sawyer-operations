from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict
from typing import Literal

from sawyer_control.types import ControlMode

from .trajectories import Trajectory

router = APIRouter(prefix='/api')


def operations(request):
    return request.app.state.operations


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Selection(Input):
    id: str | None


class Recording(Input):
    name: str = 'Recording'


class Command(Input):
    action: Literal['stop', 'enable', 'disable', 'reset', 'open', 'close']


class CSVTrajectory(Input):
    text: str
    mode: ControlMode
    rate_hz: float


@router.get('/workspace')
async def workspace(request: Request):
    return operations(request).snapshot()


@router.post('/trajectories')
async def load(value: dict, request: Request):
    return operations(request).load(Trajectory.from_dict(value))


@router.post('/trajectories/csv')
async def load_csv(value: CSVTrajectory, request: Request):
    return operations(request).load(Trajectory.from_csv(**value.model_dump()))


@router.get('/trajectories/{identity}')
async def trajectory(identity: str, request: Request):
    return operations(request).trajectories[identity].to_dict()


@router.post('/preview')
async def preview(value: Selection, request: Request):
    operations(request).preview(value.id)
    return {'selected_trajectory': value.id}


@router.post('/robot/command')
async def command(value: Command, request: Request):
    return await operations(request).command(value.action)


@router.post('/recordings')
async def record(value: Recording, request: Request):
    return operations(request).start_recording(value.name)


@router.post('/recordings/stop')
async def stop_recording(request: Request):
    return operations(request).stop_recording()


@router.get('/recordings')
async def recordings(request: Request):
    return operations(request).recorder.list()


@router.get('/recordings/{identity}/download')
async def download(identity: str, request: Request):
    return FileResponse(operations(request).recorder.path(identity),
                        media_type='application/x-ndjson', filename=f'{identity}.jsonl')
