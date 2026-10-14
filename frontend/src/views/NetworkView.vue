<script setup lang="ts">
// Network access: how this Studio is reached from other computers, and who may do what. Read-only: the
// settings live in config/studio_server.json on the host (docs/remote-access.md).

import { Globe, Laptop, Network, RefreshCw, ShieldCheck, Users } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { api, ApiError } from "../api/client";
import type { NetworkInfo } from "../api/types";
import { permissions, session } from "../auth/session";
import { liveStatus } from "../live/changes";
import CopyButton from "../components/ui/CopyButton.vue";
import PageHeader from "../components/ui/PageHeader.vue";
import PanelHeader from "../components/ui/PanelHeader.vue";
import StateMessage from "../components/ui/StateMessage.vue";
import StatusBadge from "../components/StatusBadge.vue";
import InstallApp from "../components/InstallApp.vue";

const info = ref<NetworkInfo | null>(null);
const error = ref("");

async function refresh() {
  error.value = "";
  try {
    info.value = await api.network();
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : String(e);
  }
}

const mode = computed(() => {
  const i = info.value;
  if (!i) return "";
  if (!i.remote.running) return "This computer only";
  if (i.public_url?.startsWith("https://")) return "This computer, the LAN, and secure remote access (HTTPS)";
  return i.remote.tls ? "This computer and other computers (HTTPS)" : "This computer and other computers (LAN, HTTP)";
});

const here = computed(() =>
  session.info?.local_admin
    ? { label: "the host computer (administrator)", tone: "ok" as const }
    : { label: `another computer, signed in as ${session.info?.user} (${session.info?.role})`, tone: "info" as const },
);

const connection = computed(() =>
  info.value?.https
    ? { label: "encrypted (HTTPS)", tone: "ok" as const }
    : session.info?.local_admin
      ? { label: "this computer only (never leaves it)", tone: "ok" as const }
      : { label: "not encrypted (HTTP)", tone: "warn" as const },
);

const KIND: Record<string, string> = {
  lan: "LAN",
  tailscale: "Tailscale",
  public: "public address",
  public_url: "secure address",
  name: "name",
};
const kindName = (kind: string) => KIND[kind] ?? kind;
const seen = (t: number) => new Date(t * 1000).toLocaleString();

onMounted(refresh);
</script>

<template>
  <section class="network-view">
    <PageHeader
      title="Network access"
      :icon="Network"
      lead="How other computers reach this Studio. The settings are on the host, in config/studio_server.json."
    >
      <button type="button" class="icon-label" @click="refresh"><RefreshCw :size="15" aria-hidden="true" /> Check again</button>
    </PageHeader>
    <StateMessage v-if="error" kind="error">{{ error }}</StateMessage>
    <StateMessage v-else-if="!info" kind="loading">Reading the network settings…</StateMessage>
    <InstallApp />

    <template v-if="info">
      <section class="panel" data-testid="network-mode">
        <PanelHeader title="This page" :icon="Laptop" />
        <dl class="texts small">
          <dt>Access mode</dt>
          <dd>{{ mode }}</dd>
          <dt>You are on</dt>
          <dd><StatusBadge :label="here.label" :tone="here.tone" /></dd>
          <dt>Connection</dt>
          <dd><StatusBadge :label="connection.label" :tone="connection.tone" /></dd>
          <dt>Live updates</dt>
          <dd>{{ liveStatus.status === "live" ? "connected: changes from other computers appear here" : liveStatus.status }}</dd>
          <dt>Game install / restore</dt>
          <dd>{{ permissions.install ? "allowed here (host computer)" : "only on the host computer's own Studio address" }}</dd>
        </dl>
      </section>

      <section class="panel" data-testid="network-addresses">
        <PanelHeader title="Connect from another computer" :icon="Globe" />
        <template v-if="info.remote.running">
          <ul class="plain url-list">
            <li v-for="u in info.urls" :key="u.url" class="url-row">
              <code>{{ u.url }}</code>
              <CopyButton :text="u.url" label="Copy address" />
              <StatusBadge :label="kindName(u.kind)" tone="info" />
              <StatusBadge v-if="!u.encrypted" label="not encrypted" tone="warn" />
            </li>
          </ul>
          <p class="small muted">
            Open one of these in a browser on the other computer and sign in. For access over the internet use
            Tailscale (encrypted and private to your own devices), as docs/remote-access.md describes. Never
            forward a router port to the Studio.
          </p>
        </template>
        <p v-else class="small">
          Remote access is off: only this computer can use the Studio. To turn it on, create an account on the host
          (<code>python scripts/ui/studio_users.py add &lt;name&gt; --role admin</code>), then start the server with
          <code>--lan</code>, or set <code>remote.enabled</code> to <code>true</code> in <code>config/studio_server.json</code>.
        </p>
        <dl class="texts small">
          <dt>Host name</dt>
          <dd>{{ info.hostname }}</dd>
          <dt>Addresses</dt>
          <dd>{{ info.addresses.map((a) => `${a.address} (${kindName(a.kind)})`).join(", ") || "—" }}</dd>
          <dt>Remote listener</dt>
          <dd>{{ info.remote.host }}:{{ info.remote.port }} {{ info.remote.tls ? "(HTTPS)" : "(HTTP)" }}</dd>
          <dt>Extra host names</dt>
          <dd>{{ info.allowed_hosts.join(", ") || "—" }}</dd>
          <dt>Sessions</dt>
          <dd>end after {{ info.session.idle_hours }} h unused, or after {{ info.session.max_days }} days at most</dd>
          <dt>Settings file</dt>
          <dd>{{ info.config_file ?? "none (defaults)" }}</dd>
        </dl>
      </section>

      <section v-if="info.remote_users" class="panel" data-testid="network-accounts">
        <PanelHeader title="Accounts" :icon="Users" />
        <p class="small">
          Accounts: {{ info.remote_users.join(", ") || "none" }}. Manage them on the host with
          <code>scripts/ui/studio_users.py</code>.
        </p>
        <ul class="plain small">
          <li v-for="s in info.signed_in ?? []" :key="`${s.user}-${s.last_seen}`">
            <ShieldCheck :size="13" aria-hidden="true" /> {{ s.user }} from {{ s.from ?? "?" }}, last seen {{ seen(s.last_seen) }}
          </li>
        </ul>
      </section>
    </template>
  </section>
</template>
