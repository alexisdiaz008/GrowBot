"""Robot body HTTP adapter — Pico 2 W + Kitronik 5329.

Protocol growbot-channels-1. One sparse pose (channel id → degrees). See
docs/spec-rails.md and protocol/PROTOCOL.md.

  POST /plans              {"steps":[{leg_l,leg_r,arm_l,arm_r,milliseconds}], "mode"}
  PATCH /pose              sparse degrees JSON (instant; legs use 500 ms dead-man)
  POST /stop               clear both engines + limp mapped ports
  POST /routines/:name     canned plan (wiggle, dance, shimmy, march, bow, stretch)
  PATCH /channels/:id      {"degrees"} or {"released": true}
  GET /stats               telemetry + "protocol": "growbot-channels-1"
  WS /walk                 JSON pose frames, latest-wins, legs only, 500 ms dead-man
  GET /                    HTML control page

Hardware: left leg = port 1, right leg = port 3. PORT 2 SOCKET IS DEAD.
Requires PicoRobotics.py, channels.py, act_engine.py, and motion.py on the board.
secrets.py is OPTIONAL.

Wi-Fi — three sources, tried in order (shipped chips carry NO secrets):
  1. wifi.json on the chip   <- written by the out-of-box setup hotspot (below)
  2. secrets.py on the chip  <- dev-bench convenience (gitignored file)
  3. neither / can't join    -> SETUP MODE: the Pico becomes an open hotspot
     "GrowBot-Setup"; join it with any phone, open http://192.168.4.1, pick your
     home Wi-Fi + enter its password — the chip saves wifi.json and reboots onto
     your network. A wrong password just lands it back in setup mode.

The Anthropic key (the page's ask-Claude box) is also OPTIONAL: without it the
box is hidden and everything else works. (./finish-key-rotation.sh still
refreshes secrets.py.)

FLASHING (plug the Pico into the Mac by USB first):
  1. open Terminal, then:  cd ~/Desktop/phone-body
  2. mpremote cp channels.py act_engine.py motion.py :/
  3. mpremote cp robot-server.py :main.py    <- the firmware; runs at every power-on
  4. (dev bench only, optional) mpremote cp secrets.py :secrets.py
  5. mpremote reset                          <- reboots; prints IP, or enters setup mode
  If mpremote can't find the board, name the port explicitly, e.g.:
     mpremote connect /dev/cu.usbmodem11101 cp robot-server.py :main.py
PRE-FLASH FOR SHIPPING = steps 2+3 (+ PicoRobotics.py) only — zero secrets on the chip.
"""
import network, socket, time, json, select
from machine import Pin
try:
    from channels import (
        DEAD_MAN_MILLISECONDS,
        ENQUEUE_MODE_REPLACE,
        ERROR_BAD_PLAN_JSON,
        ERROR_QUEUE_FULL,
        ERROR_UNKNOWN_CHANNEL,
        ERROR_UNKNOWN_ROUTINE,
        JSON_ACTIVE,
        JSON_CHANNELS,
        JSON_DEGREES,
        JSON_ERROR,
        JSON_MODE,
        JSON_OK,
        JSON_PROTOCOL,
        JSON_QUEUED_MILLISECONDS,
        JSON_RELEASED,
        JSON_STEPS,
        LEG_CHANNEL_IDS,
        PROTOCOL_GROWBOT_CHANNELS_1,
        permit_pose,
    )
    from motion import BodyMotion
except ImportError:
    print("MISSING channels.py / act_engine.py / motion.py — motors disabled")
    while True:
        time.sleep(1)
import PicoRobotics

try:
    from secrets import ANTHROPIC_KEY
except Exception:
    ANTHROPIC_KEY = ""   # optional — the page hides the ask-Claude box without it
# SECURITY (external review H3, 2026-07-13): this server is served over an unauthenticated
# public tunnel, so anything substituted into the HTML is world-readable via view-source.
# We therefore NEVER embed the real key in the page — the ask-Claude box stays hidden.
# If you want on-device "ask Claude", proxy it server-side (add a /ask route that keeps the
# key on the Pico) instead of shipping the key to the browser.
SERVED_KEY = ""

def load_wifi():
    try:
        with open("wifi.json") as wifi_file:
            wifi_config = json.load(wifi_file)
        if wifi_config.get("ssid"):
            return wifi_config["ssid"], wifi_config.get("password", "")
    except Exception:
        pass
    try:
        import secrets
        return secrets.WIFI_SSID, secrets.WIFI_PASSWORD
    except Exception:
        return None, None

