"""Suggested matches (stdlib only): MCC English subtitle text compared with Campaign Evolved English subtitle text,
and, for sounds with no English subtitle (AI barks), MCC sound names compared with CE record names.

The owner lifted the "no suggestions" rule on 2026-10-23 for a **read-only** Suggestions tab
(docs/suggested-matching.md). What this module guarantees:

- It only scores. It never writes, saves, selects or pre-fills anything; decisions stay the owner's, in Matching.
- English against English: MCC's `EN_Halo1.bin` text (per sound) and CE's `en` Subtitles.locres text (per line).
  Spanish texts are shown beside the suggestions, never scored.
- Deterministic: the same catalogs give the same scores and the same order (ties broken by catalog order).

Score (0..1) = 0.5 x word cosine (TF-IDF over the CE texts) + 0.3 x character-trigram Dice + 0.2 x difflib ratio,
plus SPEAKER_BONUS when the speakers' names agree (capped at 1). Every part is returned so the page can say why.
"""
import difflib
import math
import re
import unicodedata

WEIGHTS = {"words": 0.5, "chars": 0.3, "sequence": 0.2}
SPEAKER_BONUS = 0.05
METHOD = "suggest/1: EN subtitle vs EN subtitle; 0.5 word TF-IDF cosine + 0.3 char-trigram Dice + 0.2 difflib ratio" \
         " (+0.05 same speaker)"
_SPEAKER_SPLIT = re.compile(r"[^a-z0-9]+")


def fold(text):
    """Lower-case, accents removed, every run of non-alphanumerics -> one space."""
    s = "".join(c for c in unicodedata.normalize("NFKD", text or "") if not unicodedata.combining(c)).casefold()
    return " ".join(re.sub(r"[^0-9a-z]+", " ", s).split())


def words(folded):
    return folded.split()


def trigrams(folded):
    s = f"  {folded} "
    return {s[i:i + 3] for i in range(len(s) - 2)} if folded else set()


def speaker_key(name):
    """'CryoTech', 'cryotech', 'CRYO TECH' -> 'cryotech'."""
    return _SPEAKER_SPLIT.sub("", (name or "").casefold())


def same_speaker(a, b):
    """Speaker keys agree: equal, or one abbreviates the other ('cryoassist' / 'cryoassistant'; 4+ letters)."""
    if not a or not b:
        return False
    short, long_ = sorted((a, b), key=len)
    return len(short) >= 4 and long_.startswith(short)


def ce_speaker(display_key):
    """VO_SCR_M01_00460_CryoTech -> 'cryotech' (the asset name ends with the speaker)."""
    tail = (display_key or "").rsplit("_", 1)[-1]
    return speaker_key(tail) if tail and not tail.isdigit() else ""


class Candidate:
    __slots__ = ("ref", "text", "folded", "vec", "norm", "grams", "speaker", "order")

    def __init__(self, ref, text, speaker, order):
        self.ref, self.text, self.speaker, self.order = ref, text, speaker, order
        self.folded = fold(text)
        self.grams = trigrams(self.folded)
        self.vec, self.norm = {}, 0.0


