"""Suggested matches, second opinion: Claude re-ranks one MCC line's shortlist (docs/suggested-matching.md).

Read-only, like common/suggest.py: it returns an ordering with reasons and never writes a decision. Only on the
owner's request (one MCC sound, or one bark folder, from the Suggestions tab); answers are cached under
work/m4/suggest/ai/ so the same question is never paid for twice.

What is sent to the Claude API:
- subtitled lines: the MCC sound's English subtitle, speaker and level, the MCC English lines just before and after
  it, and each shortlisted CE line's id, speaker, mission and English subtitle;
- barks (no subtitles on either side): MCC sound names below the level folder with their take counts, and CE record
  names (raw and with abbreviations expanded), folders and variation counts.
No audio, no Spanish text, no file paths.

Needs the `anthropic` package (owner approval to install, CLAUDE.md rule 5) and a credential: ANTHROPIC_API_KEY in
the environment or in the git-ignored .env, or an `ant auth login` profile.
"""
import hashlib
import json
import os
from pathlib import Path

from common.env import load_env

MODEL = "claude-opus-5-5"
PROMPT_VERSION = "suggest-ai/1"
CACHE_DIR = "work/m4/suggest/ai"
VERDICTS = ("same_line", "reworded", "related", "different")

SYSTEM = """You compare dialogue from two versions of the video game Halo: Combat Evolved.
- "MCC" is the original 2001 game (as shipped in The Master Chief Collection).
- "CE" is Halo: Campaign Evolved (2026), a remake that re-recorded the dialogue. Many lines are kept word for word, \
many are reworded, some are new, and some original lines were cut.

You get one MCC line (English subtitle, speaker, level, and the lines around it) and a shortlist of CE lines \
(id, speaker, mission, English subtitle). For each CE line decide whether it is the remake's recording of the same \
moment as the MCC line:
- same_line: the same line, identical or with trivial differences.
- reworded: clearly the same moment and intent, said differently.
- related: same scene or topic, but not a replacement for this line.
- different: not this line.
Give a confidence from 0 to 1 and one short reason (under 25 words) naming what decided it (wording, speaker, \
context). Rank the candidates best first. Judge only from the text given; do not invent context."""

