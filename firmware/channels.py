"""Channel is the only motion resource: id → degrees.

The public contract is this file's channel ids. HTTP, relay, walk frames, and
body_config gestures all use the same sparse pose. See docs/spec-rails.md.
"""

# --- channel ids -----------------------------------------------------------
CHANNEL_LEFT_LEG = "leg_l"
CHANNEL_RIGHT_LEG = "leg_r"
CHANNEL_LEFT_ARM = "arm_l"
CHANNEL_RIGHT_ARM = "arm_r"

LEG_CHANNEL_IDS = (CHANNEL_LEFT_LEG, CHANNEL_RIGHT_LEG)
ARM_CHANNEL_IDS = (CHANNEL_LEFT_ARM, CHANNEL_RIGHT_ARM)
ALL_CHANNEL_IDS = LEG_CHANNEL_IDS + ARM_CHANNEL_IDS

KEYFRAME_MILLISECONDS_KEY = "milliseconds"

# --- driver ports / GPIO (Kitronik port 2 is the unused socket) ------------
PORT_LEFT_LEG = 1
PORT_RIGHT_LEG = 3
PORT_LEFT_ARM = 4
PORT_RIGHT_ARM = 5
UNUSED_KITRONIK_PORT = 2

GPIO_LEFT_LEG = 0
GPIO_RIGHT_LEG = 1
GPIO_LEFT_ARM = 2
GPIO_RIGHT_ARM = 3

CHANNEL_PORT = {
    CHANNEL_LEFT_LEG: PORT_LEFT_LEG,
    CHANNEL_RIGHT_LEG: PORT_RIGHT_LEG,
    CHANNEL_LEFT_ARM: PORT_LEFT_ARM,
    CHANNEL_RIGHT_ARM: PORT_RIGHT_ARM,
}
PORT_TO_GPIO = {
    PORT_LEFT_LEG: GPIO_LEFT_LEG,
    PORT_RIGHT_LEG: GPIO_RIGHT_LEG,
    PORT_LEFT_ARM: GPIO_LEFT_ARM,
    PORT_RIGHT_ARM: GPIO_RIGHT_ARM,
}

# --- servo travel ----------------------------------------------------------
SERVO_MIN_DEGREES = 0
SERVO_MAX_DEGREES = 180
SERVO_NEUTRAL_DEGREES = 90

# --- engine budgets (firmware-owned; not verbs) ----------------------------
DEFAULT_STEP_MILLISECONDS = 400
MAX_STEP_MILLISECONDS = 3000
MAX_QUEUE_MILLISECONDS = 15000
HOLD_AFTER_DRAIN_MILLISECONDS = 300
DEAD_MAN_MILLISECONDS = 500
SETTLE_BEFORE_RELEASE_MILLISECONDS = 300

# --- enqueue modes ---------------------------------------------------------
ENQUEUE_MODE_REPLACE = "replace"
ENQUEUE_MODE_APPEND = "append"

ERROR_NO_VALID_KEYFRAMES = "no_valid_keyframes"
ERROR_QUEUE_FULL = "queue_full"
ERROR_BAD_PLAN_JSON = "bad_plan_json"
ERROR_UNKNOWN_CHANNEL = "unknown_channel"
ERROR_UNKNOWN_ROUTINE = "unknown_routine"

# --- JSON / HTTP bodies ----------------------------------------------------
PROTOCOL_GROWBOT_CHANNELS_1 = "growbot-channels-1"
JSON_PROTOCOL = "protocol"
JSON_OK = "ok"
JSON_QUEUED_MILLISECONDS = "queued_milliseconds"
JSON_ERROR = "error"
JSON_STEPS = "steps"
JSON_MODE = "mode"
JSON_CHANNELS = "channels"
JSON_ACTIVE = "active"
JSON_DEGREES = "degrees"
JSON_RELEASED = "released"
JSON_TYPE = "type"
JSON_REQUEST_ID = "request_id"
JSON_NAME = "name"
JSON_ID = "id"

ROUTINE_WIGGLE = "wiggle"
ROUTINE_DANCE = "dance"
ROUTINE_SHIMMY = "shimmy"
ROUTINE_MARCH = "march"
ROUTINE_BOW = "bow"
ROUTINE_STRETCH = "stretch"


def clamp_degrees(degrees):
    """Hard travel. Soft band lives in body_config and is phone-side."""
    if degrees < SERVO_MIN_DEGREES:
        return float(SERVO_MIN_DEGREES)
    if degrees > SERVO_MAX_DEGREES:
        return float(SERVO_MAX_DEGREES)
    return float(degrees)


def clamp_degrees_int(degrees):
    return int(clamp_degrees(degrees) + 0.5)


def normalize_enqueue_mode(mode):
    if mode == ENQUEUE_MODE_APPEND:
        return ENQUEUE_MODE_APPEND
    return ENQUEUE_MODE_REPLACE


def permit_pose(step):
    """Strong params: keep known channel ids + milliseconds. Unknown keys drop."""
    if not isinstance(step, dict):
        return None
    frame = {}
    for channel_id in ALL_CHANNEL_IDS:
        if channel_id in step and step[channel_id] is not None:
            frame[channel_id] = step[channel_id]
    if KEYFRAME_MILLISECONDS_KEY in step:
        frame[KEYFRAME_MILLISECONDS_KEY] = step[KEYFRAME_MILLISECONDS_KEY]
    if not any(channel_id in frame for channel_id in ALL_CHANNEL_IDS):
        return None
    return frame


def permit_poses(steps):
    """Keep only well-formed keyframes (channel ids)."""
    out = []
    if not isinstance(steps, list):
        return out
    for step in steps:
        frame = permit_pose(step)
        if frame is not None:
            out.append(frame)
    return out


def loaded_channel_ids(channel_port):
    return list(channel_port.keys())
