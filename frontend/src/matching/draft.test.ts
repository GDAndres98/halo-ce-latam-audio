import { describe, expect, it } from "vitest";
import type { SlotDetail, StoredDecision } from "../api/types";
import {
  buildReworkBody,
  buildSaveBody,
  canApprove,
  canRework,
  defaultEdit,
  draftFrom,
  draftProblems,
  isDirty,
} from "./draft";

const HASHES = { mappings: "m".repeat(64), local: "l".repeat(64), progress: "p".repeat(64) };

function decision(overrides: Partial<StoredDecision> = {}): StoredDecision {
  return {
    mapping_id: "m-000001",
    match: { status: "matched", ce_line_refs: ["line_a#0"], decided_at: "2026-10-08", revision: 1 },
    audio: {
      status: "draft",
      source: "ce",
      sources: [{ kind: "ce", ce_line_ref: "line_a#0", language: "Spanish(Mexico)" }],
      edit: { ...defaultEdit(0), trim_start_s: 0.25 },
      approved_at: null,
      revision: 1,
    },
    subtitle: { status: "draft", source: "keep_original", ce_locres: null, custom_ref: null, approved_at: null, revision: 1 },
    radio_effect: { needed: false, set_at: null, revision: 1 },
    different_but_fits: { marked: false, set_at: null, revision: 1 },
    notes: "",
    ...overrides,
  };
}

function slot(mapping: StoredDecision | null, customText: string | null = null): SlotDetail {
  return {
    slot_id: "es:Z10_010_keyes#0",
    level: "z10",
    mcc_tag: "sound\\dialog\\z10\\z10_010_keyes",
    tag_name: "z10_010_keyes",
    kind: "dialog",
    speaker_from_name: "KEYES",
    spanish: { index: 0, subsong: 1, name_in_bank: "Z10_010_keyes", duration_s: 2, channels: 1 },
    english: [],
    mcc_subtitles: {},
    mapping,
    custom_text: customText,
    matched_lines: [],
    ce_missions: [],
    sha256: HASHES,
  };
}

describe("saving a draft", () => {
  it("does not send the audio recipe when the user did not change it", () => {
    const detail = slot(decision());
    const body = buildSaveBody(detail, draftFrom(detail), draftFrom(detail));
    expect(body.audio).toEqual({
      source: "ce",
      sources: [{ ce_line_ref: "line_a#0", language: "Spanish(Mexico)" }],
    });
    expect(body.audio).not.toHaveProperty("edit");
  });

  it("sends the recipe once the user changes it", () => {
    const detail = slot(decision());
    const baseline = draftFrom(detail);
    const draft = { ...baseline, edit: { ...baseline.edit, trim_start_s: 0.5 } };
    expect(buildSaveBody(detail, draft, baseline).audio?.edit?.trim_start_s).toBe(0.5);
  });

  it("sends no audio sources when Spain's audio is kept", () => {
    const detail = slot(decision({ audio: { ...decision().audio, source: "keep_original", sources: [] } }));
    const draft = { ...draftFrom(detail), audioSource: "keep_original" as const };
    expect(buildSaveBody(detail, draft, draftFrom(detail)).audio).toEqual({ source: "keep_original", sources: [] });
  });

  it("never sends an approved object, so approved decisions stay read-only", () => {
    const approved = decision({ audio: { ...decision().audio, status: "approved", approved_at: "2026-10-08" } });
    const detail = slot(approved);
    const draft = { ...draftFrom(detail), audioSource: "keep_original" as const };
    expect(buildSaveBody(detail, draft, draftFrom(detail))).not.toHaveProperty("audio");
  });

  it("always sends the independent radio and 'fits' flags", () => {
    const detail = slot(decision({ audio: { ...decision().audio, status: "approved", approved_at: "d" } }));
    const draft = { ...draftFrom(detail), radio: true, fits: true };
    const body = buildSaveBody(detail, draft, draftFrom(detail));
    expect(body.radio_effect).toEqual({ needed: true });
    expect(body.different_but_fits).toEqual({ marked: true });
  });

  it("sends custom subtitle text trimmed, with no CE line", () => {
    const detail = slot(null);
    const draft = { ...draftFrom(detail), subtitleSource: "custom" as const, customText: "  Despierte, Jefe.  " };
    expect(buildSaveBody(detail, draft, draftFrom(detail)).subtitle).toEqual({
      source: "custom",
      custom_text: "Despierte, Jefe.",
    });
  });

  it("distinguishes an intentionally omitted subtitle ('none') from a missing one", () => {
    const detail = slot(null);
    const draft = { ...draftFrom(detail), subtitleSource: "none" as const };
    expect(buildSaveBody(detail, draft, draftFrom(detail)).subtitle).toEqual({ source: "none" });
  });
});

