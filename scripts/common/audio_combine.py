"""Two Campaign Evolved lines in one replacement (owner request 2026-10-19; docs/combine-recordings.md).

Two ways, chosen as the line's audio source (manual-mappings/3, line decisions only):

  ce_concat  "Join two recordings": part 1, then part 2. Each part has its own edit recipe (trims, cuts, inserted
             silences, fades: common/audio_edit, without radio / echo / interference), and `gap_s` seconds lie
             between them: silence when positive; when negative the parts overlap by that much and both play
             (they are summed; each part's own fades shape the overlap).
  ce_mix     "Play two recordings at the same time": both unedited, summed; the second starts `offset_s` seconds
             after the first (negative: the first starts later).

The recipe (`audio.edit`, format audio-combine/1):

    {"engine": "audio-combine/1", "mode": "concat" | "mix",
     "for_sources": [{"ce_line_ref", "language"}, {"ce_line_ref", "language"}],   # = the audio sources, in order
     "parts": [<audio-edit recipe>, <audio-edit recipe>], "gap_s": -0.25,        # concat only
     "offset_s": 0.4,                                                             # mix only
     "radio": {...}, "echo": {...}}                                               # optional, on the result

Levels: both recordings play at their own level (no per-recording volume: the owner's choice, and per-line gain
was removed 2026-10-09). Where they sum past the peak ceiling (PEAK_CEILING_DB), the combined audio is lowered just
enough, linearly, and the render reports it, like the effects trim in audio_edit. Then the same stages as one
line: radio filter and echo (on the result), the build-level level mode (global gain or match Spain), the radio
clicks, 16-bit (audio_edit.finish). Deterministic; nothing here reads mappings or writes files.
"""
from . import audio_edit as ae

ENGINE = "audio-combine/1"
RENDER_ENGINE = "audio-combine-render/1"
MODES = ("concat", "mix")
SOURCE_OF = {"concat": "ce_concat", "mix": "ce_mix"}
MODE_OF = {v: k for k, v in SOURCE_OF.items()}
GAP_S = (-5.0, 5.0)
OFFSET_S = (-10.0, 10.0)
PART_FORBIDDEN = ("radio", "echo", "interference")


def is_combine(edit):
    return isinstance(edit, dict) and edit.get("engine") == ENGINE


def default(mode, for_sources):
    """The recipe a new join / overlay starts from: unedited parts, no gap, no offset, no effects."""
    out = {"engine": ENGINE, "mode": mode, "for_sources": [dict(s) for s in for_sources]}
    if mode == "concat":
        out.update(parts=[dict(ae.EDIT_ZERO), dict(ae.EDIT_ZERO)], gap_s=0)
    else:
        out["offset_s"] = 0
    return out


def _bind(src):
    return {"ce_line_ref": src["ce_line_ref"], "language": src["language"]}


def normalize(raw, mode, for_sources):
    """Owner input -> canonical recipe. for_sources: the two audio sources ({ce_line_ref, language}), in order.
    Raises audio_edit.EditError for anything malformed or out of range (durations: `problems`)."""
    if mode not in MODES:
        raise ae.EditError(f"unknown combine mode {mode!r}")
    if len(for_sources) != 2:
        raise ae.EditError("a join or an overlay uses exactly two recordings")
    r = dict(raw or {})
    allowed = {"engine", "mode", "for_sources", "radio", "echo"} | ({"parts", "gap_s"} if mode == "concat" else {"offset_s"})
    unknown = set(r) - allowed
    if unknown:
        raise ae.EditError(f"unknown field(s) for a {'join' if mode == 'concat' else 'overlay'}: {sorted(unknown)}")
    srcs = [_bind(s) for s in for_sources]
    out = {"engine": ENGINE, "mode": mode, "for_sources": srcs}
    if mode == "concat":
        parts = r.get("parts") or [{}, {}]
        if not isinstance(parts, list) or len(parts) != 2:
            raise ae.EditError("a join has exactly two parts")
        norm = []
        for k, p in enumerate(parts):
            p = dict(p or {})
            p.pop("for_source", None)
            bad = [f for f in PART_FORBIDDEN if p.get(f)]
            if bad:
                raise ae.EditError(f"part {k + 1}: {', '.join(bad)} apply to the joined result, not to one part")
            p.pop("gap_s", None)
            norm.append(ae.normalize(p, for_source=srcs[k]))
        out["parts"] = norm
        out["gap_s"] = ae._r(ae._num(r.get("gap_s", 0), "gap_s"), 3)
    else:
        out["offset_s"] = ae._r(ae._num(r.get("offset_s", 0), "offset_s"), 3)
    radio = ae.normalize_radio(r.get("radio"))
    if radio:
        out["radio"] = radio
    echo = ae.normalize_echo(r.get("echo"))
    if echo:
        out["echo"] = echo
    bad = problems(out)
    if bad:
        raise ae.EditError("; ".join(bad))
    return out


