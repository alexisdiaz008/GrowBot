# GrowBot relay client — the Pico dials OUT to the relay as a WebSocket client.
# Runs as main.py on boot (battery, untethered) OR via `mpremote run`.
# Speaks BOTH body lanes over the relay, reusing the motor driver + act_engine
# (so gestures glide exactly like the LAN firmware).
#
# ===== CANONICAL WIRE PROTOCOL (keep identical to HTTP; growbot-channels-1) =====
#   phone -> chip:
#     {"type":"pose","leg_l":70,"leg_r":110}            WALK: latest-wins ~30Hz, sparse JSON
#     {"type":"plan","request_id","steps","mode"}         GESTURE keyframes; arms-only leaves walk
#     {"type":"routine","request_id","name"}              canned gesture (e.g. "wiggle")
#     {"type":"stop","request_id"}                        halt gesture + limp
#   chip -> phone:
#     {"type":"hello","id"}                               chip handshake to the relay
#     {"type":"ack","request_id","ok","queued_milliseconds"}
#     {"type":"status","awake"}                           emitted by the RELAY (chip presence)
#
# ===== LINK SELF-HEAL =====
# Field failure: a servo-current brownout can kill the WiFi/relay link while the Pico
# keeps running — LED lit, robot deaf, only a power cycle brought it back. The link now
# heals itself, in escalating layers:
#   1. every socket op carries a timeout — no connect/read/write can block forever
#   2. link heartbeat: once the socket goes quiet the chip PINGs the relay (Cloudflare's
#      edge pongs back on its own; the traffic also keeps home-router NAT entries alive);
#      nothing received for LINK_DEAD_MS -> tear down and re-dial
#   3. wifi watch: WLAN drop -> reassociate + re-dial, exponential backoff between tries
#   4. escalation: every WIFI_RESET_EVERY straight failures power-cycle the radio
#      (active False/True); after HARD_RESET_AFTER failures, machine.reset() = an
#      automatic power cycle (boot skips the calibration stretch on self-heal resets)
#   5. a hardware watchdog — armed at the FIRST relay connect, unarmed before that so a
#      no-wifi boot idles calmly — reboots the chip if the firmware itself ever freezes
# The walk dead-man below is a FEATURE (limp on pose silence) and is separate from this.
import network, socket, ssl, os, json, time, binascii, select, machine
try:
    from channels import (
        CHANNEL_LEFT_LEG,
        CHANNEL_RIGHT_LEG,
        DEAD_MAN_MILLISECONDS,
        ENQUEUE_MODE_REPLACE,
        JSON_ID,
        JSON_MODE,
        JSON_NAME,
        JSON_OK,
        JSON_QUEUED_MILLISECONDS,
        JSON_REQUEST_ID,
        JSON_STEPS,
        JSON_TYPE,
        LEG_CHANNEL_IDS,
        SERVO_NEUTRAL_DEGREES,
        permit_pose,
    )
    from motion import BodyMotion
except ImportError:
    print("MISSING channels.py / act_engine.py / motion.py — motors disabled")
    while True:
        time.sleep(1)
import PicoRobotics

RELAY_HOST = "growbot-relay.growbot.workers.dev"
DEVICE_ID = "gb-" + binascii.hexlify(machine.unique_id()).decode()[-6:]
RELAY_PATH = "/d/" + DEVICE_ID

print("\n========================================")
print("  PAIRING CODE:  " + DEVICE_ID)
print("  Enter this code in the GrowBot app.")
print("========================================\n")

board = PicoRobotics.KitronikPicoRobotics()
motion = BodyMotion(board, PicoRobotics.CHANNEL_PORT, time.ticks_ms, time.ticks_diff)

