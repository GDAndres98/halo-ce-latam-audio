<script setup lang="ts">
// Suggestions (owner, 2026-10-23; docs/suggested-matching.md): for each MCC sound of a level, the Campaign Evolved
// lines whose English subtitle reads most like the MCC English subtitle, with the score and why. Sounds with no
// English subtitle (AI barks) are compared by name instead: the MCC tag name against CE record names, in CE's
// Systemic folder for the same character. Optionally, Claude re-ranks one sound's shortlist, or matches a whole bark
// folder in one request, with a verdict and a reason.
//
// Read-only. Nothing here saves, selects or approves anything: "Open in Matching" opens the MCC line, with the CE
// list filtered to the suggested line, and the owner decides there as always.

import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ExternalLink, RefreshCw, Sparkles } from "lucide-vue-next";
import { api, ApiError, audioUrl } from "../api/client";
import type { AiPick, SuggestCandidate, SuggestResponse, SuggestSound } from "../api/types";
import { canListen, permissions } from "../auth/session";
import AudioButton from "../components/AudioButton.vue";
import StatusBadge from "../components/StatusBadge.vue";
import PageHeader from "../components/ui/PageHeader.vue";
import PanelHeader from "../components/ui/PanelHeader.vue";
import StateMessage from "../components/ui/StateMessage.vue";

const route = useRoute();
const router = useRouter();

const levels = ref<string[]>([]);
const missions = ref<string[]>([]);
const data = ref<SuggestResponse | null>(null);
const busy = ref(false);
const error = ref("");
/** Claude's answer per MCC sound: from that sound's own request, or from the folder request. */
interface AiAnswer { ranking: AiPick[]; model: string; cached: boolean; source: "sound" | "folder" }
const ai = ref<Record<string, AiAnswer>>({});
const aiBusy = ref<string | null>(null);
const aiError = ref<Record<string, string>>({});
const folderMessage = ref("");
const folderError = ref("");

const param = (name: string, fallback: string) => String(route.query[name] ?? fallback);
const setQuery = (changes: Record<string, string>) => router.replace({ query: { ...route.query, ...changes } });
const level = computed({ get: () => param("level", "a10"), set: (v: string) => setQuery({ level: v }) });
const scope = computed({ get: () => param("scope", "mapped"), set: (v: string) => setQuery({ scope: v }) });
const show = computed({
  get: () => (param("show", "undecided") === "all" ? "all" : "undecided"),
  set: (v: string) => setQuery({ show: v }),
});
/** Barks: the CE folder to compare with ("" = the one named like the level, "all" = every folder in scope). */
const character = computed({ get: () => param("character", ""), set: (v: string) => setQuery({ character: v }) });

const canAskAi = computed(() => Boolean(permissions.value.admin) && Boolean(data.value?.ai.sdk_installed));
const aiHelp = computed(() => {
  if (!data.value) return "";
  if (!data.value.ai.sdk_installed) return "The Claude re-rank needs the anthropic Python package on the host (pip install anthropic).";
  if (!permissions.value.admin) return "Asking Claude calls a paid API: it needs an admin account.";
  return `Ask ${data.value.ai.model} to judge this shortlist (answers are cached; the same question is not paid twice).`;
});

const VERDICT: Record<string, { label: string; tone: "ok" | "warn" | "bad" | "muted" }> = {
  same_line: { label: "same line", tone: "ok" },
  reworded: { label: "reworded", tone: "ok" },
  related: { label: "related", tone: "warn" },
  different: { label: "different", tone: "muted" },
};
// Barks are judged by situation, not wording: same verdicts, other words.
const VERDICT_NAME: Record<string, string> = {
  same_line: "same situation", reworded: "close situation", related: "related", different: "different",
};
const verdictLabel = (s: SuggestSound, v: string) => (s.mode === "name" ? VERDICT_NAME[v] : VERDICT[v]?.label) ?? v;
const ASSESSMENT: Record<string, { label: string; tone: "ok" | "warn" | "bad" | "muted" }> = {
  same_recordings: { label: "same recordings", tone: "ok" },
  split: { label: "split over several CE records", tone: "warn" },
  partial: { label: "partly matched", tone: "warn" },
  no_counterpart: { label: "no CE recording", tone: "muted" },
};
const REVIEW_VERDICT: Record<string, string> = {
  same_line: "same recordings", reworded: "close", related: "situation only", different: "different",
};