def problems(edit, durations=None, sources=None):
    """Rule violations of a stored combine recipe (empty = fine). durations: the two source lengths in seconds
    (checks each part's timeline). sources: the decision's audio sources, which for_sources must equal."""
    e = edit or {}
    out = []
    if e.get("engine") != ENGINE:
        return [f"unknown combine engine {e.get('engine')!r} (expected {ENGINE})"]
    mode = e.get("mode")
    if mode not in MODES:
        return [f"unknown combine mode {mode!r}"]
    fs = e.get("for_sources") or []
    if len(fs) != 2:
        out.append("a join or an overlay uses exactly two recordings")
    if sources is not None and [_bind(s) for s in sources if s.get("kind", "ce") == "ce"] != [_bind(s) for s in fs]:
        out.append("the recipe was made for other recordings or another order; reset it")
    if mode == "concat":
        parts = e.get("parts") or []
        if len(parts) != 2:
            out.append("a join has exactly two parts")
        for k, p in enumerate(parts):
            if any(p.get(f) for f in PART_FORBIDDEN):
                out.append(f"part {k + 1}: radio, echo and interference apply to the joined result")
            if not ae.is_identity(p) and k < len(fs) and p.get("for_source") != _bind(fs[k]):
                out.append(f"part {k + 1}: the recipe was made for another recording")
            dur = durations[k] if durations and k < len(durations) else None
            out += [f"part {k + 1}: {x}" for x in ae.problems(p, dur)]
        g = e.get("gap_s", 0)
        if not GAP_S[0] <= g <= GAP_S[1]:
            out.append(f"gap {g} s outside {GAP_S[0]}..{GAP_S[1]} s")
        if "offset_s" in e:
            out.append("a join has no offset")
    else:
        o = e.get("offset_s", 0)
        if not OFFSET_S[0] <= o <= OFFSET_S[1]:
            out.append(f"offset {o} s outside {OFFSET_S[0]}..{OFFSET_S[1]} s")
        if "parts" in e or "gap_s" in e:
            out.append("an overlay has no parts or gap (both recordings play unedited)")
    out += ae.radio_problems(e.get("radio"))
    out += ae.echo_problems(e.get("echo"))
    return out


def summary(edit):
    """e.g. 'join · gap -0.25 s · part 1: trim 0.10/0.00 s · radio spain 700–3300 Hz'."""
    e = edit
    if e.get("mode") == "concat":
        bits = ["join", f"gap {e.get('gap_s', 0):+g} s" if e.get("gap_s") else "no gap"]
        for k, p in enumerate(e.get("parts") or []):
            if not ae.is_identity(p):
                bits.append(f"part {k + 1}: {ae.summary(p)}")
    else:
        o = e.get("offset_s", 0)
        bits = ["together", f"second starts {o:+g} s" if o else "both start together"]
    if e.get("radio"):
        bits.append(ae.radio_summary(e["radio"]))
    if e.get("echo"):
        bits.append(ae.echo_summary(e["echo"]))
    return " · ".join(bits)