POLL_MILLISECONDS = 20
NETWORK_TIMEOUT_SECONDS = 6
PING_MILLISECONDS = 10000
LINK_DEAD_MILLISECONDS = 25000
WIFI_RESET_EVERY_FAILURES = 3
HARD_RESET_AFTER_FAILURES = 10
WATCHDOG_MILLISECONDS = 8000
WIFI_JOIN_ATTEMPTS = 150
WIFI_JOIN_POLL_MILLISECONDS = 100
WATCHDOG_FEED_SLICE_MILLISECONDS = 200
RADIO_BOUNCE_MILLISECONDS = 1000
COLD_BOOT_SETTLE_MILLISECONDS = 2000
HEALTHY_SESSION_MILLISECONDS = 30000
REDIAL_BACKOFF_CAP_MILLISECONDS = 30000
REDIAL_BACKOFF_BASE_MILLISECONDS = 1000
TLS_PORT = 443

RELAY_TYPE_POSE = "pose"
RELAY_TYPE_PLAN = "plan"
RELAY_TYPE_ROUTINE = "routine"
RELAY_TYPE_STOP = "stop"
RELAY_TYPE_HELLO = "hello"
RELAY_TYPE_ACK = "ack"
RELAY_SEQUENCE = "seq"
RELAY_TIMESTAMP = "ts"

LANE_POSE = "pose"
LANE_ACT_LEGS = "act_legs"
LANE_ACT_ARMS = "act_arms"
LANE_STOP = "stop"

JSON_OK_TRUE = True
JSON_OK_FALSE = False
WEBSOCKET_LENGTH_16BIT = 126
WEBSOCKET_TEXT_FRAME_UNMASKED_BASE = 0x81
WEBSOCKET_MASK_BIT = 0x80
HTTP_SWITCHING_PROTOCOLS_TOKEN = b" 101 "

wlan = network.WLAN(network.STA_IF)
hardware_watchdog = None

def feed():
    if hardware_watchdog:
        hardware_watchdog.feed()


def sleep_fed(milliseconds):
    while milliseconds > 0:
        feed()
        slice_ms = min(milliseconds, WATCHDOG_FEED_SLICE_MILLISECONDS)
        time.sleep_ms(slice_ms)
        milliseconds -= slice_ms

def ensure_wifi():
    wlan.active(True)
    if not wlan.isconnected():
        try:
            import secrets
            # field secrets.py (written by the build page + all existing robots) says WIFI_PASS;
            # newer secrets.example.py says WIFI_PASSWORD — accept both, or cold boots crash here.
            wifi_password = getattr(secrets, "WIFI_PASSWORD", None) or getattr(secrets, "WIFI_PASS", "")
            wlan.connect(secrets.WIFI_SSID, wifi_password)
        except Exception as error:
            print("wifi err", error)
        for _attempt in range(WIFI_JOIN_ATTEMPTS):
            if wlan.isconnected():
                break
            feed()
            time.sleep_ms(WIFI_JOIN_POLL_MILLISECONDS)
    joined = wlan.isconnected()
    # distinct one-line tokens the build-page flasher scans for, so "flashed OK" never masks "Wi-Fi didn't join"
    if joined:
        print("WIFI_OK", wlan.ifconfig()[0])
    else:
        print("WIFI_FAIL")
    print("wifi:", joined, wlan.ifconfig()[0] if joined else "-")
    return joined

def wifi_reset():
    # power the radio down and back up — recovers a brownout-wedged CYW43 that still
    # CLAIMS to be associated (or won't reassociate) without a full chip reset
    print("wifi: bouncing the radio")
    try:
        wlan.disconnect()
    except Exception:
        pass
    try:
        wlan.active(False)
    except Exception:
        pass
    sleep_fed(RADIO_BOUNCE_MILLISECONDS)
    wlan.active(True)

