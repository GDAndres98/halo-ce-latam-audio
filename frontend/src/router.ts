import { createRouter, createWebHashHistory } from "vue-router";
import DashboardView from "./views/DashboardView.vue";
import DialoguesView from "./views/DialoguesView.vue";
import SlotView from "./views/SlotView.vue";
import BuildsView from "./views/BuildsView.vue";

// Hash history: the page is served from a dev server or a static folder, never from a server that
// rewrites paths. Filters live in the URL (query string), so reloads and Back keep the view.
export const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: "/", name: "dashboard", component: DashboardView },
    { path: "/dialogues", name: "dialogues", component: DialoguesView },
    { path: "/slots/:id(.*)", name: "slot", component: SlotView, props: true },
    { path: "/builds", name: "builds", component: BuildsView },
  ],
});