def unquote_form(encoded):
    encoded = encoded.replace("+", " ")
    out = ""
    index = 0
    while index < len(encoded):
        if encoded[index] == "%" and index + 3 <= len(encoded):
            try:
                out += chr(int(encoded[index + 1:index + 3], 16))
                index += 3
                continue
            except ValueError:
                pass
        out += encoded[index]
        index += 1
    return out

PATH_ROOT = "/"
PATH_POSE = "/pose"
PATH_STOP = "/stop"
PATH_STATS = "/stats"
PATH_PLANS = "/plans"
PATH_WALK = "/walk"
PATH_ROUTINES_PREFIX = "/routines/"
PATH_CHANNELS_PREFIX = "/channels/"

HTTP_STATUS_OK = "200 OK"
HTTP_STATUS_NO_CONTENT = "204 No Content"
HTTP_STATUS_BAD_REQUEST = "400 Bad Request"
HTTP_STATUS_NOT_FOUND = "404 Not Found"
HTTP_STATUS_CONFLICT = "409 Conflict"
HTTP_STATUS_NOT_IMPLEMENTED = "501 Not Implemented"
HTTP_STATUS_SWITCHING_PROTOCOLS = "101 Switching Protocols"

CONTENT_TYPE_TEXT = "text/plain"
CONTENT_TYPE_JSON = "application/json"
CONTENT_TYPE_HTML = "text/html"

METHOD_GET = "GET"
METHOD_POST = "POST"
METHOD_PATCH = "PATCH"
METHOD_OPTIONS = "OPTIONS"

HANDLE_RESULT_STREAM = "stream"
HANDLE_RESULT_STOP = "stop"
HANDLE_RESULT_WEBSOCKET = "ws"

QUERY_STATS_RESET = "reset"

ARRIVAL_DELTA_RING_SIZE = 120
LOG_EVERY_N_MANUAL_COMMANDS = 50
SERVO_PWM_PERIOD_MILLISECONDS = 20
WIFI_POWER_MANAGEMENT_NO_POWERSAVE = 0xa11140

board = PicoRobotics.KitronikPicoRobotics()
led = Pin("LED", Pin.OUT)
motion = BodyMotion(
    board, PicoRobotics.CHANNEL_PORT,
    time.ticks_ms, time.ticks_diff,
    led=led, sleep_milliseconds=time.sleep_ms,
)

state = {
    "legs_stream_active": False,
    "last_stream_at": 0,
    "last_arrival_at": None,
    "stream_count": 0,
    "deadman_count": 0,
}
arrival_deltas_milliseconds = []


def mark_arrival():
    now = time.ticks_ms()
    if state["last_arrival_at"] is not None:
        delta = time.ticks_diff(now, state["last_arrival_at"])
        arrival_deltas_milliseconds.append(delta)
        if len(arrival_deltas_milliseconds) > ARRIVAL_DELTA_RING_SIZE:
            arrival_deltas_milliseconds.pop(0)
    state["last_arrival_at"] = now
    state["last_stream_at"] = now
    state["stream_count"] += 1


def apply_sparse_pose_from_client(pose, legs_only=False):
    """Apply a sparse pose. Walk strips arms. Returns whether legs moved."""
    permitted = permit_pose(pose) or {}
    if legs_only:
        walk_pose = {}
        for channel_id in LEG_CHANNEL_IDS:
            if channel_id in permitted:
                walk_pose[channel_id] = permitted[channel_id]
        permitted = walk_pose
    if not permitted:
        return False
    mark_arrival()
    touched_legs, _touched_arms = motion.apply_sparse_pose(permitted)
    if touched_legs:
        state["legs_stream_active"] = True
    if state["stream_count"] % LOG_EVERY_N_MANUAL_COMMANDS == 0:
        last_delta = arrival_deltas_milliseconds[-1] if arrival_deltas_milliseconds else "?"
        print("pose#%d %s dt=%sms" % (state["stream_count"], permitted, last_delta))
    return touched_legs