def open_relay_socket():
    feed()
    address = socket.getaddrinfo(RELAY_HOST, TLS_PORT)[0][-1]
    raw_socket = socket.socket()
    raw_socket.settimeout(NETWORK_TIMEOUT_SECONDS)
    feed()
    try:
        raw_socket.connect(address)
        feed()
        ssl_socket = ssl.wrap_socket(raw_socket, server_hostname=RELAY_HOST)
    except Exception:
        raw_socket.close()
        raise
    key = binascii.b2a_base64(os.urandom(16)).strip().decode()
    request = ("GET %s HTTP/1.1\r\nHost: %s\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
               "Sec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n") % (
                   RELAY_PATH, RELAY_HOST, key)
    ssl_socket.write(request.encode())
    response = b""
    while b"\r\n\r\n" not in response:
        feed()
        chunk = ssl_socket.read(1)
        if not chunk:
            break
        response += chunk
    handshake_ok = HTTP_SWITCHING_PROTOCOLS_TOKEN in response
    print("handshake:", "OK" if handshake_ok else "FAIL", response.split(b"\r\n")[0])
    if not handshake_ok:
        for sock in (ssl_socket, raw_socket):
            try:
                sock.close()
            except Exception:
                pass
        return (None, None)
    return (ssl_socket, raw_socket)


def send_text(ssl_socket, text):
    payload = text.encode()
    length = len(payload)
    mask = os.urandom(4)
    if length < WEBSOCKET_LENGTH_16BIT:
        header = bytes([WEBSOCKET_TEXT_FRAME_UNMASKED_BASE, WEBSOCKET_MASK_BIT | length])
    else:
        header = bytes([
            WEBSOCKET_TEXT_FRAME_UNMASKED_BASE,
            WEBSOCKET_MASK_BIT | WEBSOCKET_LENGTH_16BIT,
            (length >> 8) & 0xFF,
            length & 0xFF,
        ])
    masked_payload = bytearray(length)
    for index in range(length):
        masked_payload[index] = payload[index] ^ mask[index & 3]
    ssl_socket.write(header + mask + bytes(masked_payload))


def recv_exact(ssl_socket, count):
    buffer = b""
    while len(buffer) < count:
        feed()
        chunk = ssl_socket.read(count - len(buffer))
        if not chunk:
            return None
        buffer += chunk
    return buffer


def read_frame_after_first_byte(ssl_socket, first_byte):
    second_byte = recv_exact(ssl_socket, 1)
    if not second_byte:
        return (None, None)
    opcode = first_byte[0] & 0x0F
    length = second_byte[0] & 0x7F
    if length == WEBSOCKET_LENGTH_16BIT:
        extra = recv_exact(ssl_socket, 2)
        length = (extra[0] << 8) | extra[1]
    elif length == 127:
        extra = recv_exact(ssl_socket, 8)
        length = 0
        for byte in extra:
            length = (length << 8) | byte
    masked = second_byte[0] & WEBSOCKET_MASK_BIT
    mask = recv_exact(ssl_socket, 4) if masked else None
    payload = recv_exact(ssl_socket, length) if length else b""
    if masked and payload:
        payload = bytes(payload[index] ^ mask[index & 3] for index in range(length))
    return (opcode, payload)


def send_ack(ssl_socket, message, succeeded, queued_milliseconds):
    send_text(ssl_socket, json.dumps({
        JSON_TYPE: RELAY_TYPE_ACK,
        JSON_REQUEST_ID: message.get(JSON_REQUEST_ID),
        JSON_OK: JSON_OK_TRUE if succeeded else JSON_OK_FALSE,
        JSON_QUEUED_MILLISECONDS: queued_milliseconds,
    }))


def walk_pose_from_message(message):
    permitted = permit_pose(message) or {}
    walk_pose = {}
    for channel_id in LEG_CHANNEL_IDS:
        if channel_id in permitted:
            walk_pose[channel_id] = permitted[channel_id]
    return walk_pose


