"""Shared body motion — the fat model both transports call.

HTTP (`robot-server.py`) and relay (`relay_chip.py`) stay adapters: they parse
the wire, then call this. Channel ids only; wire aliases are translated before
enqueue. Pins/ports come from the injected channel_port map (PicoRobotics).
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
    SETTLE_BEFORE_RELEASE_MILLISECONDS,
    WIRE_LEFT_LEG,
    WIRE_RIGHT_LEG,
    clamp_degrees_int,
    normalize_enqueue_mode,
    speed_to_degrees,
    translate_wire_steps_to_channels,
    wire_keys_for_channel_ports,
)


def canned_routines():
    """Absolute-degree keyframes in *wire* aliases — translated at enqueue."""
    return {
        ROUTINE_WIGGLE: [
            {WIRE_LEFT_LEG: 60, WIRE_RIGHT_LEG: 120, KEYFRAME_MILLISECONDS_KEY: 400},
            {WIRE_LEFT_LEG: 120, WIRE_RIGHT_LEG: 60, KEYFRAME_MILLISECONDS_KEY: 400},
        ] * 2 + [
            {WIRE_LEFT_LEG: SERVO_NEUTRAL_DEGREES, WIRE_RIGHT_LEG: SERVO_NEUTRAL_DEGREES,
             KEYFRAME_MILLISECONDS_KEY: 300},
        ],
        ROUTINE_DANCE: [
            {WIRE_LEFT_LEG: 50, WIRE_RIGHT_LEG: 50, KEYFRAME_MILLISECONDS_KEY: 700},
            {WIRE_LEFT_LEG: 130, WIRE_RIGHT_LEG: 130, KEYFRAME_MILLISECONDS_KEY: 700},
            {WIRE_LEFT_LEG: 55, WIRE_RIGHT_LEG: 125, KEYFRAME_MILLISECONDS_KEY: 260},
            {WIRE_LEFT_LEG: 125, WIRE_RIGHT_LEG: 55, KEYFRAME_MILLISECONDS_KEY: 260},
            {WIRE_LEFT_LEG: 55, WIRE_RIGHT_LEG: 125, KEYFRAME_MILLISECONDS_KEY: 260},
            {WIRE_LEFT_LEG: 125, WIRE_RIGHT_LEG: 55, KEYFRAME_MILLISECONDS_KEY: 260},
            {WIRE_LEFT_LEG: 150, WIRE_RIGHT_LEG: 150, KEYFRAME_MILLISECONDS_KEY: 700},
            {WIRE_LEFT_LEG: SERVO_NEUTRAL_DEGREES, WIRE_RIGHT_LEG: SERVO_NEUTRAL_DEGREES,
             KEYFRAME_MILLISECONDS_KEY: 250},
            {WIRE_LEFT_LEG: 40, WIRE_RIGHT_LEG: 40, KEYFRAME_MILLISECONDS_KEY: 500},
        ],
        ROUTINE_SHIMMY: [
            {WIRE_LEFT_LEG: 75, WIRE_RIGHT_LEG: 105, KEYFRAME_MILLISECONDS_KEY: 180},
            {WIRE_LEFT_LEG: 105, WIRE_RIGHT_LEG: 75, KEYFRAME_MILLISECONDS_KEY: 180},
        ] * 4 + [
            {WIRE_LEFT_LEG: SERVO_NEUTRAL_DEGREES, WIRE_RIGHT_LEG: SERVO_NEUTRAL_DEGREES,
             KEYFRAME_MILLISECONDS_KEY: 250},
        ],
        ROUTINE_MARCH: [
            {WIRE_LEFT_LEG: 45, WIRE_RIGHT_LEG: 135, KEYFRAME_MILLISECONDS_KEY: 340},
            {WIRE_LEFT_LEG: 135, WIRE_RIGHT_LEG: 45, KEYFRAME_MILLISECONDS_KEY: 340},
        ] * 3 + [
            {WIRE_LEFT_LEG: SERVO_NEUTRAL_DEGREES, WIRE_RIGHT_LEG: SERVO_NEUTRAL_DEGREES,
             KEYFRAME_MILLISECONDS_KEY: 300},
        ],
        ROUTINE_BOW: [
            {WIRE_LEFT_LEG: 150, WIRE_RIGHT_LEG: 150, KEYFRAME_MILLISECONDS_KEY: 600},
            {WIRE_LEFT_LEG: 150, WIRE_RIGHT_LEG: 150, KEYFRAME_MILLISECONDS_KEY: 450},
            {WIRE_LEFT_LEG: SERVO_NEUTRAL_DEGREES, WIRE_RIGHT_LEG: SERVO_NEUTRAL_DEGREES,
             KEYFRAME_MILLISECONDS_KEY: 600},
        ],
        ROUTINE_STRETCH: [
            {WIRE_LEFT_LEG: 30, WIRE_RIGHT_LEG: 30, KEYFRAME_MILLISECONDS_KEY: 700},
            {WIRE_LEFT_LEG: 30, WIRE_RIGHT_LEG: 30, KEYFRAME_MILLISECONDS_KEY: 500},
            {WIRE_LEFT_LEG: SERVO_NEUTRAL_DEGREES, WIRE_RIGHT_LEG: SERVO_NEUTRAL_DEGREES,
             KEYFRAME_MILLISECONDS_KEY: 700},
        ],
    }


def speed_steps_to_wire_keyframes(steps):
    """/seq compatibility: v2 ±1 speed steps → absolute-degree wire keyframes."""
    out = []
    if not isinstance(steps, list):
        return out
    for step in steps:
        try:
            left_speed = float(step.get(WIRE_LEFT_LEG, 0))
            right_speed = float(step.get(WIRE_RIGHT_LEG, 0))
            milliseconds = int(step.get(KEYFRAME_MILLISECONDS_KEY, 400))
            out.append({
                WIRE_LEFT_LEG: speed_to_degrees(left_speed),
                WIRE_RIGHT_LEG: speed_to_degrees(right_speed),
                KEYFRAME_MILLISECONDS_KEY: milliseconds,
            })
        except (ValueError, TypeError, AttributeError):
            continue
    return out


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

    def write_leg_speeds(self, left_speed, right_speed):
        left_port = self.port_for(CHANNEL_LEFT_LEG)
        right_port = self.port_for(CHANNEL_RIGHT_LEG)
        if left_port is not None:
            self.board.servoWrite(left_port, speed_to_degrees(left_speed))
        if right_port is not None:
            self.board.servoWrite(right_port, speed_to_degrees(right_speed))

    def write_channel_degrees(self, channel_id, degrees):
        port = self.port_for(channel_id)
        if port is None:
            return False
        self.board.servoWrite(port, clamp_degrees_int(degrees))
        return True

    def enqueue_wire_steps(self, steps, mode=ENQUEUE_MODE_REPLACE):
        """Translate wire keyframes, split across engines.

        Arms-only does not clear walk. Returns (ok, queued_or_error, used_legs).
        """
        mode = normalize_enqueue_mode(mode)
        translated = translate_wire_steps_to_channels(steps)
        leg_steps = subset_steps_for_channels(translated, LEG_CHANNEL_IDS)
        arm_steps = subset_steps_for_channels(translated, ARM_CHANNEL_IDS)
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
        return self.enqueue_wire_steps(frames, ENQUEUE_MODE_REPLACE)

    def clear_legs(self):
        self.legs_engine.clear()

    def clear_arms(self):
        self.arms_engine.clear()

    def clear_both(self):
        self.legs_engine.clear()
        self.arms_engine.clear()

    def queued_milliseconds(self):
        return max(self.legs_engine.queued_milliseconds(),
                   self.arms_engine.queued_milliseconds())

    def any_engine_active(self):
        return self.legs_engine.active or self.arms_engine.active

    def loaded_wire_keys(self):
        return wire_keys_for_channel_ports(self.channel_port)

    def tick(self):
        self.legs_engine.tick()
        self.arms_engine.tick()

    def quick_stop_legs(self):
        """Immediate zero + release (for /set 0,0 and speed-mode dead-man)."""
        self.write_leg_speeds(0, 0)
        self.release_channels(LEG_CHANNEL_IDS)

    def quick_release_legs(self):
        """Limp stop for pose mode (no recenter snap)."""
        self.release_channels(LEG_CHANNEL_IDS)

    def settle_then_release_all(self):
        """Walk-speed /stop: recenter, pause, limp every mapped port."""
        self.write_leg_speeds(0, 0)
        if self.sleep_milliseconds:
            self.sleep_milliseconds(SETTLE_BEFORE_RELEASE_MILLISECONDS)
        self.release_all_mapped_ports()

    def apply_absolute_pose(self, left_leg=None, right_leg=None,
                            left_arm=None, right_arm=None):
        """Instant pose. Missing pair = do not touch that engine.

        Returns (touched_legs, touched_arms) so the adapter can manage dead-man.
        """
        touched_legs = left_leg is not None or right_leg is not None
        touched_arms = left_arm is not None or right_arm is not None
        if touched_legs:
            self.clear_legs()
            if left_leg is not None:
                self.write_channel_degrees(CHANNEL_LEFT_LEG, left_leg)
            if right_leg is not None:
                self.write_channel_degrees(CHANNEL_RIGHT_LEG, right_leg)
            if self.led:
                self.led.on()
        if touched_arms:
            self.clear_arms()
            if left_arm is not None:
                self.write_channel_degrees(CHANNEL_LEFT_ARM, left_arm)
            if right_arm is not None:
                self.write_channel_degrees(CHANNEL_RIGHT_ARM, right_arm)
            if self.led:
                self.led.on()
        return touched_legs, touched_arms