def stats_json(reset):
    deltas = sorted(arrival_deltas_milliseconds)

    def percentile(fraction):
        if not deltas:
            return None
        index = min(len(deltas) - 1, int(fraction * (len(deltas) - 1) + 0.5))
        return deltas[index]

    out = json.dumps({
        JSON_PROTOCOL: PROTOCOL_GROWBOT_CHANNELS_1,
        "set_n": state["stream_count"],
        "deadman": state["deadman_count"],
        "walk_rx": websocket_state["frames_received"],
        "moving": state["legs_stream_active"],
        "act": {
            JSON_ACTIVE: motion.any_engine_active(),
            JSON_QUEUED_MILLISECONDS: motion.queued_milliseconds(),
        },
        JSON_CHANNELS: motion.loaded_channel_ids(),
        "up_s": time.ticks_diff(time.ticks_ms(), UP0) // 1000,
        "dt_ms": {
            "n": len(deltas),
            "min": deltas[0] if deltas else None,
            "p50": percentile(0.5),
            "p90": percentile(0.9),
            "p99": percentile(0.99),
            "max": deltas[-1] if deltas else None,
        },
    })
    if reset:
        del arrival_deltas_milliseconds[:]
        state["stream_count"] = 0
        state["last_arrival_at"] = None
        state["deadman_count"] = 0
    return out


motion.release_all_mapped_ports()

# ---------- Wi-Fi (ladder: wifi.json -> secrets.py -> setup hotspot) ----------
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.config(pm=WIFI_POWER_MANAGEMENT_NO_POWERSAVE)

SETUP_PAGE = ("<!DOCTYPE html><html><head><meta charset=utf-8><meta name=viewport "
  'content="width=device-width,initial-scale=1"><title>GrowBot setup</title><style>'
  "body{font-family:system-ui;background:#070a12;color:#e8f0fb;display:flex;flex-direction:column;"
  "align-items:center;gap:14px;padding:40px 24px}input,select,button{font-size:17px;padding:12px;"
  "box-sizing:border-box;border-radius:10px;border:1px solid #31466b;background:#101826;color:#e8f0fb;"
  "width:100%%;max-width:340px}button{background:#2bbfa8;color:#04110f;font-weight:700;border:0}"
  "p{color:#8fa3bb;font-size:13px;max-width:340px;text-align:center}</style></head><body>"
  "<h2>hi! tell me your wifi</h2><form method=POST action=/save>%s"
  '<input name=ssid2 placeholder="network name (if not in the list)">'
  '<input name=pw type=password placeholder="wifi password">'
  "<button>save &amp; wake my body</button></form>"
  "<p>I will reboot onto your wifi. The light blinks while I join; the creature page "
  "finds me from there.</p></body></html>")