def handle_relay_message(ssl_socket, payload):
    """Dispatch one text frame. Returns the lane kind so serve() can manage the dead-man."""
    try:
        message = json.loads(payload)
    except Exception:
        return None
    message_type = message.get(JSON_TYPE)
    if message_type == RELAY_TYPE_POSE:
        walk_pose = walk_pose_from_message(message)
        if not walk_pose:
            return None
        motion.apply_sparse_pose(walk_pose)
        if RELAY_SEQUENCE in message:
            send_text(ssl_socket, json.dumps({
                JSON_TYPE: RELAY_TYPE_ACK,
                RELAY_SEQUENCE: message[RELAY_SEQUENCE],
                RELAY_TIMESTAMP: message.get(RELAY_TIMESTAMP, 0),
            }))
        return LANE_POSE
    if message_type == RELAY_TYPE_PLAN:
        succeeded, queued, used_legs = motion.enqueue_steps(
            message.get(JSON_STEPS, []), message.get(JSON_MODE, ENQUEUE_MODE_REPLACE))
        send_ack(ssl_socket, message, succeeded, queued if succeeded else 0)
        return LANE_ACT_LEGS if used_legs else LANE_ACT_ARMS
    if message_type == RELAY_TYPE_ROUTINE:
        succeeded, queued, used_legs = motion.enqueue_routine(message.get(JSON_NAME, ""))
        send_ack(ssl_socket, message, succeeded, queued if succeeded else 0)
        return LANE_ACT_LEGS if used_legs else LANE_ACT_ARMS
    if message_type == RELAY_TYPE_STOP:
        motion.stop()
        send_ack(ssl_socket, message, True, 0)
        return LANE_STOP
    return None


WEBSOCKET_OPCODE_CLOSE = 0x8
WEBSOCKET_OPCODE_PING = 0x9
WEBSOCKET_OPCODE_TEXT = 0x1
WEBSOCKET_CLIENT_PONG = bytes([0x8A, WEBSOCKET_MASK_BIT])
WEBSOCKET_CLIENT_PING = bytes([0x89, WEBSOCKET_MASK_BIT])
POSE_RATE_LOG_MILLISECONDS = 1000


