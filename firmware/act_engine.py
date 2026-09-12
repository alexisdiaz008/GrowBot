"""Keyframe motion engine for the robot body — hardware-free, Mac-testable.

This is the hobby-scale version of "action chunking" from modern robotics
(ACT, Zhao et al. 2023): the brain ships a short PLAN of poses, the body
executes it locally at ~50Hz with smooth glides, and the next chunk may
arrive while this one plays.

A keyframe is a sparse map of channel id → degrees plus milliseconds:
  - values are absolute servo degrees (90 = neutral stance)
  - milliseconds = how long the glide TO that pose takes (0 = snap). From a
    cold start (pose unknown) the first frame snaps into place, then holds
    out its milliseconds — a chunk always lasts sum(milliseconds), warm or cold
  - omit a channel to leave it at its current target
  - repeat the same pose to hold it (a musical rest)

Default channels are the two legs. A second instance with the arm channel
ids owns arms; the two engines must not clear each other.

Glides are eased with smoothstep (slow-in, slow-out). When the queue drains
the engine holds the last pose briefly, then releases the servos (limp).

No MicroPython imports here. The firmware injects the servo writer, the
release function, and the tick functions; the Mac test injects fakes.
Time follows time.ticks_ms semantics (ticks_ms / ticks_diff).
write_pose(pose_dict) receives every channel this engine owns as ints.
"""
from channels import (
    DEFAULT_STEP_MILLISECONDS,
    ENQUEUE_MODE_REPLACE,
    ERROR_NO_VALID_KEYFRAMES,
    ERROR_QUEUE_FULL,
    HOLD_AFTER_DRAIN_MILLISECONDS,
    KEYFRAME_MILLISECONDS_KEY,
    LEG_CHANNEL_IDS,
    MAX_QUEUE_MILLISECONDS,
    MAX_STEP_MILLISECONDS,
    SERVO_NEUTRAL_DEGREES,
    clamp_degrees,
    clamp_degrees_int,
)


def subset_steps_for_channels(steps, channel_ids):
    """Keep only this engine's channel ids from a plan (plus duration)."""
    out = []
    if not isinstance(steps, list):
        return out
    for step in steps:
        if not isinstance(step, dict):
            continue
        frame = {}
        for channel_id in channel_ids:
            if channel_id in step and step[channel_id] is not None:
                frame[channel_id] = step[channel_id]
        if not frame:
            continue
        if KEYFRAME_MILLISECONDS_KEY in step:
            frame[KEYFRAME_MILLISECONDS_KEY] = step[KEYFRAME_MILLISECONDS_KEY]
        out.append(frame)
    return out