def _sum_at(a, b, start_a, start_b):
    n = max(start_a + len(a), start_b + len(b))
    y = [0.0] * n
    for i, v in enumerate(a):
        y[start_a + i] += v
    for i, v in enumerate(b):
        y[start_b + i] += v
    overlap = max(0, min(start_a + len(a), start_b + len(b)) - max(start_a, start_b))
    return y, overlap


def render(pcms, edit, *, ref_lufs=None, global_gain_db=0.0, level_mode="global_gain", fs=ae.SAMPLE_RATE,
           clicks=None):
    """Two 44.1 kHz mono 16-bit PCMs (in source order) + combine recipe + level -> {"pcm", "stats"}."""
    if level_mode not in ae.LEVEL_MODES:
        raise ae.EditError(f"unknown level mode {level_mode!r}")
    if len(pcms) != 2:
        raise ae.EditError("a join or an overlay uses exactly two recordings")
    xs = [ae.pcm16_to_float(p) for p in pcms]
    bad = problems(edit, [len(x) / fs for x in xs])
    if bad:
        raise ae.EditError("; ".join(bad))
    warnings, parts = [], []
    if edit["mode"] == "concat":
        ys = []
        for x, p in zip(xs, edit["parts"]):
            y, segs, inserted = ae.edit_stage(x, p, fs)
            ys.append(y)
            parts.append({"source_s": round(len(x) / fs, 3), "identity": ae.is_identity(p),
                          "kept_segments_s": [[round(a / fs, 3), round(b / fs, 3)] for a, b in segs],
                          "inserted_silence_s": round(inserted / fs, 3), "edited_s": round(len(y) / fs, 3)})
        start_b = max(0, len(ys[0]) + int(round(edit["gap_s"] * fs)))
        y, overlap = _sum_at(ys[0], ys[1], 0, start_b)
        placed = {"part_2_starts_s": round(start_b / fs, 3)}
    else:
        off = int(round(edit["offset_s"] * fs))
        start_a, start_b = max(0, -off), max(0, off)
        for x in xs:
            parts.append({"source_s": round(len(x) / fs, 3), "identity": True})
        y, overlap = _sum_at(xs[0], xs[1], start_a, start_b)
        placed = {"first_starts_s": round(start_a / fs, 3), "second_starts_s": round(start_b / fs, 3)}
    sum_trim = 0.0
    pk = ae.peak_db(y)
    if pk is not None and pk > ae.PEAK_CEILING_DB:  # the two recordings add up past the ceiling: a linear trim
        g = 10 ** ((ae.PEAK_CEILING_DB - pk) / 20)
        y = [v * g for v in y]
        sum_trim = round(ae.PEAK_CEILING_DB - pk, 2)
        warnings.append(f"combined: lowered by {-sum_trim:.1f} dB where the recordings add up past "
                        f"{ae.PEAK_CEILING_DB:g} dBFS")
    combined = len(y)
    out, f = ae.finish(y, edit, warnings=warnings, ref_lufs=ref_lufs, global_gain_db=global_gain_db,
                       level_mode=level_mode, fs=fs, clicks=clicks)
    final, match = f["final"], f["match"]
    stats = {"engine": RENDER_ENGINE, "recipe_format": ENGINE, "mode": edit["mode"], "identity": False,
             "parts": parts, **placed, "overlap_s": round(overlap / fs, 3), "sum_trim_db": sum_trim,
             "source_samples": sum(len(x) for x in xs), "source_s": round(sum(len(x) for x in xs) / fs, 3),
             "edited_samples": f["edited"], "edited_s": round(f["edited"] / fs, 3), "combined_s": round(combined / fs, 3),
             "output_samples": len(final), "output_s": round(len(final) / fs, 3),
             **ae.level_stats(f, ref_lufs=ref_lufs, global_gain_db=global_gain_db, level_mode=level_mode),
             "interference": None,
             "total_gain_db": match["applied_db"] if match else f["g_applied"],
             "output_lufs": ae._rnd(ae.loudness(final, fs)[0]), "output_peak_dbfs": ae._rnd(ae.peak_db(final)),
             "warnings": warnings}
    return {"pcm": out, "stats": stats}
