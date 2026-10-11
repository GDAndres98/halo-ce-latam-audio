// Display names for MCC Halo CE dialogue folders: the campaign levels by their mission titles, and the
// cinematic folders. Only for showing; folders are always identified by their code (a10, x20, …).

const MISSIONS: Record<string, string> = {
  a10: "The Pillar of Autumn",
  a30: "Halo",
  a50: "The Truth and Reconciliation",
  b30: "The Silent Cartographer",
  b40: "Assault on the Control Room",
  c10: "343 Guilty Spark",
  c20: "The Library",
  c40: "Two Betrayals",
  d20: "Keyes",
  d40: "The Maw",
};

/** "The Pillar of Autumn" for a10, "Cinematic x20" for x20, "" for a folder with no known name. */
export function levelTitle(level: string): string {
  if (MISSIONS[level]) return MISSIONS[level];
  if (/^x\d0$/.test(level)) return `Cinematic ${level}`;
  return "";
}
