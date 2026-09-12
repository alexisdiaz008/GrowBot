"""Hardware-free BodyMotion tests. Run: python3 firmware/test_motion.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from channels import (
    CHANNEL_LEFT_ARM,
    CHANNEL_LEFT_LEG,
    CHANNEL_PORT,
    CHANNEL_RIGHT_ARM,
    CHANNEL_RIGHT_LEG,
    ENQUEUE_MODE_REPLACE,
    ERROR_NO_VALID_KEYFRAMES,
    ERROR_QUEUE_FULL,
    KEYFRAME_MILLISECONDS_KEY,
    PORT_LEFT_ARM,
    PORT_LEFT_LEG,
    PORT_RIGHT_ARM,
    PORT_RIGHT_LEG,
    ROUTINE_WIGGLE,
    SERVO_NEUTRAL_DEGREES,
    WIRE_LEFT_ARM,
    WIRE_LEFT_LEG,
    WIRE_RIGHT_ARM,
    WIRE_RIGHT_LEG,
)
from motion import BodyMotion, speed_steps_to_wire_keyframes


class Clock:
    def __init__(self):
        self.now_milliseconds = 0

    def ticks_ms(self):
        return self.now_milliseconds

    def ticks_diff(self, later, earlier):
        return later - earlier

    def advance(self, milliseconds):
        self.now_milliseconds += milliseconds


class FakeBoard:
    def __init__(self):
        self.writes = []
        self.releases = []

    def servoWrite(self, port, degrees):
        self.writes.append((port, degrees))

    def release(self, port):
        self.releases.append(port)


def make_motion():
    clock = Clock()
    board = FakeBoard()
    slept = []
    motion = BodyMotion(
        board, CHANNEL_PORT, clock.ticks_ms, clock.ticks_diff,
        sleep_milliseconds=lambda milliseconds: slept.append(milliseconds),
    )
    return motion, clock, board, slept


def assert_eq(actual, expected, message=""):
    if actual != expected:
        raise AssertionError("%s: %r != %r" % (message, actual, expected))


def test_arms_only_act_does_not_clear_legs_engine():
    motion, clock, board, _slept = make_motion()
    succeeded, queued, used_legs = motion.enqueue_wire_steps(
        [{WIRE_LEFT_LEG: 70, WIRE_RIGHT_LEG: 110, KEYFRAME_MILLISECONDS_KEY: 800}],
        ENQUEUE_MODE_REPLACE,
    )
    assert_eq(succeeded, True)
    assert_eq(used_legs, True)
    assert_eq(motion.legs_engine.active, True)
    succeeded, _queued, used_legs = motion.enqueue_wire_steps(
        [{WIRE_LEFT_ARM: 50, WIRE_RIGHT_ARM: 130, KEYFRAME_MILLISECONDS_KEY: 400}],
        ENQUEUE_MODE_REPLACE,
    )
    assert_eq(succeeded, True)
    assert_eq(used_legs, False)
    assert_eq(motion.legs_engine.active, True)
    assert_eq(motion.arms_engine.active, True)
    motion.tick()
    clock.advance(20)
    motion.tick()
    written_ports = [port for port, _degrees in board.writes]
    assert_eq(PORT_LEFT_LEG in written_ports, True)
    assert_eq(PORT_LEFT_ARM in written_ports, True)


def test_walk_pose_does_not_clear_arms():
    motion, _clock, board, _slept = make_motion()
    motion.enqueue_wire_steps(
        [{WIRE_LEFT_ARM: 40, WIRE_RIGHT_ARM: 140, KEYFRAME_MILLISECONDS_KEY: 400}],
    )
    assert_eq(motion.arms_engine.active, True)
    touched_legs, touched_arms = motion.apply_absolute_pose(
        left_leg=70, right_leg=110,
    )
    assert_eq(touched_legs, True)
    assert_eq(touched_arms, False)
    assert_eq(motion.arms_engine.active, True)
    assert_eq(motion.legs_engine.active, False)


def test_stop_clears_both_and_releases_mapped_ports():
    motion, _clock, board, _slept = make_motion()
    motion.enqueue_wire_steps([
        {WIRE_LEFT_LEG: 70, WIRE_RIGHT_LEG: 110, KEYFRAME_MILLISECONDS_KEY: 800},
        {WIRE_LEFT_ARM: 60, WIRE_RIGHT_ARM: 120, KEYFRAME_MILLISECONDS_KEY: 800},
    ])
    motion.clear_both()
    motion.release_all_mapped_ports()
    assert_eq(motion.legs_engine.active, False)
    assert_eq(motion.arms_engine.active, False)
    assert_eq(sorted(board.releases), sorted([
        PORT_LEFT_LEG, PORT_RIGHT_LEG, PORT_LEFT_ARM, PORT_RIGHT_ARM,
    ]))


def test_queue_full_is_the_protocol_string():
    motion, _clock, _board, _slept = make_motion()
    oversized = [{WIRE_LEFT_LEG: SERVO_NEUTRAL_DEGREES, WIRE_RIGHT_LEG: SERVO_NEUTRAL_DEGREES,
                  KEYFRAME_MILLISECONDS_KEY: 3000}] * 6
    succeeded, error, used_legs = motion.enqueue_wire_steps(oversized)
    assert_eq(succeeded, False)
    assert_eq(error, ERROR_QUEUE_FULL)
    assert_eq(used_legs, True)


def test_malformed_plan_rejected():
    motion, _clock, _board, _slept = make_motion()
    succeeded, error, used_legs = motion.enqueue_wire_steps("soup")
    assert_eq(succeeded, False)
    assert_eq(error, ERROR_NO_VALID_KEYFRAMES)
    assert_eq(used_legs, False)


def test_wiggle_routine_queues_1900ms():
    motion, _clock, _board, _slept = make_motion()
    succeeded, queued, used_legs = motion.enqueue_routine(ROUTINE_WIGGLE)
    assert_eq(succeeded, True)
    assert_eq(queued, 1900)
    assert_eq(used_legs, True)


def test_unknown_routine():
    motion, _clock, _board, _slept = make_motion()
    succeeded, queued, used_legs = motion.enqueue_routine("not-a-dance")
    assert_eq(succeeded, False)
    assert_eq(queued, None)
    assert_eq(used_legs, False)


def test_legacy_speed_steps_map_to_lean_degrees():
    frames = speed_steps_to_wire_keyframes([
        {WIRE_LEFT_LEG: 1, WIRE_RIGHT_LEG: -1, KEYFRAME_MILLISECONDS_KEY: 400},
    ])
    assert_eq(frames, [{
        WIRE_LEFT_LEG: 55,
        WIRE_RIGHT_LEG: 125,
        KEYFRAME_MILLISECONDS_KEY: 400,
    }])


def test_stats_channels_are_wire_keys():
    motion, _clock, _board, _slept = make_motion()
    assert_eq(
        motion.loaded_wire_keys(),
        [WIRE_LEFT_LEG, WIRE_RIGHT_LEG, WIRE_LEFT_ARM, WIRE_RIGHT_ARM],
    )


def test_settle_then_release_sleeps_then_limps():
    motion, _clock, board, slept = make_motion()
    motion.settle_then_release_all()
    assert_eq(slept, [300])
    assert_eq(PORT_LEFT_LEG in [port for port, _degrees in board.writes], True)
    assert_eq(len(board.releases), 4)


if __name__ == "__main__":
    tests = [value for name, value in list(globals().items()) if name.startswith("test_")]
    for test_fn in tests:
        test_fn()
        print("ok", test_fn.__name__)
    print("%d passed" % len(tests))
