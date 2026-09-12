"""Hardware-free ActEngine tests. Run: python3 firmware/test_act_engine.py"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from act_engine import ActEngine

class Clock:
    def __init__(self):
        self.t = 0
    def ticks_ms(self):
        return self.t
    def ticks_diff(self, a, b):
        return a - b
    def advance(self, ms):
        self.t += ms


def make(channels=("l", "r"), hold_ms=300):
    clock = Clock()
    writes = []
    releases = []
    def write_pose(pose):
        writes.append((clock.t, dict(pose)))
    def release():
        releases.append(clock.t)
    eng = ActEngine(write_pose, release, clock.ticks_ms, clock.ticks_diff,
                    channels=channels, hold_ms=hold_ms)
    return eng, clock, writes, releases


def tick_ms(eng, clock, ms, step=20):
    end = clock.t + ms
    while clock.t < end:
        eng.tick()
        clock.advance(step)
    eng.tick()


def assert_eq(a, b, msg=""):
    if a != b:
        raise AssertionError("%s: %r != %r" % (msg, a, b))


def test_two_leg_wiggle_duration():
    eng, clock, writes, releases = make()
    ok, queued = eng.enqueue([
        {"l": 120, "r": 60, "ms": 400},
        {"l": 60, "r": 120, "ms": 400},
        {"l": 90, "r": 90, "ms": 300},
    ])
    assert_eq(ok, True)
    assert_eq(queued, 1100)
    tick_ms(eng, clock, 1100)
    assert_eq(writes[0][1], {"l": 120, "r": 60})
    last = writes[-1][1]
    assert_eq(last, {"l": 90, "r": 90})
    tick_ms(eng, clock, 300)
    assert_eq(len(releases), 1)
    assert_eq(eng.active, False)


def test_omit_holds_channel():
    eng, clock, writes, _ = make()
    eng.enqueue([{"l": 50, "r": 130, "ms": 0}])
    tick_ms(eng, clock, 20)
    eng.enqueue([{"l": 80, "ms": 0}], mode="append")
    tick_ms(eng, clock, 20)
    assert_eq(writes[-1][1], {"l": 80, "r": 130})


def test_two_instances_do_not_clear_each_other():
    clock = Clock()
    leg_w, arm_w, leg_rel, arm_rel = [], [], [], []
    legs = ActEngine(lambda p: leg_w.append(dict(p)), lambda: leg_rel.append(clock.t),
                     clock.ticks_ms, clock.ticks_diff, channels=("l", "r"), hold_ms=300)
    arms = ActEngine(lambda p: arm_w.append(dict(p)), lambda: arm_rel.append(clock.t),
                     clock.ticks_ms, clock.ticks_diff, channels=("al", "ar"), hold_ms=300)
    ok, _ = arms.enqueue([{"al": 40, "ar": 140, "ms": 400}])
    assert_eq(ok, True)
    # walk pose must not clear arms
    legs.clear()
    for _ in range(10):
        legs.tick(); arms.tick(); clock.advance(20)
    assert_eq(arms.active, True)
    assert_eq(len(arm_w) > 0, True)
    assert_eq(len(leg_w), 0)


def test_stop_both():
    clock = Clock()
    rel = []
    legs = ActEngine(lambda p: None, lambda: rel.append("l"),
                     clock.ticks_ms, clock.ticks_diff, channels=("l", "r"))
    arms = ActEngine(lambda p: None, lambda: rel.append("a"),
                     clock.ticks_ms, clock.ticks_diff, channels=("al", "ar"))
    legs.enqueue([{"l": 70, "r": 110, "ms": 800}])
    arms.enqueue([{"al": 60, "ar": 120, "ms": 800}])
    legs.clear(); arms.clear()
    legs.release(); arms.release()
    assert_eq(legs.active, False)
    assert_eq(arms.active, False)
    assert_eq(sorted(rel), ["a", "l"])


def test_queue_full():
    eng, clock, _, _ = make()
    ok, err = eng.enqueue([{"l": 90, "r": 90, "ms": 3000}] * 6)
    assert_eq(ok, False)
    assert_eq(err, "queue full")


def test_ignores_other_engine_keys():
    eng, clock, writes, _ = make(channels=("al", "ar"))
    ok, _ = eng.enqueue([{"l": 10, "r": 20, "al": 30, "ar": 40, "ms": 0}])
    assert_eq(ok, True)
    tick_ms(eng, clock, 20)
    assert_eq(writes[-1][1], {"al": 30, "ar": 40})


def test_subset_steps():
    from act_engine import subset_steps
    steps = [{"l": 10, "r": 20, "al": 30, "ar": 40, "ms": 100}]
    assert_eq(subset_steps(steps, ("l", "r")), [{"l": 10, "r": 20, "ms": 100}])
    assert_eq(subset_steps(steps, ("al", "ar")), [{"al": 30, "ar": 40, "ms": 100}])
    assert_eq(subset_steps("soup", ("l", "r")), [])
    assert_eq(subset_steps(None, ("l", "r")), [])


if __name__ == "__main__":
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for fn in tests:
        fn()
        print("ok", fn.__name__)
    print("%d passed" % len(tests))
