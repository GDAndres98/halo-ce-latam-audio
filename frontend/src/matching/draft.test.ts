import { describe, expect, it } from "vitest";
import type { SlotDetail, StoredDecision } from "../api/types";
import {
  buildReworkBody,
  buildSaveBody,
  canApprove,
  canRework,
  canUnmatch,
  defaultEdit,
  draftFrom,
  draftProblems,
  isDirty,
  muteDraft,
  proposeSubtitle,
  subtitleDirty,
  unmatchDraft,
  type Draft,
} from "./draft";
import type { CeLine } from "../api/types";

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

  it("drops the removed loudness and limiter settings of older recipes", () => {
    const old = decision({ audio: { ...decision().audio, edit: { ...defaultEdit(0), loudness: { mode: "off", offset_db: 0 }, limiter: true } as never } });
    const edit = draftFrom(slot(old)).edit as unknown as Record<string, unknown>;
    expect("loudness" in edit || "limiter" in edit).toBe(false);
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

function ceLine(ref: string, latam: string | null): CeLine {
  return {
    ce_line_ref: ref,
    mission: "M01",
    display_key: ref,
    family: "scripted",
    folder: "",
    has_source_subtitle: { "es-MX": Boolean(latam) },
    subtitles: { "es-MX": { text: latam } },
    media: {} as CeLine["media"],
  };
}

describe("needs recording flag", () => {
  it("is read from the stored decision and always sent", () => {
    const detail = slot(decision({ needs_recording: { marked: true, set_at: "2026-10-11", revision: 1 } }));
    const draft = draftFrom(detail);
    expect(draft.recording).toBe(true);
    expect(buildSaveBody(detail, draft, draft).needs_recording).toEqual({ marked: true });
    expect(draftFrom(slot(decision())).recording).toBe(false);
  });
});

describe("proposing the subtitle of a chosen recording", () => {
  it("offers the LATAM subtitle when the subtitle is still MCC's default", () => {
    const detail = slot(null);
    const baseline = draftFrom(detail);
    const draft = draftFrom(detail);
    expect(proposeSubtitle(draft, baseline, null, ceLine("a#0", "Hola"), null)).toBe("proposed");
    expect([draft.subtitleSource, draft.subtitleRef, draft.subtitleCulture]).toEqual(["ce_locres", "a#0", "es-MX"]);
    expect(subtitleDirty(draft, baseline)).toBe(true);
  });

  it("follows the user to another recording while the proposal is unchanged", () => {
    const detail = slot(null);
    const baseline = draftFrom(detail);
    const draft = draftFrom(detail);
    proposeSubtitle(draft, baseline, null, ceLine("a#0", "Hola"), null);
    expect(proposeSubtitle(draft, baseline, null, ceLine("b#0", "Adiós"), "a#0")).toBe("proposed");
    expect(draft.subtitleRef).toBe("b#0");
    // A recording without a LATAM subtitle withdraws the proposal and asks for a manual choice.
    expect(proposeSubtitle(draft, baseline, null, ceLine("c#0", null), "b#0")).toBe("missing");
    expect(draft.subtitleSource).toBe("keep_original");
  });

  it("never replaces a saved, edited or approved subtitle", () => {
    const saved = slot(decision({ subtitle: { status: "draft", source: "custom", ce_locres: null, custom_ref: "c-000001", approved_at: null, revision: 1 } }), "Mi texto");
    const savedDraft = draftFrom(saved);
    expect(proposeSubtitle(savedDraft, draftFrom(saved), saved.mapping, ceLine("a#0", "Hola"), null)).toBe("kept");
    expect(savedDraft.subtitleSource).toBe("custom");

    const fresh = slot(null);
    const edited = draftFrom(fresh);
    edited.subtitleSource = "none"; // chosen by the user in this session
    expect(proposeSubtitle(edited, draftFrom(fresh), null, ceLine("a#0", "Hola"), null)).toBe("kept");

    const approved = slot(decision({ subtitle: { status: "approved", source: "keep_original", ce_locres: null, custom_ref: null, approved_at: "2026-10-11", revision: 1 } }));
    const approvedDraft = draftFrom(approved);
    expect(proposeSubtitle(approvedDraft, draftFrom(approved), approved.mapping, ceLine("a#0", "Hola"), null)).toBe("kept");
    expect(approvedDraft.subtitleSource).toBe("keep_original");

    // The user changed the proposal to their own text: choosing another recording keeps it.
    const own = draftFrom(fresh);
    proposeSubtitle(own, draftFrom(fresh), null, ceLine("a#0", "Hola"), null);
    own.subtitleSource = "custom";
    own.customText = "Texto propio";
    expect(proposeSubtitle(own, draftFrom(fresh), null, ceLine("b#0", "Adiós"), "a#0")).toBe("kept");
  });
});

describe("unmatching a line", () => {
  const matched = (): Draft => ({
    ...draftFrom(slot(null)),
    matchStatus: "matched",
    ceRefs: ["a#0", "b#0"],
    audioSource: "ce",
    audioRef: "a#0",
    edit: { ...defaultEdit(), trim_start_s: 0.2 },
    subtitleSource: "ce_locres",
    subtitleRef: "a#0",
    radio: true,
    fits: true,
    recording: true,
    notes: "kept",
  });

  it("returns the draft to an unmatched line and keeps the user's own text and notes", () => {
    const d = matched();
    unmatchDraft(d);
    expect(d).toMatchObject({ matchStatus: "unreviewed", ceRefs: [], audioSource: "keep_original", audioRef: null,
      subtitleSource: "keep_original", subtitleRef: null, radio: false, fits: false, recording: true, notes: "kept" });
    expect(d.edit).toEqual(defaultEdit());
    expect(draftProblems(d)).toEqual([]);
  });

  it("keeps a custom subtitle", () => {
    const d = { ...matched(), subtitleSource: "custom" as const, customText: "Mi texto" };
    unmatchDraft(d);
    expect([d.subtitleSource, d.customText]).toEqual(["custom", "Mi texto"]);
  });

  it("is refused while the audio is approved, and when nothing is matched", () => {
    const approved = decision();
    approved.audio.status = "approved";
    expect(canUnmatch(approved, matched()).allowed).toBe(false);
    expect(canUnmatch(null, matched()).allowed).toBe(true);
    expect(canUnmatch(null, draftFrom(slot(null))).allowed).toBe(false);
  });
});

describe("mute / no replacement", () => {
  it("marks the line no equivalent, drops CE lines and edits, and proposes no subtitle", () => {
    const detail = slot(decision({ radio_effect: { needed: true, set_at: null, revision: 1 } }));
    const d = draftFrom(detail);
    muteDraft(d, false);
    expect([d.matchStatus, d.ceRefs, d.audioSource, d.audioRef, d.radio]).toEqual(["no_equivalent", [], "mute", null, false]);
    expect(d.edit).toEqual(defaultEdit(0));
    expect(d.subtitleSource).toBe("none");
    expect(draftProblems(d)).toEqual(["Say why the line is muted."]);
    d.muteReason = "  no equivalent in Campaign Evolved  ";
    expect(draftProblems(d)).toEqual([]);
    const body = buildSaveBody(detail, d, draftFrom(detail));
    expect(body.audio).toEqual({ source: "mute", sources: [], mute_reason: "no equivalent in Campaign Evolved" });
    expect(body.match).toEqual({ status: "no_equivalent", ce_line_refs: [] });
  });

  it("never touches an approved subtitle or a custom one", () => {
    const custom = draftFrom(slot(decision({ subtitle: { status: "draft", source: "custom", ce_locres: null, custom_ref: "c-000001", approved_at: null, revision: 1 } }), "Hola"));
    muteDraft(custom, false);
    expect(custom.subtitleSource).toBe("custom");
    const approved = draftFrom(slot(decision({ subtitle: { status: "approved", source: "keep_original", ce_locres: null, custom_ref: null, approved_at: "2026-10-15", revision: 1 } })));
    muteDraft(approved, true);
    expect(approved.subtitleSource).toBe("keep_original");
  });

  it("can be undone by unmatching (Spain's audio again)", () => {
    const d = draftFrom(slot(decision()));
    muteDraft(d, false);
    unmatchDraft(d);
    expect([d.matchStatus, d.audioSource]).toEqual(["unreviewed", "keep_original"]);
  });
});
