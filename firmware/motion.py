"""Shared body motion — the fat model both transports call.

HTTP and relay stay adapters: they parse JSON, then call this. Channel ids
only. Pins/ports come from the injected channel_port map (PicoRobotics).
"""
from act_engine import ActEngine, subset_steps_for_channels
from channels import (
    ARM_CHANNEL_IDS,
    CHANNEL_LEFT_ARM,
    CHANNEL_LEFT_LEG,
    CHANNEL_RIGHT_ARM,
    CHANNEL_RIGHT_LEG,
    ENQUEUE_MODE_REPLACE,
    ERROR_NO_VALID_KEYFRAMES,
    KEYFRAME_MILLISECONDS_KEY,
    LEG_CHANNEL_IDS,
    MAX_QUEUE_MILLISECONDS,
    MAX_STEP_MILLISECONDS,
    ROUTINE_BOW,
    ROUTINE_DANCE,
    ROUTINE_MARCH,
    ROUTINE_SHIMMY,
    ROUTINE_STRETCH,
    ROUTINE_WIGGLE,
    SERVO_NEUTRAL_DEGREES,
    clamp_degrees_int,
    loaded_channel_ids,
    normalize_enqueue_mode,
    permit_pose,
    permit_poses,
)


def canned_routines():
    """Absolute-degree keyframes in channel ids."""
    return {
        ROUTINE_WIGGLE: [
            {CHANNEL_LEFT_LEG: 60, CHANNEL_RIGHT_LEG: 120, KEYFRAME_MILLISECONDS_KEY: 400},
            {CHANNEL_LEFT_LEG: 120, CHANNEL_RIGHT_LEG: 60, KEYFRAME_MILLISECONDS_KEY: 400},
        ] * 2 + [
            {CHANNEL_LEFT_LEG: SERVO_NEUTRAL_DEGREES, CHANNEL_RIGHT_LEG: SERVO_NEUTRAL_DEGREES,
             KEYFRAME_MILLISECONDS_KEY: 300},
        ],
        ROUTINE_DANCE: [
            {CHANNEL_LEFT_LEG: 50, CHANNEL_RIGHT_LEG: 50, KEYFRAME_MILLISECONDS_KEY: 700},
            {CHANNEL_LEFT_LEG: 130, CHANNEL_RIGHT_LEG: 130, KEYFRAME_MILLISECONDS_KEY: 700},
            {CHANNEL_LEFT_LEG: 55, CHANNEL_RIGHT_LEG: 125, KEYFRAME_MILLISECONDS_KEY: 260},
            {CHANNEL_LEFT_LEG: 125, CHANNEL_RIGHT_LEG: 55, KEYFRAME_MILLISECONDS_KEY: 260},
            {CHANNEL_LEFT_LEG: 55, CHANNEL_RIGHT_LEG: 125, KEYFRAME_MILLISECONDS_KEY: 260},
            {CHANNEL_LEFT_LEG: 125, CHANNEL_RIGHT_LEG: 55, KEYFRAME_MILLISECONDS_KEY: 260},
            {CHANNEL_LEFT_LEG: 150, CHANNEL_RIGHT_LEG: 150, KEYFRAME_MILLISECONDS_KEY: 700},
            {CHANNEL_LEFT_LEG: SERVO_NEUTRAL_DEGREES, CHANNEL_RIGHT_LEG: SERVO_NEUTRAL_DEGREES,
             KEYFRAME_MILLISECONDS_KEY: 250},
            {CHANNEL_LEFT_LEG: 40, CHANNEL_RIGHT_LEG: 40, KEYFRAME_MILLISECONDS_KEY: 500},
        ],
        ROUTINE_SHIMMY: [
            {CHANNEL_LEFT_LEG: 75, CHANNEL_RIGHT_LEG: 105, KEYFRAME_MILLISECONDS_KEY: 180},
            {CHANNEL_LEFT_LEG: 105, CHANNEL_RIGHT_LEG: 75, KEYFRAME_MILLISECONDS_KEY: 180},
        ] * 4 + [
            {CHANNEL_LEFT_LEG: SERVO_NEUTRAL_DEGREES, CHANNEL_RIGHT_LEG: SERVO_NEUTRAL_DEGREES,
             KEYFRAME_MILLISECONDS_KEY: 250},
        ],
        ROUTINE_MARCH: [
            {CHANNEL_LEFT_LEG: 45, CHANNEL_RIGHT_LEG: 135, KEYFRAME_MILLISECONDS_KEY: 340},
            {CHANNEL_LEFT_LEG: 135, CHANNEL_RIGHT_LEG: 45, KEYFRAME_MILLISECONDS_KEY: 340},
        ] * 3 + [
            {CHANNEL_LEFT_LEG: SERVO_NEUTRAL_DEGREES, CHANNEL_RIGHT_LEG: SERVO_NEUTRAL_DEGREES,
             KEYFRAME_MILLISECONDS_KEY: 300},
        ],
        ROUTINE_BOW: [
            {CHANNEL_LEFT_LEG: 150, CHANNEL_RIGHT_LEG: 150, KEYFRAME_MILLISECONDS_KEY: 600},
            {CHANNEL_LEFT_LEG: 150, CHANNEL_RIGHT_LEG: 150, KEYFRAME_MILLISECONDS_KEY: 450},
            {CHANNEL_LEFT_LEG: SERVO_NEUTRAL_DEGREES, CHANNEL_RIGHT_LEG: SERVO_NEUTRAL_DEGREES,
             KEYFRAME_MILLISECONDS_KEY: 600},
        ],
        ROUTINE_STRETCH: [
            {CHANNEL_LEFT_LEG: 30, CHANNEL_RIGHT_LEG: 30, KEYFRAME_MILLISECONDS_KEY: 700},
            {CHANNEL_LEFT_LEG: 30, CHANNEL_RIGHT_LEG: 30, KEYFRAME_MILLISECONDS_KEY: 500},
            {CHANNEL_LEFT_LEG: SERVO_NEUTRAL_DEGREES, CHANNEL_RIGHT_LEG: SERVO_NEUTRAL_DEGREES,
             KEYFRAME_MILLISECONDS_KEY: 700},
        ],
    }


