import sys
from pathlib import Path

import pytest
from sawyer_control.types import ControlMode
from sawyer_operations import COMMAND_RATE_HZ
from sawyer_operations.interop import POSITION_LIMITS_RAD

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'examples'))
from demo_replay_trajectory import approach_trajectory  # noqa: E402

START = (0.,) * 7
TARGET = (0., -1.18, 0., 2.18, 0., .57, 3.14)   # the first sample of the replay table


def test_approach_starts_where_the_arm_is_and_ends_at_rest():
    approach = approach_trajectory(START, TARGET, ControlMode.TRAJECTORY, .2)
    assert approach.rate_hz == COMMAND_RATE_HZ
    assert approach.samples[0].position.values == START
    assert approach.samples[-1].position.values == TARGET
    for end in (approach.samples[0], approach.samples[-1]):
        assert set(end.velocity.values) == {0} and set(end.acceleration.values) == {0}


def test_approach_respects_the_requested_speed_and_the_joint_limits():
    approach = approach_trajectory(START, TARGET, ControlMode.TRAJECTORY, .2)
    peak = max(max(abs(value) for value in sample.velocity.values) for sample in approach.samples)
    assert peak == pytest.approx(.2, rel=1e-3)
    slower = approach_trajectory(START, TARGET, ControlMode.TRAJECTORY, .1)
    assert slower.span_s == pytest.approx(approach.span_s * 2, rel=1e-2)
    for joint, (low, high) in enumerate(POSITION_LIMITS_RAD):
        values = [sample.position.values[joint] for sample in approach.samples]
        assert low <= min(values) and max(values) <= high


def test_approach_is_skipped_when_there_is_nothing_to_move():
    assert approach_trajectory(TARGET, TARGET, ControlMode.TRAJECTORY, .2) is None
    position = approach_trajectory(START, TARGET, ControlMode.POSITION, .2)
    assert position.mode is ControlMode.POSITION
    assert all(sample.velocity is None for sample in position.samples)
