# Sawyer operations and workspace

A local browser workspace and Python library for operating a Rethink Sawyer
through [`sawyer-control`](https://github.com/sawyer-lab/sawyer-control): an
interactive 3D model, live seven-joint arm state, trajectory loading and
preview, explicit gripper commands, telemetry recording and offline analysis.

This project talks only to the local `sawyer-control` bridge over gRPC. It has
no ROS or MuJoCo runtime dependency, and hardware calls stay in the bridge.

## Requirements

- Python 3.10 or newer, with `venv` available.
- Node.js and npm, for the browser workspace.
- Chromium, for the viewer windows. The viewer needs WebGL 2.
- A clone of `sawyer-control`, which this project installs from source.
- Docker, only if you also run the robot bridge on this machine.

## Install

Clone both repositories side by side. The launcher looks for `sawyer-control`
as a sibling directory, so this layout needs no configuration:

```bash
git clone git@github.com:sawyer-lab/sawyer-control.git
git clone git@github.com:sawyer-lab/sawyer-operations.git
cd sawyer-operations
```

For any other layout, point `SAWYER_CONTROL_DIR` at your clone:

```bash
export SAWYER_CONTROL_DIR=/path/to/sawyer-control
```

There is nothing else to install by hand. The launcher creates `.venv`,
installs both packages in editable mode, installs the web dependencies and
builds the browser application on first run. Later starts reuse all of it.

## Run

Start the robot bridge first, from your `sawyer-control` clone:

```bash
./sawyer-control up
```

That step needs Docker and a connected robot; see that project's README. Then
start the workspace from this one:

```bash
./sawyer-operations
```

It serves <http://127.0.0.1:8001> and opens it in Chromium. Drag to orbit,
scroll to zoom, right-drag to pan. Move the arm with your normal robot
controls: measured joint positions update the model at a requested 30 Hz. The
view buttons only move the browser camera; they command no motion.

Stop the workspace with Ctrl-C. That does not send any robot command.

**The bridge is optional for everything except live state and motion.** The
workspace starts, loads trajectories, previews them and imports spreadsheets
with the robot off. Nothing on page load, reconnection or page close enables
the robot, initializes the tool or commands motion.

Useful environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `SAWYER_CONTROL_DIR` | `../sawyer-control` | Where to install the control package from |
| `SAWYER_ADDRESS` | `127.0.0.1:50051` | The gRPC bridge to connect to |
| `SAWYER_OPERATIONS_DATA` | `~/.local/share/sawyer-operations` | Where trajectories and recordings are stored |

To reopen the browser without restarting the server, run `bash open-workspace`.
For the minimal trajectory-preview window, run `bash open-preview`.

## Use it from Python

Scripts use one synchronous `Robot` object, which connects to the local bridge:

```python
from sawyer_operations import Robot

with Robot.connect() as robot:
    trajectory = robot.load_trajectory('examples/preview.json')
    robot.show_preview(trajectory)
    recording = robot.start_recording('trial')
    result = robot.stream(trajectory).wait()
    recording.stop()
    print(result['phase'], result['reason'])
```

Streaming is refused unless the arm already sits at the first sample, and stops
if tracking diverges. `robot.stop()` is a separate, explicit robot-wide Stop.

Try the interactive demo, which reads the current pose, generates a small
motion, previews it and waits for you to accept, repeat or quit:

```bash
.venv/bin/python examples/demo_nearby_trajectory.py
```

## Import trajectories from a spreadsheet

A joint table produced elsewhere — a colleague's `t, q0..q6, dq0..dq6` sheet,
for example — becomes a canonical trajectory with:

```bash
.venv/bin/python -m sawyer_operations import motion.xlsx -o motion.json
```

It asks for the control mode, the units of the angle columns, and one column
per joint, suggesting matches by name. Sampling is assumed uniform at 100 Hz
and any time column is ignored. Nothing is derived, resampled or repaired, and
positions outside the arm's joint limits are refused. Reading `.xlsx` needs the
`xlsx` extra; CSV needs nothing. `python -m sawyer_operations export` writes a
flat table back out. The full description is in the operations guide below.

## Documentation

- [docs/OPERATIONS.md](docs/OPERATIONS.md): Python API, trajectory format,
  spreadsheet import, recording format, HTTP interface and examples.
- [docs/MOTION_EXECUTION.md](docs/MOTION_EXECUTION.md): motion-execution design.
- [docs/RELEASE_NOTES.md](docs/RELEASE_NOTES.md): what this release contains and
  which checks were run against it.

## Develop

The Python tests need `pytest`, which the launcher does not install:

```bash
.venv/bin/python -m pip install pytest
.venv/bin/python -m pytest tests -q
npm --prefix web run build
node --test web/src/telemetry.test.js web/src/timeline.test.js
```

Components:

- `sawyer_operations/server.py`: local HTTP/WebSocket service over the gRPC
  client generated by `sawyer-control`. One upstream arm stream is shared
  across browser tabs, keeping the robot endpoint out of browser timing loops.
- `sawyer_operations/executor.py`: timed, cancellable joint command streaming.
- `sawyer_operations/interop.py`: spreadsheet import and export.
- `web/src/viewer.js`: Three.js GLB view driven by the model's named joint
  hierarchy and `joint_axis_gltf` metadata.
- `web/src/main.jsx`: React panel, connection state and telemetry analysis.

The self-contained GLB in `web/public/models/sawyer.glb` is exported from the
separate `sawyer-model` workbench. After revising the model, copy the export
over that file and rebuild the web application.

## Current scope

Head pan, button illumination, head and wrist lights and the on-arm screen are
static model details. Model fingers follow the reported binary grip signal, not
a measured finger displacement. Gripper acknowledgement from the bridge does not
prove physical finger motion. The UI retains the last arm pose and marks the
connection lost on stream loss.

Physical gripper operation and hardware execution of imported trajectories are
unverified. The control bridge is maintained separately in `sawyer-control`.
