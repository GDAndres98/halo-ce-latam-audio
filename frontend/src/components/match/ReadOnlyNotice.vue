<script setup lang="ts">
// In place of the save bar in the public read-only view (docs/public-access.md): says what this view is and
// where editing happens. There is nothing to save here, so no Save or Approve control is shown at all.

import { Eye, LogIn } from "lucide-vue-next";
import { session } from "../../auth/session";
</script>

<template>
  <section class="readonly-notice action-band" aria-label="Read-only view" data-section="save" data-testid="readonly-notice">
    <p>
      <Eye :size="16" aria-hidden="true" />
      <strong>Read-only view.</strong>
      You can browse every line, its matching decision, subtitles, flags and approvals. Saving, approving,
      listening and downloads are limited to the project owner.
    </p>
    <a v-if="session.info?.sign_in_url" class="button icon-label" :href="session.info.sign_in_url" rel="noopener">
      <LogIn :size="15" aria-hidden="true" /> Sign in to edit
    </a>
  </section>
</template>

<style scoped>
.readonly-notice {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
}

.readonly-notice p {
  margin: 0;
  flex: 1 1 18rem;
}

.readonly-notice p svg {
  vertical-align: -3px;
  margin-right: 0.25rem;
}
</style>
