<script setup lang="ts">
// How to install the Studio as an app on this device: the browser's own dialog where it has one (Chrome, Edge,
// Android), the Share → Add to Home Screen steps on an iPhone or iPad, and why it cannot be installed from a
// plain-http address. Nothing is shown once the Studio runs as the installed app.
import { Download, Share, Smartphone } from "lucide-vue-next";
import { ref } from "vue";
import { installApp, pwa } from "../pwa";

defineProps<{ compact?: boolean }>();
const result = ref("");

async function install() {
  result.value = (await installApp()) ? "Installed. Open Halo Studio from the home screen." : "";
}
</script>

<template>
  <template v-if="!pwa.standalone">
    <button v-if="compact && pwa.canInstall" type="button" class="icon-label install-button" data-testid="install-app" @click="install">
      <Download :size="15" aria-hidden="true" /> Install app
    </button>
    <section v-else-if="!compact" class="panel install-panel" data-testid="install-panel">
      <h2 class="icon-label"><Smartphone :size="18" aria-hidden="true" /> Install on this device</h2>
      <p v-if="pwa.canInstall">
        Install the Studio as an app: it opens from the home screen, without the browser's address bar.
        <button type="button" class="primary icon-label" data-testid="install-app-panel" @click="install">
          <Download :size="15" aria-hidden="true" /> Install app
        </button>
      </p>
      <p v-else-if="!pwa.secure" class="small">
        Installing needs a secure (https) address. Open the Studio through its Tailscale address
        (docs/remote-access.md §5) to install it; this plain-http address still works in the browser.
      </p>
      <p v-else-if="pwa.ios" class="small">
        In Safari, tap <Share :size="14" aria-label="Share" /> <strong>Share</strong>, then <strong>Add to Home Screen</strong>.
      </p>
      <p v-else class="small">
        Use the browser's menu: <strong>Install app</strong> or <strong>Add to Home screen</strong>.
      </p>
      <p v-if="result" class="small ok">{{ result }}</p>
      <p class="small muted">The app only keeps its own screens on the device. Mappings, recordings and your session stay on the host.</p>
    </section>
  </template>
</template>