class SuggestIndex:
    """The CE side: every line with English text. `items` = [(ce_line_ref, english_text, speaker_key)] in catalog
    order. IDF is computed over these texts, so the same index always gives the same scores."""

    def __init__(self, items):
        self.cands = [Candidate(ref, text, spk, i) for i, (ref, text, spk) in enumerate(items) if fold(text)]
        self.by_ref = {c.ref: c for c in self.cands}
        df = {}
        for c in self.cands:
            for w in set(words(c.folded)):
                df[w] = df.get(w, 0) + 1
        n = len(self.cands)
        self.idf = {w: math.log((1 + n) / (1 + k)) + 1.0 for w, k in df.items()}
        self.default_idf = math.log(1 + n) + 1.0  # a word no CE line has
        for c in self.cands:
            c.vec, c.norm = self._vector(c.folded)

    def _vector(self, folded):
        tf = {}
        for w in words(folded):
            tf[w] = tf.get(w, 0) + 1
        vec = {w: k * self.idf.get(w, self.default_idf) for w, k in tf.items()}
        return vec, math.sqrt(sum(v * v for v in vec.values()))

    def score(self, text, speaker="", refs=None, limit=5, min_score=0.0):
        """Best candidates for one MCC English text, best first. refs limits the candidates (a mission scope);
        None = every candidate. Returns [] for an empty text."""
        folded = fold(text)
        if not folded:
            return []
        vec, norm = self._vector(folded)
        grams = trigrams(folded)
        spk = speaker_key(speaker)
        pool = self.cands if refs is None else [self.by_ref[r] for r in refs if r in self.by_ref]
        rough = []
        for c in pool:
            dot = sum(v * c.vec.get(w, 0.0) for w, v in vec.items())
            w_cos = dot / (norm * c.norm) if norm and c.norm else 0.0
            dice = 2 * len(grams & c.grams) / (len(grams) + len(c.grams)) if grams and c.grams else 0.0
            rough.append((WEIGHTS["words"] * w_cos + WEIGHTS["chars"] * dice, w_cos, dice, c))
        # difflib is the slow part: only for the best few by the two fast measures.
        rough.sort(key=lambda x: (-x[0], x[3].order))
        out = []
        for _, w_cos, dice, c in rough[:max(limit * 4, 20)]:
            seq = difflib.SequenceMatcher(None, folded, c.folded, autojunk=False).ratio()
            speaker_agrees = same_speaker(spk, c.speaker)
            total = WEIGHTS["words"] * w_cos + WEIGHTS["chars"] * dice + WEIGHTS["sequence"] * seq
            total += SPEAKER_BONUS if speaker_agrees else 0.0  # sorted uncapped: the speaker still breaks a 1.0 tie
            if total < min_score:
                continue
            shared = sorted(set(words(folded)) & set(words(c.folded)),
                            key=lambda w: (-self.idf.get(w, self.default_idf), w))
            out.append({"ce_line_ref": c.ref, "score": round(min(1.0, total), 4), "_rank": total,
                        "parts": {"words": round(w_cos, 4), "chars": round(dice, 4), "sequence": round(seq, 4),
                                  "same_speaker": speaker_agrees},
                        "shared_words": shared[:8], "_order": c.order})
        out.sort(key=lambda x: (-x["_rank"], x["_order"]))
        for x in out:
            del x["_order"], x["_rank"]
        return out[:limit]


# ---------------------------------------------------------------------------------------------------- by name
# Barks (AI combat chatter) have no subtitle on either side: MCC's generic folders have no EN_Halo1.bin entry and CE's
# Systemic voice lines ship no Subtitles text. Both name their sounds by situation, though:
#   MCC  sound\dialog\grunt\conditional\combat2\exclamations\surprise
#   CE   vo_sys_default_01contact_srprs_grunt
# so the name mode compares the MCC leaf (+ its category, at half weight) with the CE record name, after expanding
# CE's abbreviations and folding synonyms to one word. Candidates are CE *records* (a record's variations are takes).
NAME_METHOD = ("suggest-name/1: MCC tag leaf (+category at 0.5) vs CE record name, abbreviations expanded; "
               "0.7 token TF-IDF cosine + 0.3 char-trigram Dice")
NAME_WEIGHTS = {"words": 0.7, "chars": 0.3}
CATEGORY_WEIGHT = 0.5

