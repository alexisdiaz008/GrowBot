#!/usr/bin/env node
// Prove walker4 channel ownership: walk + arms may share a tick; walk + leg gesture may not.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  VERB_GESTURE,
  VERB_NAME_FIELD,
  WIRE_LEFT_ARM,
  WIRE_LEFT_LEG,
  WIRE_RIGHT_ARM,
  WIRE_RIGHT_LEG,
  KEYFRAME_MILLISECONDS_KEY,
  channelSetsOverlap,
} from "./channels.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const body = JSON.parse(readFileSync(join(HERE, "body_config.walker4.json"), "utf8"));

const VERB_WALK = "walk";
const VERB_ARMS = "arms";
const VERB_REST = "rest";

const walk = { [VERB_NAME_FIELD]: VERB_WALK, args: { secs: 1 } };
const arms = { [VERB_NAME_FIELD]: VERB_ARMS, args: { secs: 1 } };
const gestureLegs = {
  [VERB_NAME_FIELD]: VERB_GESTURE,
  args: { steps: [{ [WIRE_LEFT_LEG]: 60, [WIRE_RIGHT_LEG]: 120, [KEYFRAME_MILLISECONDS_KEY]: 400 }] },
};
const gestureArms = {
  [VERB_NAME_FIELD]: VERB_GESTURE,
  args: { steps: [{ [WIRE_LEFT_ARM]: 50, [WIRE_RIGHT_ARM]: 130, [KEYFRAME_MILLISECONDS_KEY]: 400 }] },
};
const rest = { [VERB_NAME_FIELD]: VERB_REST, args: {} };

const cases = [
  ["walk + arms disjoint", channelSetsOverlap(walk, arms, body), false],
  ["walk + arms-only gesture disjoint", channelSetsOverlap(walk, gestureArms, body), false],
  ["walk + leg gesture overlaps", channelSetsOverlap(walk, gestureLegs, body), true],
  ["arms + rest overlaps", channelSetsOverlap(arms, rest, body), true],
];

let failed = 0;
for (const [name, got, want] of cases) {
  if (got !== want) {
    console.error("FAIL", name, "got", got, "want", want);
    failed++;
  } else {
    console.log("ok", name);
  }
}
if (body.limits.max_motion_verbs_per_tick !== 2) {
  console.error("FAIL walker4 max_motion_verbs_per_tick");
  failed++;
} else {
  console.log("ok walker4 motion budget is 2");
}
if (failed) process.exit(1);
console.log("disjoint checks passed");
