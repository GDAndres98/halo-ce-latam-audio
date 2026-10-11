// Highlighting for search results. Display only: which lines match is decided by the server.
//
// The server searches with punctuation-insensitive folding ("que paso" finds "¿Qué pasó?"). Highlighting
// here is a plainer case- and accent-insensitive substring match, so it can mark slightly less than the
// server matched (never more). The fold keeps every character's length, so a hit found in the folded
// text marks the same place in the original.

/** Lower-cases and removes accents, one output unit per input unit. Characters that would change length
 * (for example "ß" folding to "ss") are left as they are. */
export function foldKeepingLength(text: string): string {
  let out = "";
  for (const ch of text) {
    const base = ch.normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
    out += base.length === ch.length ? base : ch.toLowerCase();
  }
  return out;
}

export interface Segment {
  text: string;
  hit: boolean;
}

/** Splits `text` into runs, marking every place a search term occurs. */
export function highlightSegments(text: string, terms: string[]): Segment[] {
  const folded = foldKeepingLength(text);
  const marked = new Array<boolean>(text.length).fill(false);
  for (const term of terms) {
    const needle = foldKeepingLength(term.trim());
    if (!needle) continue;
    for (let i = folded.indexOf(needle); i >= 0; i = folded.indexOf(needle, i + 1)) {
      marked.fill(true, i, i + needle.length);
    }
  }
  const segments: Segment[] = [];
  let start = 0;
  for (let i = 1; i <= text.length; i++) {
    if (i === text.length || marked[i] !== marked[start]) {
      segments.push({ text: text.slice(start, i), hit: marked[start] });
      start = i;
    }
  }
  return segments;
}
