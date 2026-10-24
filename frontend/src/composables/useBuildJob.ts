// The Build & Test page's current build/install/restore job, kept outside the page so leaving and coming back
// shows it at once. The server is the source of truth (GET /api/job/current), so other tabs see it too.
import { ref } from "vue";
import type { BuildJob } from "../api/types";

export const buildJob = ref<BuildJob | null>(null);
