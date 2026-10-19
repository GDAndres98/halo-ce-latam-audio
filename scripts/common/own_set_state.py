"""Which own take sets are in force (docs/replacement-set-conversion.md). No imports: the store, the validator, the
build planner and the Studio all ask the same question here.

An own_sets entry is either
  active  (no `state` key; every entry written before 2026-10-18 is one): the sound plays only its added takes, and
          its Spain takes are dropped once one take is approved (docs/custom-take-set-design.md);
  staged  (`state: "staged"`): a conversion of the sound's per-take decisions was prepared but not switched on. The
          sound still plays as before (its line decisions and earlier added takes are in force); the takes the
          conversion created are not built until the owner switches the sound to its replacement set.
"""


def is_active(own_set):
    return own_set.get("state", "active") == "active"


def active_own_tags(doc):
    """Sounds whose replacement set is in force."""
    return {o["mcc_tag"] for o in doc.get("own_sets", []) if is_active(o)}


def staged_sets(doc):
    """{mcc_tag: own_set entry} of the conversions prepared but not switched on."""
    return {o["mcc_tag"]: o for o in doc.get("own_sets", []) if not is_active(o)}


def staged_take_ids(doc):
    """take_ids a staged conversion created: they wait for the switch and are never built before it."""
    return {t["take_id"] for o in staged_sets(doc).values()
            for t in (o.get("provenance") or {}).get("takes", []) if t.get("origin") == "created"}
