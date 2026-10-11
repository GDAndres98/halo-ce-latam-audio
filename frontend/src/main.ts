import { createApp } from "vue";
import App from "./App.vue";
import { router } from "./router";
import { applyTheme } from "./theme/tokens";
// Fonts, bundled with the app (SIL Open Font License 1.1): Michroma for titles and menus, Saira for text.
import "@fontsource/michroma/400.css";
import "@fontsource-variable/saira/index.css";
import "./styles/index.css";

applyTheme();

createApp(App).use(router).mount("#app");
