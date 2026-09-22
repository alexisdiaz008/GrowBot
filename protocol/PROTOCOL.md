# GrowBot phone↔body protocol

How the phone (the brain) talks to a microcontroller (the body). The app is
**board-agnostic by design** — it only speaks this protocol over Wi-Fi. Any board
that joins Wi-Fi and answers these messages works. **The Pico 2 W is the reference
board**; its firmware is the canonical implementation.

Protocol id: **`growbot-channels-1`** (returned on `GET /stats`). One sparse pose
schema: channel id → degrees. No `l`/`r` aliases, no CSV walk stream.

- **Reference firmware:** [`robot-server.py`](../firmware/robot-server.py) (HTTP adapter) + [`motion.py`](../firmware/motion.py) + [`act_engine.py`](../firmware/act_engine.py) + [`channels.py`](../firmware/channels.py). Flash `robot-server.py` as `main.py`.
- **Conformance test:** open [`conformance.html`](conformance.html), point it at your board, get PASS/FAIL per message.

---

## ⚠️ Read this first — what is REAL vs aspirational

This doc describes **what the code actually does today**, not the someday design. Two
common assumptions are *not* implemented yet — porters should not build to them:

1. **The walk policy runs on the PHONE, not the chip.** The browser loads the learned
   gait (`growbot_policy.js` + `policy_85mm.json`), runs it at ~30 Hz against the
   **phone's** IMU, and streams the resulting leg poses to the chip as JSON over
   `WS /walk`. The chip just applies the latest pose. So today the chip does **not**
   store or run any policy.
2. **There is no `/policy` endpoint and no on-chip policy/flash storage.** Treat the
   chip-owns-the-gait design as a TODO, not the contract.

So there are really **two motion paths with two transports**:
- **Path A — gestures (HTTP):** phone POSTs a short keyframe plan to `/plans`; the chip
  glides between poses locally at 50 Hz. This is true intent-not-per-tick.
- **Path B — walk (WebSocket):** phone streams per-pose JSON to `/walk` at ~30 Hz. This
  is closer to remote-control than intent. The chip is "dumb" on this path.

Other gaps to know: **no auth/pairing** — motor endpoints are open (CORS `*`); anyone with
the URL can move the body (accepted risk for now). **No IMU or telemetry flows chip→phone**
beyond `/stats`; the IMU used for walking is the phone's. The **duty-cycle safety budget
(20 s motion / 60 s) is enforced on the phone, not in firmware**.

---

## 1. Transport

| | |
|---|---|
| **Link** | Wi-Fi. The chip joins the **home network as a station** (not an AP in normal use). |
| **Server** | Plain **HTTP/1.1 on port 80**, plus a **WebSocket** upgrade at `/walk`. Single-threaded, non-blocking poll loop (`select.poll`, 20 ms). |
| **CORS** | Every response sends `Access-Control-Allow-Origin: *`; `OPTIONS` preflight → `204`. Required because the brain is an HTTPS web page on another origin. |
| **Address the phone uses** | A public **HTTPS** URL, because the browser brain is served over HTTPS and can't fetch `http://<lan-ip>` (mixed content). |

**First-boot provisioning (reference firmware):** with no Wi-Fi credentials the Pico
becomes an open AP **`GrowBot-Setup`** serving a join form at `http://192.168.4.1`; you pick
your network there, it saves `wifi.json` and reboots onto the LAN. (Credential sources, in
order: `wifi.json` → `secrets.py` → setup AP.)

---

## 2. Pose schema

Every motion message uses the same sparse object. Omit a channel to hold it.
Unknown keys are stripped (not aliased). Degrees are absolute; `90` = neutral.

```json
{"leg_l": 70, "leg_r": 110, "milliseconds": 400}
{"arm_l": 50, "arm_r": 130, "milliseconds": 400}
```

Channel ids: `leg_l`, `leg_r`, `arm_l`, `arm_r`. Duration key: `milliseconds`
(capped at 3000 per step; queue cap 15000). Firmware clamps degrees to 0–180.

---

## 3. Message schema

### Phone → chip (HTTP)