SCHEMA = {
    "type": "object",
    "properties": {
        "ranking": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "verdict": {"type": "string", "enum": list(VERDICTS)},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["id", "verdict", "confidence", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["ranking"],
    "additionalProperties": False,
}


class AiUnavailable(Exception):
    """The SDK is missing, no credential works, or the API refused or failed. The message is for the owner."""


def _credential(root):
    """(api_key or None, where it came from). None = let the SDK resolve it (ANTHROPIC_AUTH_TOKEN, a profile)."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return None, "environment"
    env_file = Path(root) / ".env"
    if env_file.is_file():
        key = load_env(env_file)[0].get("ANTHROPIC_API_KEY")
        if key:
            return key, ".env"
    return None, "sdk default (ANTHROPIC_AUTH_TOKEN or an `ant auth login` profile)"


def status(root):
    """What the page shows before the owner asks: is the SDK installed, where would the credential come from."""
    try:
        import anthropic  # noqa: F401
        sdk = True
    except ImportError:
        sdk = False
    return {"sdk_installed": sdk, "credential": _credential(root)[1], "model": MODEL,
            "prompt_version": PROMPT_VERSION}


def build_request(mcc, candidates):
    """mcc = {tag_name, level, speaker, english, context: [{position, speaker, english}]};
    candidates = [{id, speaker, mission, english}]. -> the user message text (deterministic)."""
    payload = {"mcc_line": mcc, "ce_candidates": candidates}
    return ("Rank these CE lines against the MCC line. Data (JSON):\n"
            + json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1))


SYSTEM_BARKS = """You compare AI combat chatter ("barks") from two versions of the video game Halo: Combat Evolved.
- "MCC" is the original 2001 game (as shipped in The Master Chief Collection). Each MCC sound is named by its tag \
path, a category and a situation, e.g. "conditional/combat2/exclamations/surprise"; it has several recorded takes.
- "CE" is Halo: Campaign Evolved (2026), a remake that re-recorded the chatter. Each CE record is named by situation \
with abbreviations, e.g. "01contact_srprs" (surprise on first contact), "11involuntary_dth" (death), \
"02combat_rtrt" (retreat), "kllfoe" (killed foe), "grnd" (grenade); "expanded" spells the abbreviations out \
(automatically, so it can be wrong). Each record has several variations.
Neither side has subtitles: judge only from the names, the character and the counts. Decide whether the CE record \
would play in the same game situation as the MCC sound, so its variations could replace the MCC takes:
- same_line: the same situation.
- reworded: a close situation that would work in its place.
- related: same family of situations, but a different trigger.
- different: not this situation.
Give a confidence from 0 to 1 and one short reason (under 25 words). Do not invent situations the names don't \
support."""

SCHEMA_FOLDER = {
    "type": "object",
    "properties": {
        "sounds": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "mcc_id": {"type": "string"},
                    "picks": SCHEMA["properties"]["ranking"],
                },
                "required": ["mcc_id", "picks"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["sounds"],
    "additionalProperties": False,
}


def build_name_request(mcc, candidates):
    """Barks, one sound: mcc = {level, sound, takes}; candidates = [{id, name, expanded, folder, variations}]."""
    return ("Rank these CE records against the MCC sound. Data (JSON):\n"
            + json.dumps({"mcc_sound": mcc, "ce_candidates": candidates}, ensure_ascii=False, sort_keys=True, indent=1))


def build_folder_request(level, sounds, records):
    """Barks, a whole folder: sounds = [{id, sound, takes}]; records = [{id, name, expanded, folder, variations}]."""
    return (f"For each MCC sound of the folder '{level}', pick up to 3 CE records that fit it best, best first "
            "(fewer, or none, when nothing fits). Answer for every MCC sound. Data (JSON):\n"
            + json.dumps({"mcc_folder": level, "mcc_sounds": sounds, "ce_records": records},
                         ensure_ascii=False, sort_keys=True, indent=1))


def cache_key(user_text, system=SYSTEM, schema=SCHEMA):
    blob = json.dumps({"model": MODEL, "prompt": PROMPT_VERSION, "system": system, "schema": schema,
                       "user": user_text}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _clean(ranking, ids, limit=None):
    """Keep only the ids that were asked about, once each, in Claude's order; clamp the confidence."""
    seen, out = set(), []
    for r in ranking:
        if r.get("id") in ids and r["id"] not in seen and r.get("verdict") in VERDICTS:
            seen.add(r["id"])
            out.append({"ce_line_ref": r["id"], "verdict": r["verdict"],
                        "confidence": max(0.0, min(1.0, float(r.get("confidence") or 0))),
                        "reason": str(r.get("reason") or "")[:300]})
    return out[:limit] if limit else out


def _ask(root, system, schema, user_text, client, max_tokens, shape):
    """One cached request -> (result, cached). shape(parsed JSON) gives the result's fields. Failures raise
    AiUnavailable and cache nothing."""
    key = cache_key(user_text, system, schema)
    cache = Path(root) / CACHE_DIR / f"{key}.json"
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8")), True
    if client is None:
        try:
            import anthropic
        except ImportError:
            raise AiUnavailable("The Claude re-rank needs the `anthropic` Python package (pip install anthropic); "
                                "it is not installed.")
        api_key, _src = _credential(root)
        client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_text}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
            betas=["server-side-fallback-2026-07-01"],
            extra_body={"fallbacks": "default"},
        )
    except Exception as e:  # the SDK's typed errors: auth, rate limit, connection. Reported, never retried here.
        raise AiUnavailable(f"The Claude API call failed: {type(e).__name__}: {e}")
    if response.stop_reason == "refusal":
        raise AiUnavailable("Claude declined this request.")
    if response.stop_reason == "max_tokens":
        raise AiUnavailable("Claude's answer was cut off (max_tokens); nothing was used.")
    text = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
    try:
        fields = shape(json.loads(text))
    except (ValueError, KeyError, TypeError, AttributeError):
        raise AiUnavailable("Claude's answer was not the expected JSON; nothing was used.")
    usage = getattr(response, "usage", None)
    result = {"model": getattr(response, "model", MODEL), "prompt_version": PROMPT_VERSION, **fields,
              "usage": {"input_tokens": getattr(usage, "input_tokens", None),
                        "output_tokens": getattr(usage, "output_tokens", None)} if usage else None}
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    tmp.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
    tmp.replace(cache)
    return result, False


def rerank(root, mcc, candidates, client=None, mode="text"):
    """One sound's shortlist -> {model, ranking, cached, usage}. mode 'text' (subtitled lines) or 'name' (barks).
    client: an anthropic.Anthropic (tests pass a stub)."""
    if not candidates:
        return {"model": MODEL, "ranking": [], "cached": False, "usage": None}
    ids = {c["id"] for c in candidates}
    if mode == "name":
        system, user_text = SYSTEM_BARKS, build_name_request(mcc, candidates)
    else:
        system, user_text = SYSTEM, build_request(mcc, candidates)
    result, cached = _ask(root, system, SCHEMA, user_text, client, 4000,
                          lambda d: {"ranking": _clean(d["ranking"], ids)})
    return {**result, "cached": cached}


def match_folder(root, level, sounds, records, client=None):
    """Barks, a whole folder in one request -> {model, sounds: {mcc_id: [picks]}, cached, usage}."""
    if not sounds or not records:
        return {"model": MODEL, "sounds": {}, "cached": False, "usage": None}
    mcc_ids, ce_ids = {s["id"] for s in sounds}, {r["id"] for r in records}

    def shape(d):
        out = {}
        for item in d["sounds"]:
            if item.get("mcc_id") in mcc_ids and item["mcc_id"] not in out:
                out[item["mcc_id"]] = _clean(item.get("picks") or [], ce_ids, limit=3)
        return {"sounds": out}
    result, cached = _ask(root, SYSTEM_BARKS, SCHEMA_FOLDER, build_folder_request(level, sounds, records), client,
                          16000, shape)
    return {**result, "cached": cached}
