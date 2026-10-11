<script setup lang="ts">
import { AudioLines, ExternalLink, Hammer, LayoutDashboard, Radar } from "lucide-vue-next";
import { RouterLink, RouterView } from "vue-router";
</script>

<template>
  <header class="top">
    <strong class="title"><Radar :size="18" aria-hidden="true" /> Halo MCC Localization Studio</strong>
    <nav>
      <RouterLink to="/"><LayoutDashboard :size="16" aria-hidden="true" /> Dashboard</RouterLink>
      <RouterLink to="/match"><AudioLines :size="16" aria-hidden="true" /> Matching</RouterLink>
      <RouterLink to="/builds"><Hammer :size="16" aria-hidden="true" /> Build &amp; Test</RouterLink>
      <a class="classic" href="http://127.0.0.1:8765/" target="_blank" rel="noopener">Classic page <ExternalLink :size="13" aria-hidden="true" /></a>
    </nav>
  </header>
  <main>
    <RouterView />
  </main>
</template>
