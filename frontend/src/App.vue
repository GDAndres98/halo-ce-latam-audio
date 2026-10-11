<script setup lang="ts">
import { RouterLink, RouterView } from "vue-router";
</script>

<template>
  <header class="top">
    <strong class="title">Halo MCC Localization Studio</strong>
    <nav>
      <RouterLink to="/">Dashboard</RouterLink>
      <RouterLink to="/dialogues">Dialogues</RouterLink>
      <RouterLink to="/builds">Build &amp; Test</RouterLink>
      <a class="classic" href="http://127.0.0.1:8765/" target="_blank" rel="noopener">Classic page (edits &amp; approvals)</a>
    </nav>
  </header>
  <main>
    <RouterView />
  </main>
</template>
