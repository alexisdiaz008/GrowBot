"""Channel is the only motion resource: id → degrees.

Convention: engines, PicoRobotics, and body_config `channels[].id` speak
channel ids. Wire aliases (`l`, `r`, `al`, `ar`) exist only at the HTTP/relay
edge — see docs/spec-rails.md. Do not change the public protocol.
"""

# --- channel ids (machine face) --------------------------------------------
CHANNEL_LEFT_LEG = "leg_l"
CHANNEL_RIGHT_LEG = "leg_r"
CHANNEL_LEFT_ARM = "arm_l"
CHANNEL_RIGHT_ARM = "arm_r"

LEG_CHANNEL_IDS = (CHANNEL_LEFT_LEG, CHANNEL_RIGHT_LEG)
ARM_CHANNEL_IDS = (CHANNEL_LEFT_ARM, CHANNEL_RIGHT_ARM)
ALL_CHANNEL_IDS = LEG_CHANNEL_IDS + ARM_CHANNEL_IDS

# --- wire aliases (HTTP query, /act JSON, relay frames) --------------------
WIRE_LEFT_LEG = "l"
WIRE_RIGHT_LEG = "r"
WIRE_LEFT_ARM = "al"
WIRE_RIGHT_ARM = "ar"

WIRE_TO_CHANNEL = {
    WIRE_LEFT_LEG: CHANNEL_LEFT_LEG,
    WIRE_RIGHT_LEG: CHANNEL_RIGHT_LEG,
    WIRE_LEFT_ARM: CHANNEL_LEFT_ARM,
    WIRE_RIGHT_ARM: CHANNEL_RIGHT_ARM,
}
CHANNEL_TO_WIRE = {
    CHANNEL_LEFT_LEG: WIRE_LEFT_LEG,
    CHANNEL_RIGHT_LEG: WIRE_RIGHT_LEG,
    CHANNEL_LEFT_ARM: WIRE_LEFT_ARM,
    CHANNEL_RIGHT_ARM: WIRE_RIGHT_ARM,
}

KEYFRAME_MILLISECONDS_KEY = "ms"

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
LEAN_DEGREES_AT_FULL_SPEED = 35

# --- engine budgets (firmware-owned; not verbs) ----------------------------
DEFAULT_STEP_MILLISECONDS = 400
MAX_STEP_MILLISECONDS = 3000
MAX_QUEUE_MILLISECONDS = 15000
HOLD_AFTER_DRAIN_MILLISECONDS = 300
DEAD_MAN_MILLISECONDS = 500
SETTLE_BEFORE_RELEASE_MILLISECONDS = 300

# --- enqueue modes (wire `mode` on /act) -----------------------------------
ENQUEUE_MODE_REPLACE = "replace"
ENQUEUE_MODE_APPEND = "append"

ERROR_NO_VALID_KEYFRAMES = "no valid keyframes"
ERROR_QUEUE_FULL = "queue full"

# --- JSON / HTTP bodies that conformance and the brain parse literally -----
JSON_OK = "ok"
JSON_QUEUED_MILLISECONDS = "queued_ms"
JSON_ERROR = "err"
JSON_STEPS = "steps"
JSON_MODE = "mode"
JSON_CHANNELS = "channels"
JSON_ACTIVE = "active"
HTTP_BODY_STOPPED = "stopped"

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


def speed_to_degrees(speed):
    """Legacy /set and /seq: speed -1..1 → lean around neutral."""
    if speed < -1.0:
        speed = -1.0
    elif speed > 1.0:
        speed = 1.0
    return int(SERVO_NEUTRAL_DEGREES - speed * LEAN_DEGREES_AT_FULL_SPEED)


def normalize_enqueue_mode(mode):
    if mode == ENQUEUE_MODE_APPEND:
        return ENQUEUE_MODE_APPEND
    return ENQUEUE_MODE_REPLACE


def translate_wire_step_to_channels(step):
    """Map one /act keyframe from wire aliases to channel ids. Unknown keys drop."""
    if not isinstance(step, dict):
        return None
    frame = {}
    for wire_key, channel_id in WIRE_TO_CHANNEL.items():
        if wire_key in step and step[wire_key] is not None:
            frame[channel_id] = step[wire_key]
    if KEYFRAME_MILLISECONDS_KEY in step:
        frame[KEYFRAME_MILLISECONDS_KEY] = step[KEYFRAME_MILLISECONDS_KEY]
    if not any(channel_id in frame for channel_id in ALL_CHANNEL_IDS):
        return None
    return frame


def translate_wire_steps_to_channels(steps):
    """Keep only well-formed keyframes, rewritten onto channel ids."""
    out = []
    if not isinstance(steps, list):
        return out
    for step in steps:
        frame = translate_wire_step_to_channels(step)
        if frame is not None:
            out.append(frame)
    return out


def wire_keys_for_channel_ports(channel_port):
    """Stats `channels` lists loaded *wire* keys (protocol, not ids)."""
    keys = []
    for channel_id in channel_port:
        wire_key = CHANNEL_TO_WIRE.get(channel_id)
        if wire_key is not None:
            keys.append(wire_key)
    return keys
