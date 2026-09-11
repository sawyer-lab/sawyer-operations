# Operations library

Implemented 2026-09-10. This layer uses the existing Sawyer control protocol.
It has no ROS or MuJoCo runtime dependency. Hardware calls stay in the bridge.

## Shared service and Python client

Run the existing launcher:

```bash
/home/fausto/Projects/sawyer-operations/sawyer-operations
```

It serves the workspace at <http://127.0.0.1:8001>. The robot bridge can be off
while loading and previewing trajectories. The launcher does not start it.

```python
from sawyer_operations import Workspace

workspace = Workspace('http://127.0.0.1:8001')
item = workspace.load('/home/fausto/Projects/sawyer-operations/examples/preview.json')
workspace.preview(item['id'])
```

Every connected browser sees that selection. Loading and selecting never execute
commands. The blue translucent robot shows planned positions; the solid model
continues to show the bridge's measured pose. Play/pause and scrubbing are local
to each browser. Preview uses the supplied position samples without resampling.
The included example illustrates the file format and visual preview, and is not
a hardware-validated motion program.

Record telemetry explicitly while inspecting a planned trajectory:

```python
recording = workspace.start_recording('Inspection trace')
workspace.stop_recording()
workspace.download_recording(recording['id'], '/tmp/sawyer-recording.jsonl')
```

`workspace.stop()` sends the control bridge's direct Stop RPC. It is not a
preview pause or a promise of position hold. Explicit enable, disable and reset
are available through `workspace.command()`. Gripper actions are `open` and
`close`.

## Direct Python use

The CLI/script API uses one synchronous `Robot` object. It always connects to
the local bridge; scripts do not configure a bridge address.

```python
from sawyer_operations import Robot

with Robot.connect() as robot:
    trajectory = robot.load_trajectory(
        '/home/fausto/Projects/sawyer-operations/examples/preview.json'
    )
    robot.force_torque.enable()
    recording = robot.start_recording('trial')
    run = robot.stream(trajectory)
    result = run.wait()
    recording.stop()
    print(result['phase'], result['reason'])
```

`run.cancel()` stops publishing future samples. `robot.stop()` is a distinct,
explicit request for the robot-wide Stop RPC. Recordings automatically contain
robot state, gripper state, stream command scheduling and acknowledgements.
After `robot.force_torque.enable()`, force/torque samples are automatically
included in any active recording.

For an interactive nearby-motion demo, run:

```bash
/home/fausto/miniconda3/envs/tossing/bin/python /home/fausto/Projects/sawyer-operations/examples/demo_nearby_trajectory.py
```

It starts the previewer when needed, reads the current pose, generates a small
smooth trajectory, updates the previewer, and waits for accept, repeat or quit.
Acceptance starts a recording and streams the samples; quitting or repeating
publishes nothing.

Recordings themselves always live in the service's storage directory under
generated IDs. On acceptance the demo additionally copies that run to a stable
pair of paths:

```
runs/<run-name>.jsonl   the recording
runs/<run-name>.json    the trajectory that was streamed
```

`--run-name` sets that base name and defaults to `nearby_trajectory`, so
running the demo repeatedly replaces the previous copy rather than accumulating
files. `runs/` is untracked. The service's own copy is untouched and still
carries every past run.

To read the saved run back:

```bash
/home/fausto/miniconda3/envs/tossing/bin/python /home/fausto/Projects/sawyer-operations/examples/demo_read_recording.py
```

It walks the JSONL once with `read_recording`, prints the header, duration and
row, observation, command and event counts, summarizes the saved trajectory,
and opens the same recording in the browser analysis view. It commands nothing
and needs no robot. Use `--no-viewer` for the summary alone. If the service's
storage no longer holds that recording, the summary still prints and the
script says the analysis view cannot open it.

## Trajectory format

Canonical JSON has `schema_version: 3`, mode, rate_hz, joint_names, units and
samples. See the complete example file above. Joint ordering is exactly
right_j0 through right_j6. Modes map directly to the existing control modes:

| Mode | Required fields in every sample |
|---|---|
| position | position |
| velocity | velocity |
| torque | effort |
| trajectory | position, velocity, acceleration |

Vectors have seven finite numbers. Units are radians, rad/s, Nm and rad/s^2.

**The rate defaults to the robot's 100 Hz command rate and is bounded to
1-100 Hz.** `rate_hz` is the last argument of `Trajectory` and may be omitted;
anything outside that range, including a non-finite value, is rejected on
construction, so an out-of-range rate cannot reach the executor. It is optional
in the JSON too and defaults to 100 when absent. Duration is
sample_count/rate_hz.

A trajectory carries no name. It is `Trajectory(mode, samples)`, and the
ID it is stored under identifies it. The mode is a `ControlMode` member, which
the package re-exports:

```python
from sawyer_operations import ControlMode, Trajectory

trajectory = Trajectory(ControlMode.TRAJECTORY, samples)
``` Trajectories the service cannot read are
skipped at startup and listed, rather than stopping it.

No degree conversion, joint reordering, interpolation or timing repair occurs. Position data is required for geometric preview;
velocity/torque data can be stored without position samples, but has no
geometric preview.

CSV columns use `position.right_j0` through `position.right_j6`, and the same
pattern for velocity, effort and acceleration. Supply the mode explicitly in
`Trajectory.from_csv(text, mode=..., rate_hz=...)` or the UI import settings,
which default to 100 Hz. The
format does not accept arbitrary time columns. The last sample's time is
(sample_count-1)/100 seconds.