| Endpoint | Method | Body | Returns | Meaning |
|---|---|---|---|---|
| `/plans` | POST | `{"steps":[{…pose…}], "mode":"replace"\|"append"}` | `{"ok":true,"queued_milliseconds":N}` · `409 {"error":"queue_full","queued_milliseconds":N}` · `400 {"error":…}` | **Path A.** Keyframe plan; chip glides. A step that names a leg replaces walk. Arms-only does **not** cancel walk. |
| `/pose` | PATCH | sparse degrees JSON (no `milliseconds` required) | `{"ok":true}` | Instant pose. Missing channel = do not touch that engine. Leg writes use the 500 ms dead-man. |
| `/stop` | POST | — | `{"ok":true}` | Instant: clear both engines + limp every mapped port. |
| `/routines/:name` | POST | — | `{"ok":true,"queued_milliseconds":N}` · `404` | Canned plan (`wiggle`, `dance`, `shimmy`, `march`, `bow`, `stretch`). |
| `/channels/:id` | PATCH | `{"degrees":0-180}` or `{"released":true}` | `{"ok":true}` · `404` | Calibration write / limp by channel id. |
| `/stats` | GET | `?reset` optional | JSON (below) | Telemetry + `protocol`. |
| `/walk` | WebSocket | JSON pose frames e.g. `{"leg_l":70,"leg_r":110}` | (no per-frame reply) | **Path B.** Persistent **leg** pose stream, latest-wins. ~30 Hz. Stop sending → 500 ms dead-man → legs limp. Does not clear an arms glide. Extra keys stripped; arm keys on this socket are ignored (not applied). |
| `/` | GET | — | HTML | Human control page. Not needed by the brain. |
| any | OPTIONS | — | `204` + CORS | Preflight. |

There is no `/act`, `/ws`, GET `/pose`, GET `/stop`, `/set`, `/seq`, `/routine`, or `/servo`.

### Chip → phone

There is **no streaming telemetry channel**. Replies are per-request JSON:
- Success: `{"ok": true}` and, for plans/routines, `"queued_milliseconds": N`.
- Errors as HTTP status + `{"error":"queue_full"|"no_valid_keyframes"|…, "queued_milliseconds":N}`.
- **`/stats` JSON:**
  ```json
  {"protocol":"growbot-channels-1",
   "set_n":N,"deadman":N,"walk_rx":N,"moving":bool,
   "act":{"active":bool,"queued_milliseconds":N},
   "channels":["leg_l","leg_r","arm_l","arm_r"],
   "up_s":N,"dt_ms":{"n":N,"min":N,"p50":N,"p90":N,"p99":N,"max":N}}
  ```

### Relay (same pose object)

Outbound WebSocket client on the chip. Field names are full words:

```json
{"type":"pose","leg_l":70,"leg_r":110}
{"type":"plan","request_id":"...","steps":[...],"mode":"replace"}
{"type":"routine","request_id":"...","name":"wiggle"}
{"type":"stop","request_id":"..."}
{"type":"ack","request_id":"...","ok":true,"queued_milliseconds":1100}
{"type":"hello","id":"gb-..."}
```

---

## 4. Behavior contract (what firmware MUST honor)

A conforming body has to do these — they are the hard-won rules, derived from the
reference firmware:

1. **Local 50 Hz motion.** On `POST /plans` you receive a *plan* and must play it at
   ~50 Hz with smooth easing (smoothstep), chaining appended chunks with no dead air.
   Reply **immediately** (< ~200 ms) — never block the socket for the duration of the motion.
2. **Positional servos, 90 = neutral.** Channel values are angles, not speeds. Expressive band
   `50–130`; full `0–180` allowed but wide/fast extremes can tip a small body.
   ⚠️ This rules out **360° / continuous-rotation servos**, which read the same value as a speed and
   can never hold a pose. Symptom: legs move on power-up and never stop.
3. **Orientation and the mirror rule.** Forward is the way the phone screen faces. `leg_l`/`leg_r`
   are the creature's own left and right, so facing the screen its left leg is on your right. On the
   reference body the two servos sit at opposite ends with shafts pointing outward, which makes them
   **mirror images: the same angle sent to both swings them in opposite directions.** To move both
   legs the same way, `leg_l + leg_r` must equal **180**. `{"leg_l":90,"leg_r":90}` is neutral,
   `{"leg_l":50,"leg_r":130}` sweeps both down and levers the body upright,
   `{"leg_l":130,"leg_r":50}` sweeps both up and folds it forward (both bench-calibrated). A custom
   body must honor this rule even if its servos are mounted or driven differently, by inverting one
   side in firmware. Quick self-check with no measuring: send `{"leg_l":50,"leg_r":130}` and confirm
   the body rises rather than folds.