class ActEngine:
    def __init__(self, write_pose, release, ticks_ms, ticks_diff,
                 channels=LEG_CHANNEL_IDS,
                 max_step_milliseconds=MAX_STEP_MILLISECONDS,
                 max_queue_milliseconds=MAX_QUEUE_MILLISECONDS,
                 hold_milliseconds=HOLD_AFTER_DRAIN_MILLISECONDS):
        self.write_pose = write_pose
        self.release = release
        self.ticks_ms = ticks_ms
        self.ticks_diff = ticks_diff
        self.channels = tuple(channels)
        self.max_step_milliseconds = max_step_milliseconds
        self.max_queue_milliseconds = max_queue_milliseconds
        self.hold_milliseconds = hold_milliseconds
        self.queue = []
        self.current_glide = None
        self.last_pose = None
        self.hold_started_at = None
        self.active = False

    def _extract_keyframe(self, step):
        pose = {}
        for channel_id in self.channels:
            if channel_id not in step or step[channel_id] is None:
                pose[channel_id] = None
                continue
            pose[channel_id] = clamp_degrees(float(step[channel_id]))
        if all(degrees is None for degrees in pose.values()):
            return None
        milliseconds = min(int(step.get(KEYFRAME_MILLISECONDS_KEY, DEFAULT_STEP_MILLISECONDS)),
                           self.max_step_milliseconds)
        return pose, max(0, milliseconds)

    def enqueue(self, steps, mode=ENQUEUE_MODE_REPLACE):
        """Validate + queue a chunk. Returns (ok, queued_milliseconds_or_error).

        replace: drop the queue AND the in-flight glide; the new chunk glides
        from wherever the channels are right now (smooth takeover).
        append: play after everything already queued (pipelining).
        """
        frames = []
        for step in steps:
            try:
                extracted = self._extract_keyframe(step)
            except (ValueError, TypeError, AttributeError):
                continue
            if extracted is None:
                continue
            frames.append(extracted)
        if not frames:
            return False, ERROR_NO_VALID_KEYFRAMES
        new_milliseconds = sum(frame[1] for frame in frames)
        if mode == ENQUEUE_MODE_REPLACE:
            self.queue = []
            self.current_glide = None
        if self.queued_milliseconds() + new_milliseconds > self.max_queue_milliseconds:
            return False, ERROR_QUEUE_FULL
        self.queue.extend(frames)
        self.hold_started_at = None
        self.active = True
        return True, self.queued_milliseconds()

    def queued_milliseconds(self):
        total = sum(frame[1] for frame in self.queue)
        if self.current_glide:
            remaining = self.current_glide[2] - self.ticks_diff(
                self.ticks_ms(), self.current_glide[3])
            total += max(0, remaining)
        return total

    def clear(self):
        """Drop all motion. Does NOT release servos — the caller decides.

        Pose is forgotten so the next writer snaps rather than gliding from a
        stale guess.
        """
        self.queue = []
        self.current_glide = None
        self.hold_started_at = None
        self.last_pose = None
        self.active = False

    def _write_if_changed(self, pose):
        out = {}
        for channel_id in self.channels:
            out[channel_id] = clamp_degrees_int(pose[channel_id])
        if self.last_pose != out:
            self.write_pose(out)
            self.last_pose = out

    def _fill_omitted_channels(self, frame_pose):
        filled = {}
        for channel_id in self.channels:
            degrees = frame_pose[channel_id]
            if degrees is not None:
                filled[channel_id] = degrees
            elif self.last_pose is not None:
                filled[channel_id] = self.last_pose[channel_id]
            else:
                filled[channel_id] = SERVO_NEUTRAL_DEGREES
        return filled

    def _start_next_keyframe(self, now):
        frame_pose, milliseconds = self.queue.pop(0)
        target = self._fill_omitted_channels(frame_pose)
        if self.last_pose is None:
            self._write_if_changed(target)
        if milliseconds <= 0:
            self._write_if_changed(target)
            return
        # Still spend the frame's milliseconds after a cold snap so a chunk
        # lasts sum(milliseconds) whether it started warm or cold.
        self.current_glide = (dict(self.last_pose), target, milliseconds, now)
        self.hold_started_at = None

    def tick(self):
        """Call every main-loop pass (~every 20ms). True while this engine owns
        its channels (glide, or post-drain hold)."""
        if not self.active:
            return False
        now = self.ticks_ms()
        while self.current_glide is None and self.queue:
            self._start_next_keyframe(now)
        if self.current_glide:
            origin, target, milliseconds, started_at = self.current_glide
            progress = self.ticks_diff(now, started_at) / milliseconds
            if progress >= 1.0:
                self._write_if_changed(target)
                self.current_glide = None
                if self.queue:
                    self._start_next_keyframe(now)
                else:
                    self.hold_started_at = now
            else:
                ease = progress * progress * (3.0 - 2.0 * progress)
                midpoint = {
                    channel_id: origin[channel_id] + (target[channel_id] - origin[channel_id]) * ease
                    for channel_id in self.channels
                }
                self._write_if_changed(midpoint)
            return True
        if self.hold_started_at is None:
            self.hold_started_at = now
        if self.ticks_diff(now, self.hold_started_at) >= self.hold_milliseconds:
            self.release()
            self.hold_started_at = None
            self.active = False
            return False
        return True
