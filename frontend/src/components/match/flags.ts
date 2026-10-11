// The owner's mapping flags, with one icon each. Used everywhere a flag is shown (the MCC list, its filter,
// the flag checkboxes and the line summary) so the same flag always looks the same. Each icon always comes
// with a word or a tooltip: colour and shape are never the only signal.
//
// The flags are metadata only. Showing them changes nothing in the stored decision.

import { Mic, Puzzle, RadioTower } from "lucide-vue-next";
import type { Component } from "vue";

export type FlagName = "radio" | "recording" | "fits";

export interface FlagInfo {
  name: FlagName;
  /** The full label (checkbox, filter, tooltip). */
  label: string;
  /** A longer explanation, for the checkbox's tooltip. */
  hint: string;
  icon: Component;
  /** The MCC list filter value that shows only lines with this flag (see m4_app._slot_filter). */
  filter: string;
}

export const FLAGS: Record<FlagName, FlagInfo> = {
  radio: {
    name: "radio",
    label: "Needs radio effect",
    hint: "Flag only: no radio processing is applied yet (v1.1). Applies to a chosen Campaign Evolved recording.",
    icon: RadioTower,
    filter: "radio",
  },
  recording: {
    name: "recording",
    label: "Needs recording",
    hint: "No suitable recording exists yet: this line needs a new recording.",
    icon: Mic,
    filter: "recording",
  },
  fits: {
    name: "fits",
    label: "Different but fits",
    hint: "The Campaign Evolved dialogue differs from the MCC line, but fits the scene.",
    icon: Puzzle,
    filter: "fits",
  },
};

export const FLAG_ORDER: FlagName[] = ["radio", "recording", "fits"];