const describe = (e: unknown) =>
  e instanceof ApiError ? `${e.message}${e.details.length ? `: ${e.details.join("; ")}` : ""}` : String(e);

let loadSeq = 0;
async function load() {
  const seq = ++loadSeq; // filters changed while a request was out: only the newest answer is shown
  busy.value = true;
  error.value = "";
  try {
    const r = await api.suggest({ level: level.value, scope: scope.value, show: show.value as "undecided" | "all",
                                  character: character.value || undefined });
    if (seq === loadSeq) data.value = r;
  } catch (e) {
    if (seq === loadSeq) error.value = describe(e);
  } finally {
    if (seq === loadSeq) busy.value = false;
  }
}

async function askAi(s: SuggestSound) {
  aiBusy.value = s.mcc_tag;
  aiError.value = { ...aiError.value, [s.mcc_tag]: "" };
  try {
    const r = await api.suggestRerank(s.mcc_tag, scope.value, character.value || undefined);
    ai.value = { ...ai.value, [s.mcc_tag]: { ranking: r.ranking, model: r.model, cached: r.cached, source: "sound" } };
  } catch (e) {
    aiError.value = { ...aiError.value, [s.mcc_tag]: describe(e) };
  } finally {
    aiBusy.value = null;
  }
}

async function askFolder() {
  aiBusy.value = "folder";
  folderError.value = "";
  folderMessage.value = "";
  try {
    const r = await api.suggestFolder(level.value, scope.value, character.value || undefined);
    const next = { ...ai.value };
    for (const [tag, picks] of Object.entries(r.sounds)) next[tag] = { ranking: picks, model: r.model, cached: r.cached, source: "folder" };
    ai.value = next;
    folderMessage.value = `Claude matched ${Object.keys(r.sounds).length} of ${r.mcc_sounds} sounds against ` +
      `${r.ce_records} CE records (${r.scope_note})${r.cached ? ", cached answer" : ""}.`;
  } catch (e) {
    folderError.value = describe(e);
  } finally {
    aiBusy.value = null;
  }
}

/** Matching with the MCC line open and the CE list searched for the suggested line (a filter, not a choice). */
const matchLink = (s: SuggestSound, c?: SuggestCandidate) => ({
  path: "/match",
  query: {
    level: s.level,
    ...(s.first_slot_id ? { slot: s.first_slot_id } : {}),
    ...(c ? { cm: c.mission, cq: c.display_key } : {}),
  },
});

// Words both texts share are highlighted (folded like the server: case and accents ignored).
const foldWord = (w: string) => w.normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase();
function pieces(text: string | null, shared: string[]) {
  const set = new Set(shared);
  return (text ?? "").split(/([\p{L}\p{N}]+)/u).map((t) => ({ t, hit: set.has(foldWord(t)) }));
}
const pct = (x: number) => `${Math.round(x * 100)}%`;
const partsTitle = (c: SuggestCandidate) =>
  [`words ${pct(c.parts.words)}`, `characters ${pct(c.parts.chars)}`,
   c.parts.sequence !== null ? `sequence ${pct(c.parts.sequence)}` : "", c.parts.same_speaker ? "same speaker" : ""]
    .filter(Boolean).join(" · ");
const hasBarks = computed(() => (data.value?.counts.by_name ?? 0) + (data.value?.counts.by_audio ?? 0) > 0);
const folderBarks = computed(() => (data.value?.sounds ?? []).filter((s) => s.mode !== "text").length);
/** "variation 3 of the record" for a CE line ref (record_id#2). */
const variationNo = (ref: string) => Number(ref.split("#").pop() ?? 0) + 1;
const takeNo = (s: SuggestSound, index: number) => s.english_takes.indexOf(index) + 1;
const gain = (db: number | null) => (db === null ? "" : ` · ${db > 0 ? "+" : ""}${db} dB`);
const usedLabel = (c: SuggestCandidate) => `already used by ${c.used_by.join(", ")}`;

