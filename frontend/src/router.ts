import { createRouter, createWebHashHistory } from "vue-router";
import BuildsView from "./views/BuildsView.vue";
import DashboardView from "./views/DashboardView.vue";
import MatchView from "./views/MatchView.vue";

// Hash history: the page is served from a dev server or a static folder, never from a server that
// rewrites paths. The matching workspace keeps its selection and filters in the query string, so a reload
// or Back returns to the same line.
export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", name: "dashboard", component: DashboardView },
    { path: "/match", name: "match", component: MatchView },
    { path: "/dialogues", redirect: "/match" },
    { path: "/builds", name: "builds", component: BuildsView },
  ],
});
