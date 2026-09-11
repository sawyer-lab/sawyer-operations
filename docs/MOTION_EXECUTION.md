# Motion execution design

Recorded 2026-09-11.

`sawyer-control` is a direct Intera/ROS adapter. It accepts one immediate joint
command at a time and exposes direct state and lifecycle calls. It does not own
trajectory timing, batching, operation IDs, completion tracking, or cancellation
state.

Trajectory files remain operations data. `Robot.stream()` owns one scheduler,
active-run state and recording annotations. It publishes one immediate joint
command per planned sample through the control layer.

Before publishing its first sample, the stream requires a fresh robot state and
rejects a trajectory whose first position differs by more than 0.05 rad at any
joint. While running, it stops publishing on cancellation, state older than
250 ms, scheduler lateness beyond 50 ms, or tracking error above 0.15 rad for
three distinct robot-state frames. It never catches up by publishing delayed
samples rapidly. These conditions end publication only; they do not issue the
robot-wide Stop RPC.

Completion means every sample was acknowledged by the bridge. The final measured
robot state is recorded separately and is not inferred from that acknowledgement.