def serve(ssl_socket, raw_socket):
    global hardware_watchdog
    poll = select.poll()
    poll.register(raw_socket, select.POLLIN)
    send_text(ssl_socket, json.dumps({
        JSON_TYPE: RELAY_TYPE_HELLO,
        JSON_ID: DEVICE_ID,
    }))
    print("hello sent; walk + gesture lanes ready (dead-man %dms)" % DEAD_MAN_MILLISECONDS)
    if hardware_watchdog is None:
        hardware_watchdog = machine.WDT(timeout=WATCHDOG_MILLISECONDS)
        print("hw watchdog armed (%dms)" % WATCHDOG_MILLISECONDS)
    motion.clear_both()
    walk_on = False
    now = time.ticks_ms()
    last_pose_at = now
    last_received_at = now
    last_ping_at = now
    pose_count = 0
    pose_count_at_last_log = 0
    last_rate_log_at = now
    while True:
        feed()
        first_byte = None
        try:
            if poll.poll(POLL_MILLISECONDS):
                first_byte = ssl_socket.read(1)
        except OSError as error:
            print("read err:", error)
            return
        if first_byte == b"":
            print("conn closed by relay")
            return
        if first_byte:
            opcode, payload = read_frame_after_first_byte(ssl_socket, first_byte)
            if opcode is None or opcode == WEBSOCKET_OPCODE_CLOSE:
                print("conn closed by relay")
                return
            last_received_at = time.ticks_ms()
            if opcode == WEBSOCKET_OPCODE_PING:
                ssl_socket.write(WEBSOCKET_CLIENT_PONG + os.urandom(4))
            elif opcode == WEBSOCKET_OPCODE_TEXT:
                lane = handle_relay_message(ssl_socket, payload)
                if lane == LANE_POSE:
                    walk_on = True
                    last_pose_at = time.ticks_ms()
                    pose_count += 1
                    now = time.ticks_ms()
                    if time.ticks_diff(now, last_rate_log_at) >= POSE_RATE_LOG_MILLISECONDS:
                        print("poses", pose_count, "rate", pose_count - pose_count_at_last_log, "Hz")
                        pose_count_at_last_log = pose_count
                        last_rate_log_at = now
                elif lane in (LANE_ACT_LEGS, LANE_STOP):
                    walk_on = False
        else:
            now = time.ticks_ms()
            if not wlan.isconnected():
                print("wifi dropped")
                return
            if time.ticks_diff(now, last_received_at) > LINK_DEAD_MILLISECONDS:
                print("link dead: nothing heard for %ds, re-dialing" % (LINK_DEAD_MILLISECONDS // 1000))
                return
            if (time.ticks_diff(now, last_received_at) > PING_MILLISECONDS
                    and time.ticks_diff(now, last_ping_at) > PING_MILLISECONDS):
                ssl_socket.write(WEBSOCKET_CLIENT_PING + os.urandom(4))
                last_ping_at = now
        motion.tick()
        if (walk_on and not motion.legs_engine.active
                and time.ticks_diff(time.ticks_ms(), last_pose_at) > DEAD_MAN_MILLISECONDS):
            motion.quick_release_legs()
            walk_on = False
            print("dead-man: walk limp (silence)")


def main():
    sleep_fed(COLD_BOOT_SETTLE_MILLISECONDS)
    failures = 0
    while True:
        ssl_socket = raw_socket = None
        session_started_at = time.ticks_ms()
        try:
            if ensure_wifi():
                ssl_socket, raw_socket = open_relay_socket()
                if ssl_socket:
                    serve(ssl_socket, raw_socket)
                    if time.ticks_diff(time.ticks_ms(), session_started_at) > HEALTHY_SESSION_MILLISECONDS:
                        failures = 0
        except Exception as error:
            print("loop err:", error)
        for sock in (ssl_socket, raw_socket):
            try:
                if sock:
                    sock.close()
            except Exception:
                pass
        motion.clear_both()
        try:
            motion.release_all_mapped_ports()
        except Exception:
            pass
        failures += 1
        if failures >= HARD_RESET_AFTER_FAILURES:
            print("self-heal: machine.reset()")
            sleep_fed(WATCHDOG_FEED_SLICE_MILLISECONDS)
            machine.reset()
        if failures % WIFI_RESET_EVERY_FAILURES == 0:
            try:
                wifi_reset()
            except Exception as error:
                print("wifi reset err:", error)
        wait = min(
            REDIAL_BACKOFF_CAP_MILLISECONDS,
            REDIAL_BACKOFF_BASE_MILLISECONDS << min(failures, 5),
        )
        print("re-dial in %ds (fail %d)" % (wait // 1000, failures))
        sleep_fed(wait)


def boot_calibration():
    left_port = motion.port_for(CHANNEL_LEFT_LEG)
    right_port = motion.port_for(CHANNEL_RIGHT_LEG)
    board.servoWrite(left_port, SERVO_NEUTRAL_DEGREES)
    board.servoWrite(right_port, SERVO_NEUTRAL_DEGREES)
    sleep_fed(500)
    for _wave in range(2):
        board.servoWrite(right_port, 60)
        sleep_fed(220)
        board.servoWrite(right_port, 120)
        sleep_fed(220)
    board.servoWrite(right_port, SERVO_NEUTRAL_DEGREES)
    for _wave in range(2):
        board.servoWrite(left_port, 60)
        sleep_fed(220)
        board.servoWrite(left_port, 120)
        sleep_fed(220)
    board.servoWrite(left_port, SERVO_NEUTRAL_DEGREES)
    for _wave in range(2):
        board.servoWrite(left_port, 55)
        board.servoWrite(right_port, 55)
        sleep_fed(260)
        board.servoWrite(left_port, 125)
        board.servoWrite(right_port, 125)
        sleep_fed(260)
    board.servoWrite(left_port, SERVO_NEUTRAL_DEGREES)
    board.servoWrite(right_port, SERVO_NEUTRAL_DEGREES)
    sleep_fed(2000)
    board.release(left_port)
    board.release(right_port)


def is_cold_boot():
    try:
        return machine.reset_cause() != machine.WDT_RESET
    except Exception:
        return True


if is_cold_boot():
    boot_calibration()
main()