class BodyMotion:
    def __init__(self, board, channel_port, ticks_ms, ticks_diff, led=None,
                 sleep_milliseconds=None,
                 max_step_milliseconds=MAX_STEP_MILLISECONDS,
                 max_queue_milliseconds=MAX_QUEUE_MILLISECONDS):
        self.board = board
        self.channel_port = channel_port
        self.ticks_ms = ticks_ms
        self.ticks_diff = ticks_diff
        self.led = led
        self.sleep_milliseconds = sleep_milliseconds
        self.routines = canned_routines()
        self.legs_engine = ActEngine(
            self.write_pose,
            lambda: self.release_channels(LEG_CHANNEL_IDS, turn_led_off=True),
            ticks_ms, ticks_diff,
            channels=LEG_CHANNEL_IDS,
            max_step_milliseconds=max_step_milliseconds,
            max_queue_milliseconds=max_queue_milliseconds,
        )
        self.arms_engine = ActEngine(
            self.write_pose,
            lambda: self.release_channels(ARM_CHANNEL_IDS, turn_led_off=False),
            ticks_ms, ticks_diff,
            channels=ARM_CHANNEL_IDS,
            max_step_milliseconds=max_step_milliseconds,
            max_queue_milliseconds=max_queue_milliseconds,
        )

    def port_for(self, channel_id):
        return self.channel_port.get(channel_id)

    def knows_channel(self, channel_id):
        return channel_id in self.channel_port

    def write_pose(self, pose):
        for channel_id, degrees in pose.items():
            port = self.port_for(channel_id)
            if port is not None:
                self.board.servoWrite(port, degrees)
        if self.led:
            self.led.on()

    def release_channels(self, channel_ids, turn_led_off=True):
        for channel_id in channel_ids:
            port = self.port_for(channel_id)
            if port is not None:
                self.board.release(port)
        if turn_led_off and self.led:
            self.led.off()

    def release_all_mapped_ports(self):
        self.release_channels(tuple(self.channel_port.keys()), turn_led_off=True)

    def write_channel_degrees(self, channel_id, degrees):
        port = self.port_for(channel_id)
        if port is None:
            return False
        self.board.servoWrite(port, clamp_degrees_int(degrees))
        return True

    def enqueue_steps(self, steps, mode=ENQUEUE_MODE_REPLACE):
        """Permit channel-id keyframes, split across engines.

        Arms-only does not clear walk. Returns (ok, queued_or_error, used_legs).
        """
        mode = normalize_enqueue_mode(mode)
        permitted = permit_poses(steps)
        leg_steps = subset_steps_for_channels(permitted, LEG_CHANNEL_IDS)
        arm_steps = subset_steps_for_channels(permitted, ARM_CHANNEL_IDS)
        if not leg_steps and not arm_steps:
            return False, ERROR_NO_VALID_KEYFRAMES, False
        if leg_steps:
            succeeded, result = self.legs_engine.enqueue(leg_steps, mode)
            if not succeeded:
                return False, result, True
        if arm_steps:
            succeeded, result = self.arms_engine.enqueue(arm_steps, mode)
            if not succeeded:
                return False, result, bool(leg_steps)
        return True, self.queued_milliseconds(), bool(leg_steps)

    def enqueue_routine(self, name):
        frames = self.routines.get(name)
        if not frames:
            return False, None, False
        return self.enqueue_steps(frames, ENQUEUE_MODE_REPLACE)

    def clear_legs(self):
        self.legs_engine.clear()

    def clear_arms(self):
        self.arms_engine.clear()

    def clear_both(self):
        self.legs_engine.clear()
        self.arms_engine.clear()

    def stop(self):
        self.clear_both()
        self.release_all_mapped_ports()

    def queued_milliseconds(self):
        return max(self.legs_engine.queued_milliseconds(),
                   self.arms_engine.queued_milliseconds())

    def any_engine_active(self):
        return self.legs_engine.active or self.arms_engine.active

    def loaded_channel_ids(self):
        return loaded_channel_ids(self.channel_port)

    def tick(self):
        self.legs_engine.tick()
        self.arms_engine.tick()

    def quick_release_legs(self):
        """Limp stop for pose/walk dead-man (no recenter snap)."""
        self.release_channels(LEG_CHANNEL_IDS)

    def apply_sparse_pose(self, pose):
        """Instant pose from a sparse channel-id map.

        Returns (touched_legs, touched_arms) so the adapter can manage dead-man.
        """
        permitted = permit_pose(pose) or {}
        touched_legs = any(channel_id in permitted for channel_id in LEG_CHANNEL_IDS)
        touched_arms = any(channel_id in permitted for channel_id in ARM_CHANNEL_IDS)
        if touched_legs:
            self.clear_legs()
            for channel_id in LEG_CHANNEL_IDS:
                if channel_id in permitted:
                    self.write_channel_degrees(channel_id, permitted[channel_id])
            if self.led:
                self.led.on()
        if touched_arms:
            self.clear_arms()
            for channel_id in ARM_CHANNEL_IDS:
                if channel_id in permitted:
                    self.write_channel_degrees(channel_id, permitted[channel_id])
            if self.led:
                self.led.on()
        return touched_legs, touched_arms
