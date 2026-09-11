# Initial source release — 2026-09-11

This initial commit collects the operations library, script demos, browser
preview and telemetry analysis, plus Claude's trajectory table helper.

## Operations and demos

- Direct `Robot.connect()` script API, trajectory loading and cancellable streams.
- Initial-pose, state freshness, tracking divergence and scheduling checks.
  Cancellation stops future publication; explicit robot Stop remains separate.
- Automatic recording of robot telemetry and enabled force/torque observations,
  with command scheduling, attempts and acknowledgements in version 2 JSONL.
- Nearby interpolated motion demo with preview, terminal acceptance, recording,
  execution and post-run analysis. The script enables force/torque directly.
- Explicit browser selection and isolated browser profiles for owned windows.

## Analysis

Light editor with seven-joint q/dq/tau and six-axis sensor tracks, measured/sent/
error toggles, pointer-centered zoom, panning, range selection, overview handles,
A/B comparisons, sample/command stepping, timestamps, events, CSV export and
synchronized 3D replay. Panels resize and channels can be hidden or collapsed.
Error uses the last sent value at each measured sample without delay correction.
ACK represents bridge acknowledgement, not physical execution. Visual browser
verification and hardware execution were not performed for this release.

## Trajectory table helper

Claude's `sawyer-traj` entry point and `python -m sawyer_operations` support
CSV/XLSX import/export, explicit units and column mapping, reusable mapping
profiles, alias suggestions and position-limit validation. Uniform sampling
defaults to 100 Hz; time columns are ignored and `--rate` overrides the rate.
No derivatives or resampling are inferred. Install the `xlsx` extra for Excel.
The helper implementation and its regression tests are included unchanged.

## Validation

Release checks passed: 21 Python tests (including the table helper), six
JavaScript telemetry/timeline tests, production web build and helper CLI help.

From the project root, run the Python tests using an environment with
`sawyer-control`, `sawyer-operations` and pytest installed:

```bash
python -m pytest tests -q
npm --prefix web run build
node --test web/src/telemetry.test.js web/src/timeline.test.js
python -m sawyer_operations --help
```

Generated web assets, Python environments, caches, logs and local recordings
are excluded from the source commit. The model GLB is included for the viewers.
