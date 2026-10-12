<script setup lang="ts">
// Sign-in for the remote address (another computer on the LAN or through Tailscale). The host computer's own
// address never shows this. Accounts are made on the host with scripts/ui/studio_users.py.

import { KeyRound, LogIn, ShieldAlert } from "lucide-vue-next";
import { ref } from "vue";
import { ApiError } from "../api/client";
import { session, signIn } from "../auth/session";
import PanelHeader from "../components/ui/PanelHeader.vue";
import StateMessage from "../components/ui/StateMessage.vue";

const username = ref("");
const password = ref("");
const busy = ref(false);
const error = ref("");

async function submit() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    await signIn(username.value.trim(), password.value);
    password.value = "";
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : String(e);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="login-view">
    <form class="panel login-panel" aria-labelledby="login-title" @submit.prevent="submit">
      <PanelHeader title="Sign in" title-id="login-title" :icon="KeyRound" />
      <p class="small muted">
        This Studio runs on the host computer. Sign in with the account its owner made for you.
      </p>
      <StateMessage v-if="session.reason" kind="warning" class="small">{{ session.reason }}</StateMessage>
      <label class="field">
        <span>User name</span>
        <input v-model="username" name="username" autocomplete="username" autocapitalize="none" spellcheck="false" required />
      </label>
      <label class="field">
        <span>Password</span>
        <input v-model="password" name="password" type="password" autocomplete="current-password" required />
      </label>
      <StateMessage v-if="error" kind="error" class="small">{{ error }}</StateMessage>
      <p v-if="session.info && !session.info.https" class="small warn insecure">
        <ShieldAlert :size="14" aria-hidden="true" />
        This connection is not encrypted. Use it only on a network you trust, or connect through Tailscale
        (HTTPS) instead.
      </p>
      <button type="submit" class="primary icon-label" :disabled="busy || !username || !password">
        <LogIn :size="16" aria-hidden="true" /> {{ busy ? "Signing in…" : "Sign in" }}
      </button>
    </form>
  </section>
</template>
