from contextlib import asynccontextmanager
import asyncio
import os
from pathlib import Path
from typing import Literal

import grpc
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .operations import Operations
from .routes import router

ROOT = Path(__file__).resolve().parents[1]


@asynccontextmanager
async def lifespan(app):
    async with Operations.connect(os.environ.get('SAWYER_ADDRESS', '127.0.0.1:50051'),
                                  os.environ.get('SAWYER_OPERATIONS_DATA', '~/.local/share/sawyer-operations')) as ops:
        app.state.operations = ops
        app.state.link = ops.link
        yield


app = FastAPI(lifespan=lifespan)
app.include_router(router)


@app.exception_handler(ValueError)
async def invalid(request, exc):
    return JSONResponse({'detail': str(exc)}, status_code=422)


@app.exception_handler(KeyError)
async def missing(request, exc):
    return JSONResponse({'detail': f'Missing item or field: {exc}'}, status_code=404)


@app.exception_handler(RuntimeError)
async def conflict(request, exc):
    return JSONResponse({'detail': str(exc)}, status_code=409)


@app.exception_handler(grpc.RpcError)
async def bridge_error(request, exc):
    return JSONResponse({'detail': exc.details() or exc.code().name}, status_code=502)


@app.get('/api/health')
async def health():
    return {'app': 'sawyer-operations', **app.state.link.snapshot()}


@app.websocket('/api/live')
async def live(socket: WebSocket):
    await socket.accept()
    revision = -1
    try:
        while True:
            snapshot = app.state.link.snapshot()
            ops = app.state.operations
            # Send the catalog/events only when changed, but recording counts each frame.
            if revision != ops.revision:
                snapshot['workspace'] = ops.snapshot()
                revision = ops.revision
            snapshot['recording'] = ops.recorder.active
            snapshot['recording_error'] = ops.recorder.error
            await socket.send_json(snapshot)
            await asyncio.sleep(1/30)
    except (WebSocketDisconnect, RuntimeError):
        pass


class GripperCommand(BaseModel):
    action: Literal['open', 'close']


@app.post('/api/gripper')
async def gripper(command: GripperCommand, request: Request):
    origin = request.headers.get('origin')
    if origin and origin != str(request.base_url).rstrip('/'):
        raise HTTPException(403, 'Use the workspace page to send commands')
    try:
        return await app.state.operations.command(command.action)
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc


app.mount('/', StaticFiles(directory=ROOT / 'web/dist', html=True, check_dir=False), name='web')