describe("reading a stored recipe", () => {
  it("fills the fields the server did not store, so the editor always has lists to work on", () => {
    const sparse = decision({ audio: { ...decision().audio, edit: { trim_start_s: 0.1, trim_end_s: 0, gap_s: 0 } as never } });
    const draft = draftFrom(slot(sparse));
    expect(draft.edit.cuts).toEqual([]);
    expect(draft.edit.silences).toEqual([]);
    expect(draft.edit.trim_start_s).toBe(0.1);
  });

  it("keeps a stored loudness mode and fills its offset", () => {
    const partial = decision({ audio: { ...decision().audio, edit: { trim_start_s: 0, trim_end_s: 0, gap_s: 0, loudness: { mode: "match_mcc" } } as never } });
    expect(draftFrom(slot(partial)).edit.loudness).toEqual({ mode: "match_mcc", offset_db: 0 });
  });

  it("never keeps the server's recording binding", () => {
    const bound = decision({ audio: { ...decision().audio, edit: { ...defaultEdit(0), for_source: { ce_line_ref: "line_a#0" } } as never } });
    expect(draftFrom(slot(bound)).edit).not.toHaveProperty("for_source");
  });
});

describe("approval and rework", () => {
  it("blocks approval while the draft has unsaved changes", () => {
    const detail = slot(decision());
    const baseline = draftFrom(detail);
    const draft = { ...baseline, notes: "pending" };
    expect(canApprove("audio", decision(), draft, baseline)).toEqual({ allowed: false, reason: "Save the draft first." });
  });

  it("approves a saved audio draft independently of the subtitle", () => {
    const detail = slot(decision({ subtitle: { ...decision().subtitle, source: "none" } }));
    const baseline = draftFrom(detail);
    expect(canApprove("audio", detail.mapping, baseline, baseline).allowed).toBe(true);
    expect(canApprove("subtitle", detail.mapping, baseline, baseline).allowed).toBe(true);
  });

  it("refuses to approve an audio choice without a recording", () => {
    const detail = slot(null);
    const draft = { ...draftFrom(detail), audioSource: "ce" as const, audioRef: null };
    expect(canApprove("audio", null, draft, draft).reason).toMatch(/recording/);
  });

  it("only an approved decision can be sent to rework, and the body carries nothing else", () => {
    const approved = decision({ audio: { ...decision().audio, status: "approved", approved_at: "d" } });
    expect(canRework("audio", approved).allowed).toBe(true);
    expect(canRework("subtitle", approved).allowed).toBe(false);
    expect(buildReworkBody(slot(approved), "audio")).toEqual({
      slot_id: "es:Z10_010_keyes#0",
      loaded_sha256: HASHES.mappings,
      local_sha256: HASHES.local,
      actions: [{ action: "needs_rework", field: "audio" }],
    });
  });
});

describe("problems shown before any request", () => {
  it("asks for a replacement when CE audio is chosen without one", () => {
    const detail = slot(null);
    expect(draftProblems({ ...draftFrom(detail), audioSource: "ce", audioRef: null })).toHaveLength(1);
  });

  it("detects unsaved changes against the baseline", () => {
    const detail = slot(decision());
    const baseline = draftFrom(detail);
    expect(isDirty(baseline, draftFrom(detail))).toBe(false);
    expect(isDirty({ ...baseline, radio: true }, baseline)).toBe(true);
  });
});
