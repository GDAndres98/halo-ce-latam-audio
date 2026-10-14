<script setup lang="ts">
// Shown instead of the Studio when the host computer cannot be reached: the phone is offline, the host is off
// or asleep, the Studio is not running there, or the network route (Wi-Fi, Tailscale) is down. The installed
// app still opens (its own files are on the phone), so this explains what to check instead of a browser
// error page. It tries again by itself when the connection comes back and every few seconds while shown.

import { CloudOff, RotateCw, WifiOff } from "lucide-vue-next";
import { onBeforeUnmount, onMounted, ref } from "vue";
import AppEmblem from "./AppEmblem.vue";

const props = defineProps<{ reason: string; retry: () => Promise<void> }>();

const offline = ref(typeof navigator !== "undefined" && navigator.onLine === false);
const trying = ref(false);
const RETRY_MS = 8000;

async function tryAgain() {
  if (trying.value) return;
  trying.value = true;
  try {
    await props.retry();
  } finally {
    trying.value = false;
  }
}

const onOnline = () => {
  offline.value = false;
  void tryAgain();
};
const onOffline = () => (offline.value = true);
const onVisible = () => document.visibilityState === "visible" && void tryAgain();
let timer: ReturnType<typeof setInterval> | undefined;

onMounted(() => {
  window.addEventListener("online", onOnline);
  window.addEventListener("offline", onOffline);
  document.addEventListener("visibilitychange", onVisible);
  timer = setInterval(() => !offline.value && document.visibilityState === "visible" && void tryAgain(), RETRY_MS);
});
onBeforeUnmount(() => {
  window.removeEventListener("online", onOnline);
  window.removeEventListener("offline", onOffline);
  document.removeEventListener("visibilitychange", onVisible);
  clearInterval(timer);
});
</script>

<template>
  <section class="panel host-unreachable" role="alert" data-testid="host-unreachable">
    <AppEmblem :size="44" />
    <h2>
      <WifiOff v-if="offline" :size="20" aria-hidden="true" />
      <CloudOff v-else :size="20" aria-hidden="true" />
      {{ offline ? "This device is offline" : "Can't reach the Studio host" }}
    </h2>
    <p v-if="offline">Connect to Wi-Fi or mobile data. The Studio will reconnect by itself.</p>
    <template v-else>
      <p>All mappings and recordings live on the host computer, so the Studio needs it to work. Check that:</p>
      <ul>
        <li>the host computer is on and awake;</li>
        <li>the Studio is running there (<code>npm run host</code>);</li>
        <li>this device is on the same Wi-Fi, or Tailscale is connected on both.</li>
      </ul>
    </template>
    <p class="small muted">Unsaved edits made on this device are kept for this session.</p>
    <p v-if="reason && !offline" class="small muted">Details: {{ reason }}</p>
    <button type="button" class="primary icon-label" :disabled="trying" data-testid="retry-host" @click="tryAgain">
      <RotateCw :size="16" :class="{ spin: trying }" aria-hidden="true" /> {{ trying ? "Connecting…" : "Try again" }}
    </button>
  </section>
</template>
