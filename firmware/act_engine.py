"""Keyframe motion engine for the robot body - hardware-free, Mac-testable.

This is the hobby-scale version of "action chunking" from modern robotics
(ACT, Zhao et al. 2023): the brain (phone/LLM) ships a short PLAN of poses,
the body executes it locally at ~50Hz with smooth glides, and the next chunk
may arrive while this one plays - so gestures chain with no dead air, and the
Wi-Fi link only has to carry intent, never per-tick servo commands.

A keyframe is a sparse map of channel -> degrees plus "ms":
  - channel values are absolute servo degrees (90 = neutral stance)
  - ms = how long the glide TO that pose takes (0 = snap). From a cold
    start (pose unknown) the first frame snaps into place, then holds out
    its ms - a chunk always lasts sum(ms), warm or cold
  - omit a channel to leave it at its current target
  - repeat the same pose to hold it (a musical rest)

Default channels are ("l", "r") — the 2-leg wire keys. A second instance
with ("al", "ar") owns arms; the two engines must not clear each other.

Glides are eased with smoothstep (slow-in, slow-out) so motion reads as a
living thing, not a stepper. When the queue drains the engine holds the last
pose briefly, then releases the servos (limp = cool + silent + ~6mA).

No MicroPython imports here. The firmware injects the servo writer, the
release function, and the tick functions; the Mac test injects fakes.
Time follows time.ticks_ms semantics (ticks_ms / ticks_diff).
write_pose(pose_dict) receives every channel this engine owns as ints.
"""


def subset_steps(steps, keys):
    """Keep only this engine's keys from a /act plan (plus ms)."""
    out = []
    if not isinstance(steps, list):
        return out
    for st in steps:
        if not isinstance(st, dict):
            continue
        frame = {}
        for k in keys:
            if k in st and st[k] is not None:
                frame[k] = st[k]
        if not frame:
            continue
        if "ms" in st:
            frame["ms"] = st["ms"]
        out.append(frame)
    return out


class ActEngine:
    def __init__(self, write_pose, release, ticks_ms, ticks_diff,
                 channels=("l", "r"),
                 max_step_ms=3000, max_queue_ms=15000, hold_ms=300):
        self.write_pose = write_pose    # fn({channel: deg_int, ...})
        self.release = release          # fn() -> go limp
        self.ticks_ms = ticks_ms
        self.ticks_diff = ticks_diff
        self.channels = tuple(channels)
        self.max_step_ms = max_step_ms
        self.max_queue_ms = max_queue_ms
        self.hold_ms = hold_ms
        self.q = []                     # validated keyframes: (pose_or_none map, ms)
        self.cur = None                 # active glide: (from, to, ms, t0)
        self.pose = None                # last commanded {ch: int}; None = unknown
        self.hold_t0 = None             # queue drained at this tick (hold timer)
        self.active = False

    def _extract(self, st):
        pose = {}
        for ch in self.channels:
            if ch not in st or st[ch] is None:
                pose[ch] = None
                continue
            pose[ch] = max(0.0, min(180.0, float(st[ch])))
        if all(v is None for v in pose.values()):
            return None
        ms = min(int(st.get("ms", 400)), self.max_step_ms)
        return pose, max(0, ms)

    # ---------- feeding ----------

    def enqueue(self, steps, mode="replace"):
        """Validate + queue a chunk. Returns (ok, queued_ms_or_error_string).
        mode "replace": drop the queue AND the in-flight glide; the new chunk
        glides from wherever the channels are right now (smooth takeover).
        mode "append": play after everything already queued (pipelining)."""
        frames = []
        for st in steps:
            try:
                got = self._extract(st)
            except (ValueError, TypeError, AttributeError):
                continue
            if got is None:
                continue
            frames.append(got)
        if not frames:
            return False, "no valid keyframes"
        new_ms = sum(f[1] for f in frames)
        if mode == "replace":
            self.q = []
            self.cur = None
        if self.queued_ms() + new_ms > self.max_queue_ms:
            return False, "queue full"
        self.q.extend(frames)
        self.hold_t0 = None
        self.active = True
        return True, self.queued_ms()

    def queued_ms(self):
        total = sum(f[1] for f in self.q)
        if self.cur:
            left = self.cur[2] - self.ticks_diff(self.ticks_ms(), self.cur[3])
            total += max(0, left)
        return total

    def clear(self):
        """Drop all motion (for /stop and manual-control overrides). Does NOT
        release the servos - the caller decides. Pose is forgotten: whoever
        moves the channels next, the following chunk snaps rather than gliding
        from a stale guess."""
        self.q = []
        self.cur = None
        self.hold_t0 = None
        self.pose = None
        self.active = False

    # ---------- playing ----------

    def _write(self, pose):
        out = {}
        for ch in self.channels:
            v = pose[ch]
            out[ch] = int(min(180, max(0, v)) + 0.5)
        if self.pose != out:
            self.write_pose(out)
            self.pose = out

    def _filled(self, frame_pose):
        filled = {}
        for ch in self.channels:
            v = frame_pose[ch]
            if v is not None:
                filled[ch] = v
            elif self.pose is not None:
                filled[ch] = self.pose[ch]
            else:
                filled[ch] = 90
        return filled

    def _start_next(self, now):
        frame_pose, ms = self.q.pop(0)
        tl = self._filled(frame_pose)
        if self.pose is None:
            self._write(tl)             # cold start: place at once...
        if ms <= 0:
            self._write(tl)             # explicit snap frame
            return
        # ...then still spend the frame's ms (constant glide = hold), so a
        # chunk lasts sum(ms) whether it started warm or cold.
        self.cur = (dict(self.pose), tl, ms, now)
        self.hold_t0 = None

    def tick(self):
        """Call every main-loop pass (~every 20ms). Returns True while the
        engine owns its channels (glide, or post-drain hold)."""
        if not self.active:
            return False
        now = self.ticks_ms()
        while self.cur is None and self.q:  # ms=0 snap frames chain same-tick
            self._start_next(now)
        if self.cur:
            fl, tl, ms, t0 = self.cur
            p = self.ticks_diff(now, t0) / ms
            if p >= 1.0:
                self._write(tl)
                self.cur = None
                if self.q:
                    self._start_next(now)
                else:
                    self.hold_t0 = now
            else:
                e = p * p * (3.0 - 2.0 * p)     # smoothstep ease
                mid = {ch: fl[ch] + (tl[ch] - fl[ch]) * e for ch in self.channels}
                self._write(mid)
            return True
        if self.hold_t0 is None:                # drained with nothing played
            self.hold_t0 = now
        if self.ticks_diff(now, self.hold_t0) >= self.hold_ms:
            self.release()                      # limp; pose kept as best guess
            self.hold_t0 = None
            self.active = False
            return False
        return True
