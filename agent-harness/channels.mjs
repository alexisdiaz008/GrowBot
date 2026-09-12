/** Channel ids and wire aliases — shared by the reference loop and tests.
 *
 * Engines and body_config `channels[].id` speak channel ids.
 * Gesture JSON still uses wire aliases (l/r/al/ar) because that is the
 * public protocol; we translate at this edge. See docs/spec-rails.md.
 */

export const CHANNEL_LEFT_LEG = "leg_l";
export const CHANNEL_RIGHT_LEG = "leg_r";
export const CHANNEL_LEFT_ARM = "arm_l";
export const CHANNEL_RIGHT_ARM = "arm_r";

export const WIRE_LEFT_LEG = "l";
export const WIRE_RIGHT_LEG = "r";
export const WIRE_LEFT_ARM = "al";
export const WIRE_RIGHT_ARM = "ar";

export const WIRE_TO_CHANNEL = {
  [WIRE_LEFT_LEG]: CHANNEL_LEFT_LEG,
  [WIRE_RIGHT_LEG]: CHANNEL_RIGHT_LEG,
  [WIRE_LEFT_ARM]: CHANNEL_LEFT_ARM,
  [WIRE_RIGHT_ARM]: CHANNEL_RIGHT_ARM,
};

export const KEYFRAME_MILLISECONDS_KEY = "ms";
export const VERB_NAME_FIELD = "v";
export const VERB_GESTURE = "gesture";
export const ARG_TYPE_STRING = "string";
export const ARG_TYPE_ENUM = "enum";
export const ARG_TYPE_NUMBER = "number";
export const ARG_TYPE_ARRAY = "array";

export const DEFAULT_MAX_MOTION_VERBS_PER_TICK = 1;

export function usedChannelsForVerb(verbCall, body) {
  if (verbCall[VERB_NAME_FIELD] === VERB_GESTURE && Array.isArray(verbCall.args?.steps)) {
    const used = new Set();
    for (const step of verbCall.args.steps) {
      for (const key of Object.keys(step)) {
        if (key === KEYFRAME_MILLISECONDS_KEY) continue;
        used.add(WIRE_TO_CHANNEL[key] || key);
      }
    }
    return [...used];
  }
  const spec = verbCall.spec || body.verbs.find(verb => verb[VERB_NAME_FIELD] === verbCall[VERB_NAME_FIELD]);
  return spec?.channels || [];
}

export function channelSetsOverlap(firstVerb, secondVerb, body) {
  const claimed = new Set(usedChannelsForVerb(firstVerb, body));
  return usedChannelsForVerb(secondVerb, body).some(channelId => claimed.has(channelId));
}
