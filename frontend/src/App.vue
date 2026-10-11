<script setup lang="ts">
import { AudioLines, Database, ExternalLink, Hammer, LayoutDashboard } from "lucide-vue-next";
import { RouterLink, RouterView, useRoute } from "vue-router";
import AppBackdrop from "./components/AppBackdrop.vue";
import AppEmblem from "./components/AppEmblem.vue";
import ConfirmDialog from "./components/ui/ConfirmDialog.vue";

const route = useRoute();
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
    <nav aria-label="Main">
      <RouterLink to="/"><LayoutDashboard :size="15" aria-hidden="true" /> Dashboard</RouterLink>
      <RouterLink to="/match"><AudioLines :size="15" aria-hidden="true" /> Matching</RouterLink>
      <RouterLink to="/builds"><Hammer :size="15" aria-hidden="true" /> Build &amp; Test</RouterLink>
      <RouterLink to="/data"><Database :size="15" aria-hidden="true" /> Data</RouterLink>
      <a class="classic" href="http://127.0.0.1:8765/" target="_blank" rel="noopener">Classic page <ExternalLink :size="13" aria-hidden="true" /></a>
    </nav>
  </header>
  <main :class="{ wide: route.name === 'match' }">
    <RouterView />
  </main>
  <ConfirmDialog />
</template>
