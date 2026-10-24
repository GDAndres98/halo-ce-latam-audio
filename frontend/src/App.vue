<script setup lang="ts">
import { AudioLines, Database, ExternalLink, Eye, Hammer, Layers, LayoutDashboard, LogIn, LogOut, Menu, Network, Sparkles, UserRound, X } from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { RouterLink, RouterView, useRoute, useRouter } from "vue-router";
import { canListen, loadSession, session, signedIn, signOut, visitor } from "./auth/session";
import { startLiveUpdates, stopLiveUpdates } from "./live/changes";
import AppBackdrop from "./components/AppBackdrop.vue";
import AppEmblem from "./components/AppEmblem.vue";
import ConfirmDialog from "./components/ui/ConfirmDialog.vue";
import HostUnreachable from "./components/HostUnreachable.vue";
import InstallApp from "./components/InstallApp.vue";
import PwaBanner from "./components/PwaBanner.vue";
import StateMessage from "./components/ui/StateMessage.vue";
import VolumeControl from "./components/VolumeControl.vue";
import LoginView from "./views/LoginView.vue";

const route = useRoute();
const router = useRouter();
// The classic page is served by the API server on the host only (the dev server does not forward it).
const classicUrl = import.meta.env.DEV ? "http://127.0.0.1:8765/classic" : "/classic";

// Phones: the menu folds behind a button, with the current screen's name beside it; it closes on navigation.
const navOpen = ref(false);
const PAGE_NAMES: Record<string, string> = {
  dashboard: "Dashboard", match: "Matching", suggest: "Suggestions", builds: "Build & Test", data: "Data", network: "Network",
};
const pageName = computed(() => PAGE_NAMES[String(route.name ?? "")] ?? "");
watch(() => route.path, () => (navOpen.value = false));

onMounted(loadSession);
// Live updates name who saved: the public view has none (the server refuses them there too).
const live = computed(() => signedIn.value && !visitor.value);
watch(live, (yes) => (yes ? startLiveUpdates() : stopLiveUpdates()), { immediate: true });

// The public read-only view (docs/public-access.md) has no Suggestions, Data or Network page: they are the owner's.
const OWNER_PAGES = new Set(["suggest", "data", "network"]);
// Never mounted for a visitor (they would only ask for what the server refuses), even for a moment.
const ownerPageForVisitor = computed(() => visitor.value && OWNER_PAGES.has(String(route.name)));
watch(
  [visitor, () => route.name],
  ([isVisitor, name]) => {
    if (isVisitor && OWNER_PAGES.has(String(name))) void router.replace("/");
  },
  { immediate: true },
);
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
    <button
      v-if="signedIn" type="button" class="menu-toggle icon-label" aria-controls="main-nav" :aria-expanded="navOpen"
      data-testid="menu-toggle" @click="navOpen = !navOpen"
    >
      <X v-if="navOpen" :size="18" aria-hidden="true" />
      <Menu v-else :size="18" aria-hidden="true" />
      <span>{{ pageName || "Menu" }}</span><span class="sr-only"> · menu</span>
    </button>
    <nav v-if="signedIn" id="main-nav" aria-label="Main" :class="{ open: navOpen }">
      <RouterLink to="/"><LayoutDashboard :size="15" aria-hidden="true" /> Dashboard</RouterLink>
      <RouterLink to="/match"><AudioLines :size="15" aria-hidden="true" /> Matching</RouterLink>
      <RouterLink v-if="!visitor" to="/suggest"><Sparkles :size="15" aria-hidden="true" /> Suggestions</RouterLink>
      <RouterLink to="/builds"><Hammer :size="15" aria-hidden="true" /> Build &amp; Test</RouterLink>
      <RouterLink v-if="!visitor" to="/take-sets"><Layers :size="15" aria-hidden="true" /> Take sets</RouterLink>
      <RouterLink v-if="!visitor" to="/data"><Database :size="15" aria-hidden="true" /> Data</RouterLink>
      <RouterLink v-if="!visitor" to="/network"><Network :size="15" aria-hidden="true" /> Network</RouterLink>
      <InstallApp compact />
      <a v-if="session.info?.local_admin" class="classic" :href="classicUrl" target="_blank" rel="noopener">Classic page <ExternalLink :size="13" aria-hidden="true" /></a>
    </nav>
    <!-- The listening volume for every player in the Studio; hidden where nothing can be heard. In the menu on phones. -->
    <VolumeControl v-if="signedIn && canListen" :class="{ open: navOpen }" />
    <!-- Public view: always visible (also on a phone, where the account area folds into the menu). -->
    <div v-if="visitor" class="visitor-chip" data-testid="visitor-mode">
      <span class="badge info" title="Anyone can browse this Studio. Editing, listening and downloads need the owner's sign-in.">
        <Eye :size="13" aria-hidden="true" /> Read-only
      </span>
      <a
        v-if="session.info?.sign_in_url" class="button small-button icon-label" :href="session.info.sign_in_url"
        rel="noopener" data-testid="sign-in-to-edit" title="Editing is limited to the project owner's account"
      ><LogIn :size="14" aria-hidden="true" /> Sign in to edit</a>
    </div>
    <div v-if="signedIn && session.info?.auth_required" class="who" :class="{ open: navOpen }" data-testid="signed-in-user">
      <UserRound :size="14" aria-hidden="true" /> {{ session.info.user }} <span class="muted">({{ session.info.role }})</span>
      <button type="button" class="link icon-label" @click="signOut"><LogOut :size="14" aria-hidden="true" /> Sign out</button>
    </div>
  </header>
  <main :class="{ wide: route.name === 'match' && signedIn }">
    <StateMessage v-if="!session.loaded" kind="loading">Connecting to the Studio…</StateMessage>
    <HostUnreachable v-else-if="!session.info && !session.accessSignIn" :reason="session.reason" :retry="loadSession" />
    <LoginView v-else-if="!signedIn" />
    <RouterView v-else-if="!ownerPageForVisitor" />
  </main>
  <PwaBanner />
  <ConfirmDialog />
</template>