## Importing tables from other tools

`sawyer-traj` maps a colleague's joint table onto the canonical format. It maps
columns and converts units; it derives nothing. Rows are consumed in order at
100 Hz unless `--rate` says otherwise, so a time column is listed but ignored.
A table at another rate needs that rate passed; nothing is inferred from `t`.

```bash
python -m sawyer_operations import motion.xlsx -o motion.json
```

It asks for the control mode, then the units of the angle columns, then one
column per joint. It never asks for a rate; pass `--rate` for a table that is
not at 100 Hz. Answer with a column number or name; Enter accepts the
suggestion. Aliases cover `q0`/`dq0`/`ddq0`/`tau0` spellings, `J_1` style
one-based headers, headerless files (answer with indices), and semicolon files
with comma decimals. Modes ask for the columns they require: position and
velocity need seven, `trajectory` needs twenty-one. Acceleration is never
computed from velocity, and velocity is never computed from position; a
trajectory-mode file must already contain all three.

Units are asked, never inferred, because the same numbers are valid in both.
Imported positions are checked against the published `right_j0`-`right_j6`
ranges and the import is refused outside them, naming the joint and row. That
check also catches degrees declared as radians, which exceed every limit at once.

```bash
# same layout again, no prompts
python -m sawyer_operations import second.xlsx -o second.json --profile colleague.json
# alias-matched columns, no prompts; also the default when stdin is not a terminal
python -m sawyer_operations import motion.csv -o motion.json --mode position --units deg --auto
# flat t, q0..q6 table to send back
python -m sawyer_operations export motion.json -o motion.csv --units deg
```

Add `--save-profile colleague.json` to record the answers for reuse. Reading and
writing `.xlsx` needs `openpyxl`; the `.csv` path has no extra dependency.

For scripts, the same mapping is available without prompts:

```python
from sawyer_operations import Robot, import_table

trajectory = import_table('motion.xlsx', mode='position', units='deg')
with Robot.connect() as robot:
    loaded = robot.load_trajectory(trajectory)
    robot.show_preview(loaded)
```

Nothing about import commands motion. The imported trajectory still faces the
executor's start-pose check before streaming, and no approach motion to the
first sample is generated.

## Recordings and shared state

Set `SAWYER_OPERATIONS_DATA` to choose the service's storage directory. By default
it uses `/home/fausto/.local/share/sawyer-operations` for this user. It stores
trajectory JSON and recording JSONL under generated IDs. Files are created
exclusively; submitted names are labels, not paths.

Recordings contain a metadata header, ordered observations, command events and a
closing record. Every row has a sequence number plus wall-clock and monotonic
nanoseconds. Observations additionally retain a source timestamp when supplied
by the bridge. This makes scheduling, state and enabled-sensor records
reconstructible on one timeline.

```python
from sawyer_operations import read_recording

for row in read_recording('/tmp/sawyer-recording.jsonl'):
    print(row['sequence'], row['type'])
```

Closing/refreshing a browser does not end server recordings. Server shutdown
finalizes its recording and disconnects; it sends no robot stop. Loaded
trajectories and saved recordings survive restart. Selection and event history
are session state and are not resumed after restart.
The bounded event history contains the latest 200 workspace events with revisions;
full command events during recording are stored on disk.

## HTTP interface

Interactive API documentation is at <http://127.0.0.1:8001/docs>.

- GET /api/workspace: catalog, selection, recording and events.
- POST /api/trajectories: canonical trajectory JSON.
- POST /api/trajectories/csv: text, mode and an optional rate_hz.
- GET /api/trajectories/{id}: full trajectory.
- POST /api/preview: `{ "id": "..." }`, or null to clear.
- POST /api/robot/command: `{ "action": "stop" }`, enable, disable, reset, open or close.
- POST /api/recordings: recording name; enabled sources are recorded automatically.
- POST /api/recordings/stop: finalize the current recording.
- GET /api/recordings and GET /api/recordings/{id}/download.
- WS /api/live: telemetry plus workspace state on revisions, including initial state.

The existing /api/health and /api/gripper endpoints continue to serve the UI.

## Verification and current scope

Offline tests cover malformed trajectories, CSV parsing, passive preview,
persistence, recording timeline records, initial-pose rejection, cancellation,
tracking divergence and the direct `Robot` facade.

```bash
cd /home/fausto/Projects/sawyer-operations
PYTHONPATH=/home/fausto/Projects/sawyer-operations /home/fausto/miniconda3/envs/tossing/bin/python -m pytest tests -q
cd /home/fausto/Projects/sawyer-operations/web
npm run build
```

The light analysis editor provides synchronized recorded robot replay, measured
and sent-command traces, measured-minus-sent error, pointer-centered zoom, pan,
range selection, an overview navigator, A/B cursors and selection statistics.
It includes individual channel selection, collapsible groups, resizable panels,
command timestamps, event markers and CSV export. Previous/Next can step through
robot samples or sent commands. The nearby-motion demo enables force/torque in
Python, closes its owned preview window after execution and opens analysis.
Use `--browser chromium` to explicitly select Chromium. See the README for the
complete analysis workflow and timestamp interpretation.

The motion-execution design is recorded separately in
[`MOTION_EXECUTION.md`](MOTION_EXECUTION.md). Physical button bindings require
the control layer to expose input events and are not implemented here.
