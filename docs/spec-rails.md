# Body motion: one engine type, two instances

Convention over configuration for GrowBot firmware. No new wire format. Walk stays `"l,r"`. Extra channels use the existing `/act` JSON keys.

## Resources

A **channel** is `id → degrees` (0–180, 90 = neutral). Shared `body_truth` lists ids, limits, bands, verbs — **no pins**. Pins/ports live in firmware next to `GPIO_PINS` / `PORT_GP`.

| Wire key | Channel id | Default port | Default GPIO |
|---|---|---|---|
| `l` | `leg_l` | 1 | GP0 |
| `r` | `leg_r` | 3 | GP1 |
| `al` | `arm_l` | 4 | GP2 |
| `ar` | `arm_r` | 5 | GP3 |

Kitronik port 2 stays unused. Automower keeps its own `PicoRobotics.py` and is not this map.

Aliases exist only at the HTTP/relay edge. `/ws` and relay `{"t":"pose","lr":"L,R"}` stay **two numbers**. Never send a 4-value CSV (legacy chips fail to parse it).

## Two ActEngine instances

[`firmware/act_engine.py`](../firmware/act_engine.py) plays sparse keyframes. The 2-leg body uses one instance (`l`,`r`). A 4-servo body constructs two:

- **legs** — channels `l`,`r`. Walk, `/pose` legs, `/ws`, `/set` own this instance.
- **arms** — channels `al`,`ar`. Arms-only `/act` and `/pose?al=&ar=` own this instance.

Walk/pose/ws **must not** `clear()` the arms engine.

`/act` steps may name any subset of `{l,r,al,ar}`. A step with a leg key replaces the legs engine (walk loses the legs, same as today). An arms-only step leaves walk running. `/stop` clears both and limp-releases every mapped port.

Dead-man (500 ms) stays on the legs stream. Arms `/act` keeps hold-then-limp.

## Transport

Which file you copy as `main.py` is the transport: `robot-server.py` (LAN HTTP) or `relay_chip.py` (outbound relay). Do not infer relay from Wi-Fi secrets.

Missing `act_engine.py`: print and do not drive servos.

## Mind

- `body_truth.phone.json` — no motors (unchanged).
- `body_truth.walker.json` — 2-leg verbs.
- `body_truth.walker4.json` — adds `arm_l`/`arm_r` and an `arms` policy verb.

One tick may emit two motion verbs only if their **used channel sets are disjoint**. `walk` + arms-only `gesture` is legal; `walk` + a gesture that names `l`/`r` is not.

## Arm mechanics (before training)

Shoulder paddles reuse [`hardware/print/growbot_diy_leg_v1_r01.stl`](../hardware/print/growbot_diy_leg_v1_r01.stl). Mount mid-body, shafts facing **out**, same mirror rule as legs (`al + ar = 180` for unison). Neutral 90 = arms along the body. Soft band 50–130°.

**Objective (v1):** expressive waving / counter-pose, **not** locomotion. Treat arms as non-load-bearing. Train `GrowBotArms` like `GrowBotWalker` (obs16, two tanh outputs) with randomized/replayed leg motion as disturbance. If a later print makes arms load-bearing, stop and couple the observation to leg state instead of training independently.

Hosted `growbot.dev` is out of this repo. Chip-side proof is [`protocol/conformance.html`](../protocol/conformance.html).