4. **Servos on the battery rail, common ground.** Power servos from the battery, **not**
   from a logic/3V3 pin. Tie the servo ground to the board ground. (SG90/MG90 run fine on a
   raw ~4 V 1S LiPo — no 5 V boost required.)
5. **Dead-man on streamed/instant control.** `PATCH /pose` and `WS /walk` auto-limp
   legs after **500 ms** of silence. Plans hold the last pose ~300 ms, then release.
6. **Release means limp.** "Stop"/idle = cut the servo signal so the servo is limp (cool,
   quiet, low current) — not actively holding torque.
7. **Manual control wins on the channels it names.** Walk/pose clear the **legs**
   engine only. They must not clear an arms-only plan.
8. **`POST /stop` is instant + hard.** Clear both engines and limp immediately, even mid-glide.
9. **Don't run away on disconnect.** Lost link / drained queue / closed WebSocket = limp,
   not "keep doing the last thing." Add your own stall/thermal bound — the phone's 20 s/60 s
   duty budget is advisory and **not** enforced on the chip.

---

## 5. Conformance test

Run [`conformance.html`](conformance.html).

**Minimum viable body** — all must PASS:
- `GET /stats` → `200` + JSON containing `protocol` = `growbot-channels-1` and
  `act.active` / `act.queued_milliseconds`.
- `POST /plans {"steps":[{"leg_l":120,"leg_r":60,"milliseconds":400},{"leg_l":60,"leg_r":120,"milliseconds":400},{"leg_l":90,"leg_r":90,"milliseconds":300}]}`
  → `200 {"ok":true,"queued_milliseconds":1100}`, reply in < 200 ms, **legs wiggle then go limp**.
- `POST /stop` → `200 {"ok":true}`, legs limp instantly.

**Full conformance** (adds):
- `POST /plans` oversized (`6 × {milliseconds:3000}`) → `409` with `queue_full`.
- `POST /plans {"steps":"soup"}` → `400`.
- `POST /routines/wiggle` → `200` with `queued_milliseconds`.
- WebSocket `/walk` connects; sending `{"leg_l":70,"leg_r":110}` then
  `{"leg_l":90,"leg_r":90}` moves the legs; stopping the stream limps them within ~500 ms.

**Optional 4-servo block** (skip if the body has no arms):
- `POST /plans {"steps":[{"arm_l":50,"arm_r":130,"milliseconds":400}]}` → `200` and **legs stay put**.
- Then `POST /stop` → both pairs limp.

Old `"l,r"` CSV and `POST /act` are **not** accepted.

---

## 6. Per-board notes

The protocol is identical everywhere; only the firmware that implements it changes.
**Hard requirement, any board: a network path to the phone (Wi-Fi today).**

- **Raspberry Pi Pico 2 W** — the reference. MicroPython, drag-drop `.uf2` flashing.
- **ESP32** — LEDC hardware PWM + HTTP + WebSocket.
- **Carrier boards** (PCA9685 over I2C) — auto-detected by the reference `PicoRobotics.py`.
- **Raspberry Pi / Linux SBC** — use a PCA9685 or hardware-PWM pins, not software PWM.
- **Serial-bus servos** — not PWM; the reference firmware will not move them.

---

## Appendix — reference body (mechanical)

**The body is up to you — the protocol doesn't care about the shell.** For reference, the demo rig:

- **Flat base plate** (≈ phone-sized, **114 × 69 mm**) carrying the phone + battery + Pico/board
  stacked in the middle.
- **2× SG90/MG90 servos mounted at the two ends** (left & right), output shafts pointing
  **outward**.
- A flat **leg/paddle on each servo horn**. The servo **sweeps the leg through its full
  180°** (90° = upright/neutral).

Bottom line: phone + 2 side-mounted servos with a paddle on each horn, on *any* rigid base.
