<script setup lang="ts">
// A new version of the Studio is ready (the host was updated and rebuilt). It is used when the user chooses
// Reload, or the next time the app opens: never by itself in the middle of an edit.
import { RefreshCw } from "lucide-vue-next";
import { applyUpdate, pwa } from "../pwa";
</script>

<template>
  <div v-if="pwa.needRefresh" class="pwa-banner" role="status" data-testid="pwa-update">
    <span>A new version of the Studio is available. Unsaved edits are kept.</span>
    <button type="button" class="primary icon-label" @click="applyUpdate">
      <RefreshCw :size="15" aria-hidden="true" /> Reload
    </button>
  </div>
</template>
