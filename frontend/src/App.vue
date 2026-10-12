<script setup lang="ts">
import { AudioLines, Database, ExternalLink, Hammer, LayoutDashboard, LogOut, Network, UserRound } from "lucide-vue-next";
import { onMounted, watch } from "vue";
import { RouterLink, RouterView, useRoute } from "vue-router";
import { loadSession, session, signedIn, signOut } from "./auth/session";
import { startLiveUpdates, stopLiveUpdates } from "./live/changes";
import AppBackdrop from "./components/AppBackdrop.vue";
import AppEmblem from "./components/AppEmblem.vue";
import ConfirmDialog from "./components/ui/ConfirmDialog.vue";
import StateMessage from "./components/ui/StateMessage.vue";
import LoginView from "./views/LoginView.vue";

const route = useRoute();
// The classic page is served by the API server on the host only (the dev server does not forward it).
const classicUrl = import.meta.env.DEV ? "http://127.0.0.1:8765/classic" : "/classic";

onMounted(loadSession);
watch(signedIn, (yes) => (yes ? startLiveUpdates() : stopLiveUpdates()), { immediate: true });
</script>

<template>
  <AppBackdrop />
  <header class="top">
    <RouterLink to="/" class="brand" aria-label="Localization Studio: dashboard">
      <AppEmblem :size="32" />
      <span class="wordmark">
        <strong>Localization Studio</strong>
        <span>Halo CE · MCC · Español LATAM</span>
      </span>
    </RouterLink>
    <nav v-if="signedIn" aria-label="Main">
      <RouterLink to="/"><LayoutDashboard :size="15" aria-hidden="true" /> Dashboard</RouterLink>
      <RouterLink to="/match"><AudioLines :size="15" aria-hidden="true" /> Matching</RouterLink>
      <RouterLink to="/builds"><Hammer :size="15" aria-hidden="true" /> Build &amp; Test</RouterLink>
      <RouterLink to="/data"><Database :size="15" aria-hidden="true" /> Data</RouterLink>
      <RouterLink to="/network"><Network :size="15" aria-hidden="true" /> Network</RouterLink>
      <a v-if="session.info?.local_admin" class="classic" :href="classicUrl" target="_blank" rel="noopener">Classic page <ExternalLink :size="13" aria-hidden="true" /></a>
    </nav>
    <div v-if="signedIn && session.info?.auth_required" class="who" data-testid="signed-in-user">
      <UserRound :size="14" aria-hidden="true" /> {{ session.info.user }} <span class="muted">({{ session.info.role }})</span>
      <button type="button" class="link icon-label" @click="signOut"><LogOut :size="14" aria-hidden="true" /> Sign out</button>
    </div>
  </header>
  <main :class="{ wide: route.name === 'match' && signedIn }">
    <StateMessage v-if="!session.loaded" kind="loading">Connecting to the Studio…</StateMessage>
    <template v-else-if="!session.info">
      <StateMessage kind="error">{{ session.reason || "The Studio server cannot be reached." }}</StateMessage>
      <button type="button" @click="loadSession">Try again</button>
    </template>
    <LoginView v-else-if="!signedIn" />
    <RouterView v-else />
  </main>
  <ConfirmDialog />
</template>
