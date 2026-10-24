import { createRouter, createWebHashHistory } from "vue-router";
import BuildsView from "./views/BuildsView.vue";
import DataView from "./views/DataView.vue";
import DashboardView from "./views/DashboardView.vue";
import MatchView from "./views/MatchView.vue";
import NetworkView from "./views/NetworkView.vue";
import SuggestView from "./views/SuggestView.vue";
import TakeSetsView from "./views/TakeSetsView.vue";

// Hash history: the page is served from a dev server or a static folder, never from a server that
// rewrites paths. The matching workspace keeps its selection and filters in the query string, so a reload
// or Back returns to the same line.
export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", name: "dashboard", component: DashboardView },
    { path: "/match", name: "match", component: MatchView },
    { path: "/dialogues", redirect: "/match" },
    { path: "/suggest", name: "suggest", component: SuggestView },
    { path: "/builds", name: "builds", component: BuildsView },
    { path: "/data", name: "data", component: DataView },
    { path: "/take-sets", name: "take-sets", component: TakeSetsView },
    { path: "/network", name: "network", component: NetworkView },
  ],
});