watch(() => [route.query.level, route.query.scope, route.query.show, route.query.character], () => {
  if (route.name === "suggest") void load();
});

onMounted(async () => {
  try {
    const st = await api.state();
    levels.value = st.levels.map((l) => l.level);
    missions.value = st.missions.map((m) => m.mission);
  } catch (e) {
    error.value = describe(e);
  }
  await load();
});
</script>

<template>
  <section class="suggest-view">
    <PageHeader title="Suggestions" :icon="Sparkles">
      <button type="button" class="icon-label" :disabled="busy" @click="load">
        <RefreshCw :size="15" aria-hidden="true" /> Check again
      </button>
    </PageHeader>
    <p class="note">
      For each MCC sound, the Campaign Evolved lines whose <strong>English</strong> subtitle reads most like MCC's
      English subtitle. Sounds with no English subtitle (AI barks) are compared <strong>by sound</strong>: each MCC
      English take against Campaign Evolved's English variations, ignoring volume (many are the same recording). Barks
      that were not compared by sound are compared <strong>by name</strong>, with CE's abbreviations spelled out.
      Every take and variation can be played. This page only reads: nothing is saved, selected or approved here. Open
      a line in Matching and decide there as usual.
    </p>

    <div class="row filters">
      <label>Level
        <select v-model="level" data-testid="suggest-level">
          <option v-for="l in levels" :key="l" :value="l">{{ l }}</option>
        </select>
      </label>
      <label>CE lines from
        <select v-model="scope" data-testid="suggest-scope">
          <option value="mapped">the level's missions</option>
          <option value="all">every mission</option>
          <option v-for="m in missions" :key="m" :value="m">{{ m }}</option>
        </select>
      </label>
      <label>Show
        <select v-model="show" data-testid="suggest-show">
          <option value="undecided">sounds without a match decision</option>
          <option value="all">every sound</option>
        </select>
      </label>
      <span v-if="data?.character_map" class="small" data-testid="character-map"
            title="config/suggest_characters.json: this MCC folder is compared only with these CE folders">
        CE folders (your character map): <strong>{{ data.character_map.join(", ") }}</strong>
      </span>
      <label v-else-if="hasBarks" title="Barks are compared with one CE Systemic folder (a character)">CE folder for barks
        <select v-model="character" data-testid="suggest-character">
          <option value="">{{ data?.character ? `${data.character} (named like ${level})` : "every folder (none named like this level)" }}</option>
          <option value="all">every folder</option>
          <option v-for="f in data?.characters ?? []" :key="f" :value="f">{{ f }}</option>
        </select>
      </label>
    </div>

    <StateMessage v-if="busy && !data" kind="loading">Comparing English subtitles…</StateMessage>
    <StateMessage v-if="error" kind="error" class="small">{{ error }}</StateMessage>

    <template v-if="data">
      <p class="small muted" data-testid="suggest-summary">
        {{ data.counts.listed }} of {{ data.counts.sounds }} sounds listed · {{ data.counts.decided }} with a match
        decision ·
        <span :title="data.method">{{ data.counts.by_text }} by English text ({{ data.counts.ce_lines_in_scope }} CE
          lines, {{ data.scope_note }})</span> ·
        <span v-if="data.counts.by_audio" :title="data.audio_match?.method ?? ''">{{ data.counts.by_audio }} by sound
          (English audio, compared {{ data.audio_match?.built_at }}) · </span>
        <span :title="data.name_method">{{ data.counts.by_name }} by name ({{ data.counts.ce_records_in_name_scope }} CE
          records, {{ data.name_scope_note }})</span>.
      </p>
      <details v-if="data.review" class="review-notes small" data-testid="review-notes">
        <summary>Reviewed by {{ data.review.reviewer }} on {{ data.review.reviewed_at }}
          <template v-if="data.review.stale"> (made with an older audio comparison)</template></summary>
        <p class="muted">{{ data.review.basis }}</p>
        <ul><li v-for="(n, i) in data.review.notes" :key="i">{{ n }}</li></ul>
      </details>
      <p v-if="hasBarks && data.audio_match && !data.audio_match.built_at" class="small muted" data-testid="audio-hint">
        Barks can also be compared by their English audio with {{ data.audio_match.folder }}: on the host, run
        <code>{{ data.audio_match.command }}</code>, then Check again.
      </p>
      <div v-if="hasBarks" class="row ai">
        <button type="button" class="icon-label small" :disabled="!canAskAi || aiBusy !== null || !folderBarks"
                :title="aiHelp" data-testid="ask-claude-folder" @click="askFolder">
          <Sparkles :size="14" aria-hidden="true" />
          {{ aiBusy === "folder" ? "Asking Claude about the folder…" : `Ask Claude to match all ${data.counts.by_name + data.counts.by_audio} barks of ${level} by name` }}
        </button>
        <span class="small muted">One request: every bark of the level against the CE records in scope.</span>
      </div>
      <StateMessage v-if="folderMessage" kind="success" class="small">{{ folderMessage }}</StateMessage>
      <StateMessage v-if="folderError" kind="error" class="small">{{ folderError }}</StateMessage>
      <StateMessage v-if="!data.sounds.length" kind="empty">
        Nothing to suggest here{{ show === "undecided" ? ": every sound with English text already has a match decision" : "" }}.
      </StateMessage>

      <section v-for="s in data.sounds" :key="s.mcc_tag" class="panel sound" :data-sound="s.mcc_tag">
        <PanelHeader :title="s.tag_name" :icon="Sparkles">
          <StatusBadge v-if="s.own_set" label="replacement set" tone="ok" />
          <StatusBadge v-else-if="s.decided" label="has a match decision" tone="muted" />
          <RouterLink :to="matchLink(s)" class="icon-label small" title="Open this sound's first take in Matching">
            <ExternalLink :size="14" aria-hidden="true" /> Open
          </RouterLink>
        </PanelHeader>

        <div class="mcc">
          <template v-if="s.mode !== 'text'">
            <div class="mcc-line">
              <span class="lang" :title="s.mode === 'audio' ? 'Compared by its English audio' : 'Compared by name'">
                {{ s.mode === "audio" ? "SOUND" : "NAME" }}</span>
              <span class="text"><span class="muted">{{ s.category }} › </span><strong>{{ s.name }}</strong></span>
            </div>
            <div v-if="canListen" class="mcc-line takes small" data-testid="mcc-takes">
              <span class="lang">EN</span>
              <AudioButton v-for="(idx, i) in s.english_takes" :key="`en${idx}`" :url="audioUrl.mcc(s.level, 'english', idx)"
                           :label="String(i + 1)" :title="`MCC English take ${i + 1}`" />
            </div>
            <div v-if="canListen" class="mcc-line takes small">
              <span class="lang">ES</span>
              <AudioButton v-for="(idx, i) in s.spanish_takes" :key="`es${idx}`" :url="audioUrl.mcc(s.level, 'spanish', idx)"
                           :label="String(i + 1)" :title="`MCC Spain take ${i + 1}`" />
            </div>
          </template>
          <div v-else class="mcc-line">
            <span class="lang">EN</span>
            <span class="speaker" v-if="s.english_speaker || s.speaker">{{ s.english_speaker ?? s.speaker }}</span>
            <span class="text">{{ s.english }}</span>
            <AudioButton v-if="canListen && s.english_index !== null"
                         :url="audioUrl.mcc(s.level, 'english', s.english_index)" label="EN" title="MCC English" />
          </div>
          <div v-if="s.mode === 'text'" class="mcc-line muted small">
            <span class="lang">SU</span><span class="text">{{ s.su ?? "—" }}</span>
            <AudioButton v-if="canListen && s.spanish_index !== null"
                         :url="audioUrl.mcc(s.level, 'spanish', s.spanish_index)" label="ES" title="MCC Spain" />
          </div>
        </div>

        <div v-if="s.review" class="review" data-testid="sound-review">
          <div class="review-head">
            <strong>Claude's review</strong>
            <StatusBadge :label="ASSESSMENT[s.review.assessment]?.label ?? s.review.assessment"
                         :tone="ASSESSMENT[s.review.assessment]?.tone ?? 'muted'" />
            <span class="small">{{ s.review.summary }}</span>
          </div>
          <div v-for="p in s.review.picks" :key="p.ce_line_ref" class="review-pick small" :data-ref="p.ce_line_ref">
            <StatusBadge :label="REVIEW_VERDICT[p.verdict] ?? p.verdict" :tone="p.verdict === 'same_line' ? 'ok' : 'muted'" />
            <span class="mono">{{ p.name }}</span>
            <span class="muted">{{ pct(p.confidence) }}</span>
            <template v-if="canListen && p.english_takes.length">
              <span class="muted">MCC takes</span>
              <AudioButton v-for="idx in p.english_takes" :key="idx" :url="audioUrl.mcc(s.level, 'english', idx)"
                           :label="String(takeNo(s, idx))" :title="`MCC English take ${takeNo(s, idx)}`" />
            </template>
            <span>{{ p.reason }}</span>
            <RouterLink :to="matchLink(s, p)" class="icon-label small" title="Open in Matching, with the CE list filtered to this record">
              <ExternalLink :size="12" aria-hidden="true" /> Open
            </RouterLink>
          </div>
          <div v-if="!s.review.picks.length" class="small muted">No pick.</div>
        </div>

        <div v-if="s.audio_candidates?.length" class="review" data-testid="same-recording">
          <div class="review-head"><strong>Same English recording in CE</strong>
            <span class="small muted">compared by sound, not by text</span></div>
          <div v-for="c in s.audio_candidates" :key="c.ce_line_ref" class="review-pick small" :data-ref="c.ce_line_ref">
            <span class="mono">{{ c.display_key }}</span>
            <span class="muted">{{ c.mission }} · {{ c.audio?.takes_matched }} of {{ c.audio?.takes }} take(s) · {{ pct(c.score) }}</span>
            <template v-for="p in c.audio?.pairs ?? []" :key="p.english_index">
              <AudioButton v-if="canListen" :url="audioUrl.mcc(s.level, 'english', p.english_index)"
                           :label="`MCC ${takeNo(s, p.english_index)}`" :title="`MCC English take ${takeNo(s, p.english_index)}`" />
              ≈
              <AudioButton v-if="canListen" :url="audioUrl.ce(p.ce_line_ref, 'English(US)')"
                           :label="`CE ${variationNo(p.ce_line_ref)}`" :title="`CE English variation ${variationNo(p.ce_line_ref)}`" />
              <span class="muted">{{ gain(p.gain_db).replace(' · ', '') }}</span>
            </template>
            <AudioButton v-if="canListen && c.has_es_mx_audio" :url="audioUrl.ce(c.ce_line_ref, 'Spanish(Mexico)')"
                         label="MX" title="Campaign Evolved es-MX" />
            <RouterLink :to="matchLink(s, c)" class="icon-label small" title="Open in Matching, with the CE list filtered to this line">
              <ExternalLink :size="12" aria-hidden="true" /> Open
            </RouterLink>
          </div>
        </div>

        <div class="table-frame"><table>
          <thead><tr><th>Score</th><th>Campaign Evolved {{ s.mode === "text" ? "line" : "record" }}</th>
            <th>{{ s.mode === "audio" ? "Takes that sound the same" : s.mode === "name" ? "Name, spelled out" : "English / es-MX" }}</th>
            <th></th></tr></thead>
          <tbody>
            <tr v-for="c in s.candidates" :key="c.ce_line_ref" :data-ref="c.ce_line_ref">
              <td class="score" :title="partsTitle(c)">
                <span class="bar"><span :style="{ width: pct(c.score) }"></span></span>
                {{ pct(c.score) }}
              </td>
              <td class="mono small">
                {{ c.display_key }}<br />
                <span class="muted">{{ c.mission }}<template v-if="c.parts.same_speaker"> · same speaker</template></span>
                <span v-if="c.used_by.length" class="used" :title="usedLabel(c)"> · used</span>
              </td>
              <td v-if="s.mode === 'audio' && c.audio" class="small" data-testid="audio-pairs">
                <div><strong>{{ c.audio.takes_matched }} of {{ c.audio.takes }}</strong> English takes ·
                  {{ c.variations }} variation(s)</div>
                <div v-for="p in c.audio.pairs" :key="p.english_index" class="pair">
                  <AudioButton v-if="canListen" :url="audioUrl.mcc(s.level, 'english', p.english_index)"
                               :label="`MCC ${takeNo(s, p.english_index)}`" :title="`MCC English take ${takeNo(s, p.english_index)}`" />
                  ≈
                  <AudioButton v-if="canListen" :url="audioUrl.ce(p.ce_line_ref, 'English(US)')"
                               :label="`CE ${variationNo(p.ce_line_ref)}`" :title="`CE English variation ${variationNo(p.ce_line_ref)}`" />
                  <span class="muted">{{ pct(p.score) }}{{ gain(p.gain_db) }}</span>
                </div>
              </td>
              <td v-else-if="s.mode === 'name'" class="small">
                <div class="mono">{{ c.name }}</div>
                <div><template v-for="(p, i) in pieces(c.expanded ?? '', c.shared_words)" :key="i"><mark v-if="p.hit">{{ p.t }}</mark><template v-else>{{ p.t }}</template></template></div>
                <div class="muted">{{ c.variations }} variation(s){{ c.folder ? ` · ${c.folder}` : "" }}</div>
              </td>
              <td v-else class="small">
                <div><template v-for="(p, i) in pieces(c.english, c.shared_words)" :key="i"><mark v-if="p.hit">{{ p.t }}</mark><template v-else>{{ p.t }}</template></template></div>
                <div class="muted">{{ c.es_mx ?? "(no es-MX subtitle)" }}</div>
              </td>
              <td class="actions">
                <details v-if="canListen && c.variations > 1 && s.mode !== 'text'" class="variations">
                  <summary>{{ c.variations }} variations</summary>
                  <div v-for="v in c.variation_refs" :key="v.ce_line_ref" class="variation">
                    <span class="muted">{{ variationNo(v.ce_line_ref) }}</span>
                    <AudioButton v-if="v.en" :url="audioUrl.ce(v.ce_line_ref, 'English(US)')" label="EN"
                                 :title="`CE English variation ${variationNo(v.ce_line_ref)}`" />
                    <AudioButton v-if="v.mx" :url="audioUrl.ce(v.ce_line_ref, 'Spanish(Mexico)')" label="MX"
                                 :title="`CE es-MX variation ${variationNo(v.ce_line_ref)}`" />
                  </div>
                </details>
                <template v-else>
                  <AudioButton v-if="canListen && c.variation_refs[0]?.en" :url="audioUrl.ce(c.ce_line_ref, 'English(US)')"
                               label="EN" title="Campaign Evolved English" />
                  <AudioButton v-if="canListen && c.has_es_mx_audio" :url="audioUrl.ce(c.ce_line_ref, 'Spanish(Mexico)')"
                               label="MX" title="Campaign Evolved es-MX" />
                </template>
                <RouterLink :to="matchLink(s, c)" class="icon-label small"
                            title="Open in Matching, with the CE list filtered to this line">
                  <ExternalLink :size="14" aria-hidden="true" /> Open
                </RouterLink>
              </td>
            </tr>
          </tbody>
        </table></div>
        <StateMessage v-if="!s.candidates.length" kind="empty">
          No CE {{ s.mode === "name" ? "record in scope shares a word with this name" : "line in scope shares anything with this text" }}.
        </StateMessage>

        <div class="row ai">
          <button type="button" class="icon-label small" :disabled="!canAskAi || aiBusy !== null || !s.candidates.length"
                  :title="aiHelp" data-testid="ask-claude" @click="askAi(s)">
            <Sparkles :size="14" aria-hidden="true" />
            {{ aiBusy === s.mcc_tag ? "Asking Claude…" : ai[s.mcc_tag] ? "Ask Claude again" : "Ask Claude" }}
          </button>
          <span v-if="!canAskAi" class="small muted">{{ aiHelp }}</span>
        </div>
        <StateMessage v-if="aiError[s.mcc_tag]" kind="error" class="small">{{ aiError[s.mcc_tag] }}</StateMessage>
        <ol v-if="ai[s.mcc_tag]" class="ai-ranking small" data-testid="ai-ranking">
          <li v-for="r in ai[s.mcc_tag].ranking" :key="r.ce_line_ref">
            <StatusBadge :label="verdictLabel(s, r.verdict)" :tone="VERDICT[r.verdict]?.tone ?? 'muted'" />
            <span class="mono">{{ s.mode === "name" ? r.name : r.display_key }}</span> · {{ pct(r.confidence) }} · {{ r.reason }}
            <RouterLink :to="matchLink(s, r)" class="icon-label small" title="Open in Matching, with the CE list filtered to this line">
              <ExternalLink :size="12" aria-hidden="true" /> Open
            </RouterLink>
          </li>
          <li v-if="!ai[s.mcc_tag].ranking.length" class="muted">Claude found nothing that fits.</li>
          <li class="muted meta">
            {{ ai[s.mcc_tag].model }}{{ ai[s.mcc_tag].source === "folder" ? " · from the folder request" : "" }}{{ ai[s.mcc_tag].cached ? " · cached answer" : "" }}
          </li>
        </ol>
      </section>
    </template>
  </section>