def setup_mode():
    """No usable Wi-Fi: become the GrowBot-Setup hotspot and serve a join form at
    http://192.168.4.1 — the pre-flashed out-of-box path. Reboots after saving."""
    nets = []
    try:
        nets = sorted(set(n[0].decode() for n in wlan.scan() if n[0]), key=lambda s: s.lower())[:12]
    except Exception:
        pass
    wlan.active(False)
    ap = network.WLAN(network.AP_IF)
    try:
        ap.config(essid="GrowBot-Setup", security=0)   # open network
    except Exception:
        ap.config(essid="GrowBot-Setup")               # older ports: default is open
    ap.active(True)
    print("\n  SETUP MODE: join the 'GrowBot-Setup' wifi, then open http://192.168.4.1\n")
    opts = ""
    if nets:
        opts = ("<select name=ssid><option value=''>choose your network...</option>"
                + "".join("<option>%s</option>" % n for n in nets) + "</select>")
    page = SETUP_PAGE % opts
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(socket.getaddrinfo("0.0.0.0", 80)[0][-1])
    srv.listen(2)
    srv.settimeout(0.5)        # so the LED blinks while waiting = "I'm in setup mode"
    while True:
        led.toggle()
        try:
            cl, _ = srv.accept()
        except OSError:
            continue
        try:
            cl.settimeout(3)
            req = cl.recv(2048)
            while req and b"\r\n\r\n" not in req and len(req) < 8192:
                more = cl.recv(512)
                if not more: break
                req += more
            head, _, body = req.partition(b"\r\n\r\n")
            if head.split(b"\r\n")[0].startswith(b"POST /save"):
                clen = 0
                for h in head.split(b"\r\n"):
                    if h.lower().startswith(b"content-length"):
                        clen = int(h.split(b":")[1])
                while len(body) < clen:
                    more = cl.recv(512)
                    if not more: break
                    body += more
                form = {}
                for kv in body.decode().split("&"):
                    k, _, v = kv.partition("=")
                    form[k] = unquote_form(v)
                ssid = (form.get("ssid") or form.get("ssid2") or "").strip()
                if ssid:
                    with open("wifi.json", "w") as f:
                        json.dump({"ssid": ssid, "password": form.get("pw", "")}, f)
                    cl.send(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n"
                            b"<body style='font-family:system-ui;background:#070a12;color:#e8f0fb;"
                            b"text-align:center;padding-top:80px'><h2>got it &mdash; waking up on your wifi...</h2>"
                            b"<p>rejoin your normal wifi; I'll be there in ~15 seconds.</p></body>")
                    try: cl.close()
                    except Exception: pass
                    time.sleep(1)
                    import machine
                    machine.reset()
            cl.send(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nConnection: close\r\n\r\n")
            cl.send(page)
        except Exception as e:
            print("setup req error:", e)
        finally:
            try: cl.close()
            except Exception: pass

SSID, PASSWORD = load_wifi()
joined = False
if SSID:
    wlan.connect(SSID, PASSWORD)
    print("connecting to", SSID, "...")
    for _ in range(40):
        if wlan.isconnected():
            joined = True
            break
        time.sleep(0.5)
if not joined:
    setup_mode()                      # never returns (reboots after save)
IP = wlan.ifconfig()[0]
print("\n  ROBOT SERVER growbot-channels-1:  http://%s/\n" % IP)

# ---------- the page ----------
PAGE = """<!DOCTYPE html><html><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>robot legs</title><style>
body{margin:0;min-height:100vh;background:#05070d;color:#e8f6ff;font-family:system-ui;
display:flex;flex-direction:column;align-items:center;gap:14px;padding:22px;box-sizing:border-box}
h1{font-size:16px;color:#7f93ab;margin:2px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px;width:100%;max-width:420px}
button{font-size:17px;padding:16px;border-radius:14px;border:0;font-weight:700;
background:#0e1622;color:#e8f6ff;border:1px solid rgba(120,160,200,.25)}
#stop{background:#8c1d2f;grid-column:1/3;font-size:20px}
textarea{width:100%;max-width:420px;box-sizing:border-box;background:#0e1622;color:#e8f6ff;
border:1px solid rgba(120,160,200,.25);border-radius:14px;padding:12px;font-size:16px;min-height:64px}
#ask{background:linear-gradient(160deg,#37e0c8,#5ab0ff);color:#04110f;width:100%;max-width:420px}
#mic{background:#1d2a3d;width:100%;max-width:420px}
#st{color:#7f93ab;font-size:14px;min-height:1.2em;text-align:center}
#say{color:#37e0c8;font-size:15px;min-height:1.2em;text-align:center;max-width:420px}
</style></head><body>
<h1>robot legs &middot; growbot-channels-1</h1>
<div class=grid>
<button id=stop onclick="post('/stop')">STOP</button>
<button onclick="post('/routines/wiggle')">wiggle</button>
<button onclick="post('/routines/dance')">dance</button>
<button onclick="post('/routines/shimmy')">shimmy</button>
<button onclick="post('/routines/march')">march</button>
<button onclick="post('/routines/bow')">bow</button>
<button onclick="post('/routines/stretch')">stretch</button>
</div>
<textarea id=q placeholder="type here - or tap this box and use the keyboard mic to dictate, then hit ask"></textarea>
<button id=mic onclick="mic()">&#127908; tap to talk</button>
<button id=ask onclick="ask()">ask Claude to move the legs</button>
<div id=say></div>
<div id=st>ready</div>
<script>
var st=document.getElementById('st'),say=document.getElementById('say'),q=document.getElementById('q');
var KEY='%KEY%';
if(!KEY){ q.style.display='none'; document.getElementById('mic').style.display='none';
 document.getElementById('ask').style.display='none'; }
function post(p){st.textContent='moving...';
 fetch(p,{method:'POST'}).then(function(r){return r.json();}).then(function(d){
  st.textContent=d.ok?(d.queued_milliseconds!=null?('queued '+d.queued_milliseconds+'ms'):'ok'):(d.error||'ok');
 }).catch(function(){st.textContent='! no link to robot';});}
var SYS='You choreograph a small 2-leg desk robot. Each leg is a positional servo with the FULL '+
'0-180 range (90 = straight-down neutral stance; 0 and 180 are the extreme fore/aft swings). '+
'You write animation KEYFRAMES: the body glides smoothly from pose to pose, each keyframe taking '+
'milliseconds to arrive. Repeat a pose to hold it (a rest). Reply with ONLY raw JSON, no fences: '+
'{"say":"<one short fun sentence>","steps":[{"leg_l":<0-180>,"leg_r":<0-180>,"milliseconds":<120..2000>}]} '+
'Use the whole range for big expressive moves; just know wide stances '+
'or fast extremes can tip a small desk robot, so land back near 90 to settle. Max 24 keyframes, '+
'total under 12000 milliseconds. Be expressive: deep bows, high marches, asymmetric struts, dramatic pauses.';
function ask(){
 var text=q.value.trim(); if(!text){st.textContent='type something first';return;}
 st.textContent='asking Claude...'; say.textContent='';
 fetch('https://api.anthropic.com/v1/messages',{method:'POST',headers:{
  'content-type':'application/json','x-api-key':'%KEY%',
  'anthropic-version':'2023-06-01','anthropic-dangerous-direct-browser-access':'true'},
  body:JSON.stringify({model:'claude-opus-4-8',max_tokens:2000,
   output_config:{effort:'low'},system:SYS,messages:[{role:'user',content:text}]})})
 .then(function(r){return r.json();})
 .then(function(d){
  if(d.error){st.textContent='Claude error: '+d.error.message;return;}
  var txt=''; (d.content||[]).forEach(function(b){if(b.type==='text')txt+=b.text;});
  txt=txt.replace(/```json|```/g,'').trim();
  var plan=JSON.parse(txt);
  say.textContent='Claude: '+(plan.say||'');
  st.textContent='Claude sent '+plan.steps.length+' keyframes - playing...';
  return fetch('/plans',{method:'POST',headers:{'content-type':'application/json'},
   body:JSON.stringify({steps:plan.steps,mode:'replace'})})
   .then(function(r){return r.json();})
   .then(function(d2){st.textContent=d2.ok?('playing '+d2.queued_milliseconds+'ms of motion'):('! '+d2.error);});})
 .catch(function(e){st.textContent='! '+e.message;});}
var SR=window.SpeechRecognition||window.webkitSpeechRecognition,rec=null,micb=document.getElementById('mic');
function mic(){
 if(!SR||!window.isSecureContext){
  st.textContent='browser mic needs https - tap the text box and use the keyboard mic key instead';
  q.focus();return;}
 if(rec){rec.stop();return;}
 rec=new SR();rec.lang='en-US';rec.interimResults=true;
 micb.textContent='listening... (tap to stop)';st.textContent='speak now';
 rec.onresult=function(e){var t='';for(var i=0;i<e.results.length;i++)t+=e.results[i][0].transcript;q.value=t;};
 rec.onerror=function(e){st.textContent='mic error: '+e.error;};
 rec.onend=function(){micb.textContent='\\ud83c\\udfa4 tap to talk';rec=null;if(q.value.trim())ask();};
 rec.start();}
</script></body></html>""".replace("%KEY%", SERVED_KEY)

# ---------- WebSocket (persistent /walk pose stream) ----------
try:
    import hashlib, binascii
    WEBSOCKET_AVAILABLE = hasattr(hashlib, "sha1")
except ImportError:
    WEBSOCKET_AVAILABLE = False
WEBSOCKET_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
WEBSOCKET_OPCODE_CLOSE = 8
WEBSOCKET_OPCODE_PING = 9
WEBSOCKET_OPCODE_PONG = 10
WEBSOCKET_OPCODE_TEXT = 1
WEBSOCKET_OPCODE_BINARY = 2
WEBSOCKET_BUFFER_LIMIT = 4096
WEBSOCKET_RECV_CHUNK = 512
HTTP_RECV_CHUNK = 512
HTTP_RECV_INITIAL = 2048
HTTP_RECV_MAX = 8192
WEBSOCKET_LENGTH_16BIT = 126
WEBSOCKET_LENGTH_64BIT = 127

websocket_state = {"socket": None, "buffer": b"", "frames_received": 0}

def websocket_frame(opcode, payload=b""):
    length = len(payload)
    if length < WEBSOCKET_LENGTH_16BIT:
        return bytes([0x80 | opcode, length]) + payload
    return bytes([0x80 | opcode, WEBSOCKET_LENGTH_16BIT, length >> 8, length & 0xFF]) + payload

def websocket_pop_frame():
    buffer = websocket_state["buffer"]
    if len(buffer) < 2:
        return None
    opcode = buffer[0] & 0x0F
    masked = buffer[1] & 0x80
    length = buffer[1] & 0x7F
    header_end = 2
    if length == WEBSOCKET_LENGTH_16BIT:
        if len(buffer) < 4:
            return None
        length = (buffer[2] << 8) | buffer[3]
        header_end = 4
    elif length == WEBSOCKET_LENGTH_64BIT:
        websocket_state["buffer"] = b""
        return None
    mask = None
    if masked:
        if len(buffer) < header_end + 4:
            return None
        mask = buffer[header_end:header_end + 4]
        header_end += 4
    if len(buffer) < header_end + length:
        return None
    payload = bytearray(buffer[header_end:header_end + length])
    if mask:
        for index in range(length):
            payload[index] ^= mask[index & 3]
    websocket_state["buffer"] = buffer[header_end + length:]
    return opcode, bytes(payload)

def websocket_close(reason=""):
    sock = websocket_state["socket"]
    if not sock:
        return
    try:
        poller.unregister(sock)
    except Exception:
        pass
    try:
        sock.close()
    except Exception:
        pass
    websocket_state["socket"] = None
    websocket_state["buffer"] = b""
    if state["legs_stream_active"]:
        motion.quick_release_legs()
        state["legs_stream_active"] = False
    print("ws closed:", reason)

def websocket_service():
    """Drain all pending frames, apply ONLY the newest pose (latest-wins)."""
    sock = websocket_state["socket"]
    try:
        while True:
            data = sock.recv(WEBSOCKET_RECV_CHUNK)
            if data == b"":
                websocket_close("peer gone")
                return
            websocket_state["buffer"] += data
            if len(data) < WEBSOCKET_RECV_CHUNK:
                break
    except OSError:
        pass
    if len(websocket_state["buffer"]) > WEBSOCKET_BUFFER_LIMIT:
        websocket_close("buffer overflow")
        return
    latest = None
    while True:
        frame = websocket_pop_frame()
        if frame is None:
            break
        opcode, payload = frame
        if opcode == WEBSOCKET_OPCODE_CLOSE:
            try:
                sock.send(websocket_frame(WEBSOCKET_OPCODE_CLOSE))
            except OSError:
                pass
            websocket_close("client close")
            return
        if opcode == WEBSOCKET_OPCODE_PING:
            try:
                sock.send(websocket_frame(WEBSOCKET_OPCODE_PONG, payload))
            except OSError:
                pass
        elif opcode in (WEBSOCKET_OPCODE_TEXT, WEBSOCKET_OPCODE_BINARY):
            latest = payload
            websocket_state["frames_received"] += 1
    if latest is not None:
        try:
            pose = json.loads(latest.decode())
            if isinstance(pose, dict):
                apply_sparse_pose_from_client(pose, legs_only=True)
        except (ValueError, TypeError):
            pass

CORS_HEADER = "Access-Control-Allow-Origin: *\r\n"
ERROR_NOT_WEBSOCKET = "not a websocket upgrade"
ERROR_NO_SHA1 = "no sha1 in this firmware build"
ERROR_NOT_FOUND = "not_found"
POLL_MILLISECONDS = SERVO_PWM_PERIOD_MILLISECONDS
HTTP_LISTEN_BACKLOG = 4
HTTP_PORT = 80
BIND_ALL_INTERFACES = "0.0.0.0"


def send_all(client, data):
    if isinstance(data, str):
        data = data.encode()
    while data:
        sent = client.send(data)
        data = data[sent:]


def reply(client, status, body_text, content_type=CONTENT_TYPE_JSON):
    send_all(client, "HTTP/1.1 %s\r\n%sContent-Type: %s\r\nConnection: close\r\n\r\n"
             % (status, CORS_HEADER, content_type))
    send_all(client, body_text)


def ok_body(queued_milliseconds=None):
    payload = {JSON_OK: True}
    if queued_milliseconds is not None:
        payload[JSON_QUEUED_MILLISECONDS] = queued_milliseconds
    return json.dumps(payload)


def error_body(error, queued_milliseconds=None):
    payload = {JSON_ERROR: error}
    if queued_milliseconds is not None:
        payload[JSON_QUEUED_MILLISECONDS] = queued_milliseconds
    return json.dumps(payload)


def parse_json_object(body):
    try:
        parsed = json.loads(body)
    except Exception:
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def read_request(client, timeout=0.5):
    client.settimeout(timeout)
    request = client.recv(HTTP_RECV_INITIAL)
    if not request:
        return None
    while b"\r\n\r\n" not in request and len(request) < HTTP_RECV_MAX:
        more = client.recv(HTTP_RECV_CHUNK)
        if not more:
            break
        request += more
    head, _, body = request.partition(b"\r\n\r\n")
    first = head.split(b"\r\n")[0].split(b" ")
    method = first[0].decode() if first else METHOD_GET
    full = first[1].decode() if len(first) > 1 else PATH_ROOT
    path, _, query = full.partition("?")
    content_length = 0
    for header_line in head.split(b"\r\n"):
        if header_line.lower().startswith(b"content-length"):
            content_length = int(header_line.split(b":")[1])
    while len(body) < content_length:
        more = client.recv(HTTP_RECV_CHUNK)
        if not more:
            break
        body += more
    return method, path, query, body, head


def reply_plan_result(client, succeeded, result, used_legs, mode):
    if used_legs:
        state["legs_stream_active"] = False
    if succeeded:
        print("plan: queued %dms (%s)" % (result, mode))
        reply(client, HTTP_STATUS_OK, ok_body(result))
        return
    queued_left = motion.queued_milliseconds()
    status = HTTP_STATUS_CONFLICT if result == ERROR_QUEUE_FULL else HTTP_STATUS_BAD_REQUEST
    reply(client, status, error_body(result, queued_left))


def handle(client):
    """Serve one request. Nothing here blocks on motion."""
    parsed = read_request(client)
    if not parsed:
        return None
    method, path, query, body, head = parsed

    if method == METHOD_OPTIONS:
        send_all(client, "HTTP/1.1 %s\r\n" % HTTP_STATUS_NO_CONTENT + CORS_HEADER +
                 "Access-Control-Allow-Methods: GET, POST, PATCH, OPTIONS\r\n"
                 "Access-Control-Allow-Headers: content-type\r\n"
                 "Access-Control-Max-Age: 86400\r\nConnection: close\r\n\r\n")
        return None

    if path == PATH_PLANS and method == METHOD_POST:
        plan = parse_json_object(body)
        if plan is None:
            reply(client, HTTP_STATUS_BAD_REQUEST, error_body(ERROR_BAD_PLAN_JSON))
            return None
        steps = plan.get(JSON_STEPS, [])
        mode = plan.get(JSON_MODE, ENQUEUE_MODE_REPLACE)
        if not isinstance(steps, list):
            reply(client, HTTP_STATUS_BAD_REQUEST, error_body(ERROR_BAD_PLAN_JSON))
            return None
        succeeded, result, used_legs = motion.enqueue_steps(steps, mode)
        reply_plan_result(client, succeeded, result, used_legs, mode)
        return None

    if path == PATH_POSE and method == METHOD_PATCH:
        pose = parse_json_object(body)
        if pose is None:
            reply(client, HTTP_STATUS_BAD_REQUEST, error_body(ERROR_BAD_PLAN_JSON))
            return None
        apply_sparse_pose_from_client(pose, legs_only=False)
        reply(client, HTTP_STATUS_OK, ok_body())
        return HANDLE_RESULT_STREAM

    if path == PATH_STOP and method == METHOD_POST:
        motion.stop()
        state["legs_stream_active"] = False
        reply(client, HTTP_STATUS_OK, ok_body())
        return HANDLE_RESULT_STOP

    if path == PATH_STATS and method == METHOD_GET:
        reply(client, HTTP_STATUS_OK, stats_json(QUERY_STATS_RESET in query))
        return None

    if path == PATH_WALK:
        if not WEBSOCKET_AVAILABLE:
            reply(client, HTTP_STATUS_NOT_IMPLEMENTED, error_body(ERROR_NO_SHA1))
            return None
        key = None
        for line in head.split(b"\r\n"):
            if line.lower().startswith(b"sec-websocket-key"):
                key = line.split(b":", 1)[1].strip()
        if not key:
            reply(client, HTTP_STATUS_BAD_REQUEST, error_body(ERROR_NOT_WEBSOCKET))
            return None
        accept = binascii.b2a_base64(hashlib.sha1(key + WEBSOCKET_GUID).digest()).strip()
        send_all(client, "HTTP/1.1 %s\r\nUpgrade: websocket\r\n"
                 "Connection: Upgrade\r\nSec-WebSocket-Accept: %s\r\n\r\n"
                 % (HTTP_STATUS_SWITCHING_PROTOCOLS, accept.decode()))
        websocket_close("replaced by new client")
        client.setblocking(False)
        websocket_state["socket"] = client
        websocket_state["buffer"] = b""
        poller.register(client, select.POLLIN)
        print("walk connected")
        return HANDLE_RESULT_WEBSOCKET

    if path == PATH_ROOT and method == METHOD_GET:
        send_all(client, "HTTP/1.1 %s\r\nContent-Type: %s\r\nConnection: close\r\n\r\n"
                 % (HTTP_STATUS_OK, CONTENT_TYPE_HTML))
        send_all(client, PAGE)
        return None

    if path.startswith(PATH_ROUTINES_PREFIX) and method == METHOD_POST:
        name = path[len(PATH_ROUTINES_PREFIX):]
        if not name or "/" in name:
            reply(client, HTTP_STATUS_NOT_FOUND, error_body(ERROR_UNKNOWN_ROUTINE))
            return None
        succeeded, result, used_legs = motion.enqueue_routine(name)
        if succeeded:
            reply_plan_result(client, True, result, used_legs, name)
        else:
            reply(client, HTTP_STATUS_NOT_FOUND, error_body(ERROR_UNKNOWN_ROUTINE))
        return None

    if path.startswith(PATH_CHANNELS_PREFIX) and method == METHOD_PATCH:
        channel_id = path[len(PATH_CHANNELS_PREFIX):]
        if not channel_id or "/" in channel_id or not motion.knows_channel(channel_id):
            reply(client, HTTP_STATUS_NOT_FOUND, error_body(ERROR_UNKNOWN_CHANNEL))
            return None
        payload = parse_json_object(body)
        if payload is None:
            reply(client, HTTP_STATUS_BAD_REQUEST, error_body(ERROR_BAD_PLAN_JSON))
            return None
        if payload.get(JSON_RELEASED):
            motion.release_channels((channel_id,), turn_led_off=False)
            reply(client, HTTP_STATUS_OK, ok_body())
            return None
        if JSON_DEGREES not in payload:
            reply(client, HTTP_STATUS_BAD_REQUEST, error_body(ERROR_BAD_PLAN_JSON))
            return None
        motion.write_channel_degrees(channel_id, payload[JSON_DEGREES])
        reply(client, HTTP_STATUS_OK, ok_body())
        return None

    reply(client, HTTP_STATUS_NOT_FOUND, error_body(ERROR_NOT_FOUND))
    return None

server_socket = socket.socket()
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server_socket.bind(socket.getaddrinfo(BIND_ALL_INTERFACES, HTTP_PORT)[0][-1])
server_socket.listen(HTTP_LISTEN_BACKLOG)
server_socket.settimeout(0)
poller = select.poll()
poller.register(server_socket, select.POLLIN)
UP0 = time.ticks_ms()
print("ready - growbot-channels-1: POST /plans PATCH /pose POST /stop WS /walk GET /stats")

while True:
    motion.tick()
    if state["legs_stream_active"] and \
       time.ticks_diff(time.ticks_ms(), state["last_stream_at"]) > DEAD_MAN_MILLISECONDS:
        motion.quick_release_legs()
        state["legs_stream_active"] = False
        state["deadman_count"] += 1
        print("dead-man stop (#%d)" % state["deadman_count"])
    try:
        events = poller.poll(POLL_MILLISECONDS)
    except OSError:
        continue
    for obj, event_flags in events:
        if obj is server_socket:
            try:
                client, _address = server_socket.accept()
            except OSError:
                continue
            handle_result = None
            try:
                handle_result = handle(client)
            except Exception as error:
                print("request error:", error)
                try:
                    if not state["legs_stream_active"] and not motion.any_engine_active():
                        motion.release_all_mapped_ports()
                except Exception:
                    pass
            finally:
                if handle_result != HANDLE_RESULT_WEBSOCKET:
                    try:
                        client.close()
                    except Exception:
                        pass
        elif websocket_state["socket"] is not None and obj is websocket_state["socket"]:
            if event_flags & (select.POLLERR | select.POLLHUP):
                websocket_close("socket error")
            else:
                try:
                    websocket_service()
                except Exception as error:
                    print("ws error:", error)
                    websocket_close("exception")
        else:
            try:
                poller.unregister(obj)
            except Exception:
                pass