# CE's abbreviations, as seen in the Systemic record names. Only expansions that are clear from several names.
ABBREV = {
    "srprs": "surprise", "dth": "death", "rtrt": "retreat", "grnd": "grenade", "kllfoe": "kill foe",
    "kll": "kill", "kllally": "kill ally", "cvr": "cover", "brsrk": "berserk", "dwn": "down", "lmnt": "lament",
    "deadally": "dead ally", "thrtn": "threaten", "undr": "under", "incmn": "incoming", "shotfoebdy": "shot foe body",
    "gnr": "gunner", "entervcl": "enter vehicle", "vcl": "vehicle", "foundfoe": "found foe", "lst": "lost",
    "cntct": "contact", "thnk": "thank", "newordr": "new order", "ordr": "order", "scld": "scold", "plr": "player",
    "plsmgrnd": "plasma grenade", "plsm": "plasma", "deadmc": "dead masterchief", "mjr": "major", "thrwn": "thrown",
    "cmnt": "comment", "heardfoe": "heard foe", "morefoe": "more foe", "seefoe": "see foe", "ack": "acknowledge",
    "endcmbt": "end combat", "cmbt": "combat", "gdgrnd": "good grenade", "re": "response", "noncombat": "non combat",
    "cm": "cm", "strk": "strike", "chr": "cheer", "shotfoe": "shot foe",
}
# Different words for one idea, folded to one (after the abbreviations, before the light stemming).
CANON = {
    "enemy": "foe", "enemies": "foe", "foes": "foe", "killed": "kill", "killing": "kill", "kills": "kill",
    "died": "death", "die": "death", "dying": "death", "dead": "death", "sighted": "see", "seen": "see",
    "sleeping": "sleep", "doze": "sleep", "celebration": "cheer", "celebrate": "cheer", "throwing": "throw",
    "falling": "fall", "taunt": "threaten", "hurt": "pain", "hurting": "pain", "damaged": "damage", "friend": "ally",
    "friends": "ally", "uncover": "cover", "fleeing": "flee", "run": "flee", "screaming": "scream",
}
NAME_STOP = {"conditional", "combat", "vo", "sys", "default", "scripted", "script", "actions", "the", "a", "of"}

# MCC's human folders write names run together ('hurtfriendplayer', 'unexpectedenemy', 'fleere'). These words split
# them (segment()): the bark vocabulary of both games' names plus the expansions above.
VOCAB = set("""
hurt friend friends player enemy enemies killed kill kills by flee re nothing there partially sighted unexpected
death agonizing flying quiet violent instant pain major minor body scream screaming falling shooting traitor vehicle
scared blocked block blocking cover uncover group search query new near far old grenade danger self startle throwing
throw celebration taunt idle combat non sleeping sleep alert leader died run away panic dive surprise damaged damage
melee needler plasma sentinel flood mounted weapon retreat stunned stun lost contact found foe charge advance hold order
berserk cower threaten warn incoming shoot shot lament dead ally thank respond response assassinated grabbed thrown
fall down pinned under fire strike good more see heard ambush last standing enter gunner searching betrayed betray
scold me crazy hail bump kamikaze help cm involuntary exclamation exclamations shouting postcombat actions
hurting people killing dying being arms flailing sighting manned ride riding driver passenger turret overheat
reload empty check investigate curse cheer comment acknowledge
""".split()) | {w for v in ABBREV.values() for w in v.split()} | set(CANON) | set(CANON.values())


def segment(word):
    """'hurtfriendplayer' -> ['hurt', 'friend', 'player'] when the whole word splits into VOCAB words (the split with
    the longest words wins); otherwise [word]."""
    if word in VOCAB or len(word) < 6:
        return [word]
    best = {0: (0, [])}  # end -> (score, words): score = sum of squared word lengths
    for end in range(1, len(word) + 1):
        for start in range(max(0, end - 16), end):
            piece = word[start:end]
            if start in best and piece in VOCAB and (len(piece) >= 2 or piece in ("a",)):
                score = best[start][0] + len(piece) ** 2
                if end not in best or score > best[end][0]:
                    best[end] = (score, best[start][1] + [piece])
    return best[len(word)][1] if len(word) in best else [word]


def _stem(w):
    for suf in ("ing", "ed", "es", "s"):
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[:-len(suf)]
    return w