</template>

<style scoped>
.filters label {
  display: inline-flex;
  gap: 0.4rem;
  align-items: center;
  margin-right: 1rem;
}
.sound {
  margin-top: 0.75rem;
}
/* Long sound names and the badge + Open wrap on a phone instead of widening the page. */
.sound :deep(.panel-head) {
  flex-wrap: wrap;
  min-width: 0;
}
.sound :deep(.panel-head h2) {
  min-width: 0;
  overflow-wrap: anywhere;
}
.filters {
  flex-wrap: wrap;
}
.filters select {
  max-width: 100%;
}
.mcc {
  margin: 0.4rem 0 0.6rem;
}
.mcc-line {
  display: flex;
  gap: 0.5rem;
  align-items: baseline;
  flex-wrap: wrap;
}
.lang {
  font-weight: 600;
  opacity: 0.7;
  min-width: 1.6rem;
}
.speaker {
  text-transform: uppercase;
  opacity: 0.7;
  font-size: 0.85em;
}
.text {
  flex: 1 1 16rem;
  overflow-wrap: anywhere;
}
.score {
  white-space: nowrap;
}
.bar {
  display: inline-block;
  width: 3rem;
  height: 0.4rem;
  margin-right: 0.35rem;
  border: 1px solid var(--frame, currentColor);
  vertical-align: middle;
}
.bar > span {
  display: block;
  height: 100%;
  background: var(--accent, currentColor);
}
.used {
  color: var(--warn, #b7791f);
}
.actions {
  white-space: nowrap;
}
.takes {
  flex-wrap: wrap;
  gap: 0.3rem;
}
.pair,
.variation {
  display: flex;
  gap: 0.35rem;
  align-items: center;
  flex-wrap: wrap;
  margin-top: 0.2rem;
}
.review {
  margin: 0 0 0.6rem;
  padding: 0.5rem 0.6rem;
  border: 1px solid var(--frame-dim, currentColor);
  border-radius: var(--radius, 4px);
}
.review-head,
.review-pick {
  display: flex;
  gap: 0.4rem;
  align-items: center;
  flex-wrap: wrap;
}
.review-pick {
  margin-top: 0.3rem;
}
.review-notes summary,
.variations summary {
  cursor: pointer;
}
.variations[open] {
  white-space: normal;
}
mark {
  background: transparent;
  color: inherit;
  font-weight: 700;
  text-decoration: underline;
}
.ai {
  margin-top: 0.5rem;
}
.ai-ranking li {
  margin: 0.2rem 0;
}
.ai-ranking .meta {
  list-style: none;
}
</style>
