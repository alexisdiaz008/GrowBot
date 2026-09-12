#!/usr/bin/env node
// Prove walker4 channel ownership: walk + arms may share a tick; walk + leg gesture may not.
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const body = JSON.parse(readFileSync(join(HERE, "body_truth.walker4.json"), "utf8"));
const WIRE_KEYS = { l: "leg_l", r: "leg_r", al: "arm_l", ar: "arm_r" };

function usedChannels(v) {
  if (v.v === "gesture" && Array.isArray(v.args.steps)) {
    const used = new Set();
    for (const st of v.args.steps) {
      for (const k of Object.keys(st)) {
        if (k === "ms") continue;
        used.add(WIRE_KEYS[k] || k);
      }
    }
    return [...used];
  }
  const spec = body.verbs.find(x => x.v === v.v);
  return spec?.channels || [];
}

function overlap(a, b) {
  const claimed = new Set(usedChannels(a));
  return usedChannels(b).some(c => claimed.has(c));
}

const walk = { v: "walk", args: { secs: 1 } };
const arms = { v: "arms", args: { secs: 1 } };
const gLegs = { v: "gesture", args: { steps: [{ l: 60, r: 120, ms: 400 }] } };
const gArms = { v: "gesture", args: { steps: [{ al: 50, ar: 130, ms: 400 }] } };
const rest = { v: "rest", args: {} };

const cases = [
  ["walk + arms disjoint", overlap(walk, arms), false],
  ["walk + arms-only gesture disjoint", overlap(walk, gArms), false],
  ["walk + leg gesture overlaps", overlap(walk, gLegs), true],
  ["arms + rest overlaps", overlap(arms, rest), true],
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