def name_tokens(text):
    """'02combat_kllfoe' -> ['kill', 'foe']; 'grenade_throwing' -> ['grenade', 'throw']. Digits are dropped
    ('combat2', CE's '01' ordering prefixes)."""
    out = []
    for raw in re.findall(r"[a-z]+", fold(text).replace(" ", "_")):
        words = ABBREV[raw].split() if raw in ABBREV else segment(raw)
        for w in (x for part in words for x in ABBREV.get(part, part).split()):
            w = CANON.get(w, w)
            w = CANON.get(_stem(w), _stem(w))
            if w not in NAME_STOP:
                out.append(w)
    return out


def mcc_name_parts(mcc_tag, level):
    """(leaf, category) of an MCC tag below its level folder: 'conditional/combat2/exclamations/surprise' ->
    ('surprise', 'conditional combat2 exclamations')."""
    parts = re.split(r"[\\/]", mcc_tag)
    if level in parts:
        parts = parts[parts.index(level) + 1:]
    return parts[-1], " ".join(parts[:-1])


def ce_record_name(display_key, character=""):
    """'vo_sys_default_01contact_srprs_grunt' -> '01contact_srprs' (prefix and the character's suffix dropped)."""
    name = re.sub(r"^vo_sys_(default_)?", "", display_key, flags=re.I)
    if character and name.lower().endswith("_" + character.lower()):
        name = name[:-len(character) - 1]
    return name


class NameIndex:
    """CE records by name. items = [(ref, name, group)] in catalog order; ref = the record's first line ref; group
    = what score() may be limited to (the CE character folder)."""

    def __init__(self, items):
        self.items = []
        df = {}
        for i, (ref, name, group) in enumerate(items):
            toks = name_tokens(name)
            if not toks:
                continue
            self.items.append({"ref": ref, "name": name, "group": group, "order": i, "tokens": toks,
                               "grams": trigrams(" ".join(toks))})
            for w in set(toks):
                df[w] = df.get(w, 0) + 1
        n = len(self.items)
        self.idf = {w: math.log((1 + n) / (1 + k)) + 1.0 for w, k in df.items()}
        self.default_idf = math.log(1 + n) + 1.0
        for it in self.items:
            it["vec"], it["norm"] = self._vector({w: 1.0 for w in it["tokens"]})

    def _vector(self, weights):
        vec = {w: k * self.idf.get(w, self.default_idf) for w, k in weights.items()}
        return vec, math.sqrt(sum(v * v for v in vec.values()))

    def score(self, leaf, category="", groups=None, limit=5):
        """Best CE records for an MCC sound name, best first. groups limits the candidates (CE folders)."""
        leaf_t, cat_t = name_tokens(leaf), name_tokens(category)
        if not leaf_t:
            return []
        weights = {}
        for w in cat_t:
            weights[w] = max(weights.get(w, 0.0), CATEGORY_WEIGHT)
        for w in leaf_t:
            weights[w] = 1.0
        vec, norm = self._vector(weights)
        grams = trigrams(" ".join(leaf_t))
        out = []
        for it in self.items:
            if groups is not None and it["group"] not in groups:
                continue
            dot = sum(v * it["vec"].get(w, 0.0) for w, v in vec.items())
            cos = dot / (norm * it["norm"]) if norm and it["norm"] else 0.0
            dice = 2 * len(grams & it["grams"]) / (len(grams) + len(it["grams"])) if grams and it["grams"] else 0.0
            total = NAME_WEIGHTS["words"] * cos + NAME_WEIGHTS["chars"] * dice
            if total <= 0:
                continue
            shared = sorted(set(weights) & set(it["tokens"]), key=lambda w: (-weights[w], w))
            out.append({"ce_line_ref": it["ref"], "score": round(min(1.0, total), 4), "_rank": total,
                        "_order": it["order"], "parts": {"words": round(cos, 4), "chars": round(dice, 4),
                                                         "sequence": None, "same_speaker": False},
                        "shared_words": shared[:8], "expanded": " ".join(it["tokens"])})
        out.sort(key=lambda x: (-x["_rank"], x["_order"]))
        for x in out:
            del x["_order"], x["_rank"]
        return out[:limit]
