# Body motion: one engine type, two instances

Convention over configuration. The public contract is the same sparse pose the engines already speak: channel id → degrees. Protocol id: `growbot-channels-1` (advertised on `GET /stats`).

## Resources

A **channel** is `id → degrees` (0–180, 90 = neutral). Shared `body_config` lists ids, limits, bands, verbs — **no pins**. Pins/ports live in firmware as `CHANNEL_PORT` / `PORT_TO_GPIO` ([`firmware/channels.py`](../firmware/channels.py) and [`firmware/PicoRobotics.py`](../firmware/PicoRobotics.py)).

| Channel id | Default port | Default GPIO |
|---|---|---|
| `leg_l` | 1 | GP0 |
| `leg_r` | 3 | GP1 |
| `arm_l` | 4 | GP2 |
| `arm_r` | 5 | GP3 |

Kitronik port 2 stays unused. Automower keeps its own `PicoRobotics.py` and is not this map.

One pose schema everywhere (HTTP plans, `PATCH /pose`, `WS /walk`, relay frames, body_config gestures). Omit a channel to hold it. Unknown keys are stripped. Duration key is `milliseconds`.

```json
{"leg_l": 70, "leg_r": 110, "milliseconds": 400}
{"arm_l": 50, "arm_r": 130, "milliseconds": 400}
```

There is no `l` / `r` / `al` / `ar` dialect and no CSV walk stream.

## Two ActEngine instances

[`firmware/act_engine.py`](../firmware/act_engine.py) plays sparse keyframes keyed by channel id. The 2-leg body uses one instance (`leg_l`,`leg_r`). A 4-servo body constructs two:

- **legs** — channels `leg_l`,`leg_r`. Walk (`WS /walk`), `PATCH /pose` legs, and a plan step that names a leg own this instance.
- **arms** — channels `arm_l`,`arm_r`. Arms-only `POST /plans` and arm keys on `PATCH /pose` own this instance.

Walk/pose **must not** `clear()` the arms engine.

`POST /plans` steps may name any subset of `{leg_l,leg_r,arm_l,arm_r}`. A step with a leg key replaces the legs engine (walk loses the legs). An arms-only step leaves walk running. `POST /stop` clears both and limp-releases every mapped port.

Dead-man (500 ms) stays on the legs walk stream. Arms plans keep hold-then-limp.

## Transport

Which file you copy as `main.py` is the transport: `robot-server.py` (LAN HTTP) or `relay_chip.py` (outbound relay). Do not infer relay from Wi-Fi secrets. Both import [`firmware/motion.py`](../firmware/motion.py) which owns two [`ActEngine`](../firmware/act_engine.py) instances.

Missing `channels.py`, `act_engine.py`, or `motion.py`: print and do not drive servos.

HTTP: `POST /plans`, `PATCH /pose`, `POST /stop`, `POST /routines/:name`, `PATCH /channels/:id`, `GET /stats`, `WS /walk`. No GET that moves motors. No `/set` / `/seq` speed dialect.

Relay frames use the same pose object and full field names (`type`, `request_id`), never `t` / `rid` / `lr`.

## Mind

- `body_config.phone.json` — no motors (unchanged).
- `body_config.walker.json` — 2-leg verbs; gesture steps use channel ids.
- `body_config.walker4.json` — adds `arm_l`/`arm_r` and an `arms` policy verb.

One tick may emit two motion verbs only if their **used channel sets are disjoint**. `walk` + arms-only `gesture` is legal; `walk` + a gesture that names `leg_l`/`leg_r` is not.

## Arm mechanics (before training)

Shoulder paddles reuse [`hardware/print/growbot_diy_leg_v1_r01.stl`](../hardware/print/growbot_diy_leg_v1_r01.stl). Mount mid-body, shafts facing **out**, same mirror rule as legs (`arm_l + arm_r = 180` for unison). Neutral 90 = arms along the body. Soft band 50–130°.

**Objective (v1):** expressive waving / counter-pose, **not** locomotion. Treat arms as non-load-bearing. Train `GrowBotArms` like `GrowBotWalker` (obs16, two tanh outputs) with randomized/replayed leg motion as disturbance. If a later print makes arms load-bearing, stop and couple the observation to leg state instead of training independently.

Hosted `growbot.dev` is out of this repo and is desynced until updated. Chip-side proof is [`protocol/conformance.html`](../protocol/conformance.html).
