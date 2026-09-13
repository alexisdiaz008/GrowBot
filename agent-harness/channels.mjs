/** Channel ids — shared by the reference loop and tests.
 *
 * Gesture JSON uses the same channel ids as firmware. Duration key is
 * `milliseconds`. See docs/spec-rails.md.
 */

export const CHANNEL_LEFT_LEG = "leg_l";
export const CHANNEL_RIGHT_LEG = "leg_r";
export const CHANNEL_LEFT_ARM = "arm_l";
export const CHANNEL_RIGHT_ARM = "arm_r";

export const KEYFRAME_MILLISECONDS_KEY = "milliseconds";
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
        used.add(key);
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
