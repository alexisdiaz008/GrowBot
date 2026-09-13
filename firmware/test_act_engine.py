"""Hardware-free ActEngine + pose-permit tests.

Run: python3 firmware/test_act_engine.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from act_engine import ActEngine, subset_steps_for_channels
from channels import (
    ARM_CHANNEL_IDS,
    CHANNEL_LEFT_ARM,
    CHANNEL_LEFT_LEG,
    CHANNEL_RIGHT_ARM,
    CHANNEL_RIGHT_LEG,
    ENQUEUE_MODE_APPEND,
    ERROR_QUEUE_FULL,
    KEYFRAME_MILLISECONDS_KEY,
    LEG_CHANNEL_IDS,
    SERVO_NEUTRAL_DEGREES,
    permit_pose,
    permit_poses,
)


class Clock:
    def __init__(self):
        self.now_milliseconds = 0

    def ticks_ms(self):
        return self.now_milliseconds

    def ticks_diff(self, later, earlier):
        return later - earlier

    def advance(self, milliseconds):
        self.now_milliseconds += milliseconds


def make_engine(channels=LEG_CHANNEL_IDS, hold_milliseconds=300):
    clock = Clock()
    writes = []
    releases = []

    def write_pose(pose):
        writes.append((clock.now_milliseconds, dict(pose)))

    def release():
        releases.append(clock.now_milliseconds)

    engine = ActEngine(
        write_pose, release, clock.ticks_ms, clock.ticks_diff,
        channels=channels, hold_milliseconds=hold_milliseconds,
    )
    return engine, clock, writes, releases


def tick_for(engine, clock, milliseconds, step_milliseconds=20):
    end = clock.now_milliseconds + milliseconds
    while clock.now_milliseconds < end:
        engine.tick()
        clock.advance(step_milliseconds)
    engine.tick()


def assert_eq(actual, expected, message=""):
    if actual != expected:
        raise AssertionError("%s: %r != %r" % (message, actual, expected))


def test_two_leg_wiggle_duration():
    engine, clock, writes, releases = make_engine()
    succeeded, queued = engine.enqueue([
        {CHANNEL_LEFT_LEG: 120, CHANNEL_RIGHT_LEG: 60, KEYFRAME_MILLISECONDS_KEY: 400},
        {CHANNEL_LEFT_LEG: 60, CHANNEL_RIGHT_LEG: 120, KEYFRAME_MILLISECONDS_KEY: 400},
        {CHANNEL_LEFT_LEG: SERVO_NEUTRAL_DEGREES, CHANNEL_RIGHT_LEG: SERVO_NEUTRAL_DEGREES,
         KEYFRAME_MILLISECONDS_KEY: 300},
    ])
    assert_eq(succeeded, True)
    assert_eq(queued, 1100)
    tick_for(engine, clock, 1100)
    assert_eq(writes[0][1], {CHANNEL_LEFT_LEG: 120, CHANNEL_RIGHT_LEG: 60})
    last = writes[-1][1]
    assert_eq(last, {CHANNEL_LEFT_LEG: SERVO_NEUTRAL_DEGREES, CHANNEL_RIGHT_LEG: SERVO_NEUTRAL_DEGREES})
    tick_for(engine, clock, 300)
    assert_eq(len(releases), 1)
    assert_eq(engine.active, False)


def test_omit_holds_channel():
    engine, clock, writes, _releases = make_engine()
    engine.enqueue([{CHANNEL_LEFT_LEG: 50, CHANNEL_RIGHT_LEG: 130, KEYFRAME_MILLISECONDS_KEY: 0}])
    tick_for(engine, clock, 20)
    engine.enqueue([{CHANNEL_LEFT_LEG: 80, KEYFRAME_MILLISECONDS_KEY: 0}], mode=ENQUEUE_MODE_APPEND)
    tick_for(engine, clock, 20)
    assert_eq(writes[-1][1], {CHANNEL_LEFT_LEG: 80, CHANNEL_RIGHT_LEG: 130})


def test_two_instances_do_not_clear_each_other():
    clock = Clock()
    leg_writes, arm_writes, leg_releases, arm_releases = [], [], [], []
    legs = ActEngine(
        lambda pose: leg_writes.append(dict(pose)),
        lambda: leg_releases.append(clock.now_milliseconds),
        clock.ticks_ms, clock.ticks_diff, channels=LEG_CHANNEL_IDS, hold_milliseconds=300,
    )
    arms = ActEngine(
        lambda pose: arm_writes.append(dict(pose)),
        lambda: arm_releases.append(clock.now_milliseconds),
        clock.ticks_ms, clock.ticks_diff, channels=ARM_CHANNEL_IDS, hold_milliseconds=300,
    )
    succeeded, _queued = arms.enqueue([
        {CHANNEL_LEFT_ARM: 40, CHANNEL_RIGHT_ARM: 140, KEYFRAME_MILLISECONDS_KEY: 400},
    ])
    assert_eq(succeeded, True)
    legs.clear()
    for _index in range(10):
        legs.tick()
        arms.tick()
        clock.advance(20)
    assert_eq(arms.active, True)
    assert_eq(len(arm_writes) > 0, True)
    assert_eq(len(leg_writes), 0)


def test_stop_both():
    clock = Clock()
    releases = []
    legs = ActEngine(
        lambda pose: None, lambda: releases.append("legs"),
        clock.ticks_ms, clock.ticks_diff, channels=LEG_CHANNEL_IDS,
    )
    arms = ActEngine(
        lambda pose: None, lambda: releases.append("arms"),
        clock.ticks_ms, clock.ticks_diff, channels=ARM_CHANNEL_IDS,
    )
    legs.enqueue([{CHANNEL_LEFT_LEG: 70, CHANNEL_RIGHT_LEG: 110, KEYFRAME_MILLISECONDS_KEY: 800}])
    arms.enqueue([{CHANNEL_LEFT_ARM: 60, CHANNEL_RIGHT_ARM: 120, KEYFRAME_MILLISECONDS_KEY: 800}])
    legs.clear()
    arms.clear()
    legs.release()
    arms.release()
    assert_eq(legs.active, False)
    assert_eq(arms.active, False)
    assert_eq(sorted(releases), ["arms", "legs"])


def test_queue_full():
    engine, _clock, _writes, _releases = make_engine()
    succeeded, error = engine.enqueue(
        [{CHANNEL_LEFT_LEG: SERVO_NEUTRAL_DEGREES, CHANNEL_RIGHT_LEG: SERVO_NEUTRAL_DEGREES,
          KEYFRAME_MILLISECONDS_KEY: 3000}] * 6
    )
    assert_eq(succeeded, False)
    assert_eq(error, ERROR_QUEUE_FULL)


def test_ignores_other_engine_keys():
    engine, clock, writes, _releases = make_engine(channels=ARM_CHANNEL_IDS)
    succeeded, _queued = engine.enqueue([{
        CHANNEL_LEFT_LEG: 10, CHANNEL_RIGHT_LEG: 20,
        CHANNEL_LEFT_ARM: 30, CHANNEL_RIGHT_ARM: 40,
        KEYFRAME_MILLISECONDS_KEY: 0,
    }])
    assert_eq(succeeded, True)
    tick_for(engine, clock, 20)
    assert_eq(writes[-1][1], {CHANNEL_LEFT_ARM: 30, CHANNEL_RIGHT_ARM: 40})


def test_subset_steps_for_channels():
    steps = [{
        CHANNEL_LEFT_LEG: 10, CHANNEL_RIGHT_LEG: 20,
        CHANNEL_LEFT_ARM: 30, CHANNEL_RIGHT_ARM: 40,
        KEYFRAME_MILLISECONDS_KEY: 100,
    }]
    assert_eq(
        subset_steps_for_channels(steps, LEG_CHANNEL_IDS),
        [{CHANNEL_LEFT_LEG: 10, CHANNEL_RIGHT_LEG: 20, KEYFRAME_MILLISECONDS_KEY: 100}],
    )
    assert_eq(
        subset_steps_for_channels(steps, ARM_CHANNEL_IDS),
        [{CHANNEL_LEFT_ARM: 30, CHANNEL_RIGHT_ARM: 40, KEYFRAME_MILLISECONDS_KEY: 100}],
    )
    assert_eq(subset_steps_for_channels("soup", LEG_CHANNEL_IDS), [])
    assert_eq(subset_steps_for_channels(None, LEG_CHANNEL_IDS), [])


def test_permit_pose_keeps_channel_ids_and_strips_unknown():
    assert_eq(permit_pose({
        CHANNEL_LEFT_LEG: 70, "l": 1, "ms": 400, KEYFRAME_MILLISECONDS_KEY: 400,
    }), {CHANNEL_LEFT_LEG: 70, KEYFRAME_MILLISECONDS_KEY: 400})
    assert_eq(permit_pose({KEYFRAME_MILLISECONDS_KEY: 100}), None)
    assert_eq(permit_pose("soup"), None)
    assert_eq(permit_poses([{CHANNEL_RIGHT_ARM: 130}, {KEYFRAME_MILLISECONDS_KEY: 10}]),
              [{CHANNEL_RIGHT_ARM: 130}])
    assert_eq(permit_poses("soup"), [])


if __name__ == "__main__":
    tests = [value for name, value in list(globals().items()) if name.startswith("test_")]
    for test_fn in tests:
        test_fn()
        print("ok", test_fn.__name__)
    print("%d passed" % len(tests))
