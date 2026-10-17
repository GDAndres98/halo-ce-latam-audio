<script setup lang="ts">
// Public read-only view (docs/public-access.md §2.1): the line's published edited LATAM preview, i.e. the
// approved Campaign Evolved replacement rendered with its saved recipe (trims, cuts, fades, radio, echo,
// interference, the export gain) exactly as the build renders it. Only approved lines are published, and only
// while unchanged; the server decides (public_previews.py). The browser's own player: play, pause, seek, replay,
// on desktop and phone. Its download menu is turned off, which hides a button but cannot stop recording.

import { Headphones } from "lucide-vue-next";
import type { PublicPreview } from "../../api/types";

defineProps<{ preview: PublicPreview | null }>();
</script>

<template>
  <section class="block public-preview" aria-label="Edited LATAM preview" data-section="preview" data-testid="public-preview">
    <h3><Headphones :size="15" aria-hidden="true" /> Edited LATAM preview</h3>
    <template v-if="preview?.available && preview.url">
      <audio
        class="preview-player" :src="preview.url" controls preload="none"
        controlslist="nodownload noplaybackrate" data-testid="public-preview-player"
        aria-label="Play the edited LATAM preview" @contextmenu.prevent
      ></audio>
      <p class="small muted">The approved replacement as the game will play it, with its edits applied.</p>
    </template>
    <p v-else class="muted" data-testid="public-preview-unavailable">
      Preview unavailable: {{ preview?.reason ?? "no preview has been published for this line yet" }}.
    </p>
  </section>
</template>

<style scoped>
.preview-player {
  width: 100%;
  max-width: 34rem;
  display: block;
  margin: 0.25rem 0;
}
</style>
