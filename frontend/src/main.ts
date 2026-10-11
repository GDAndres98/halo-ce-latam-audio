import { createApp } from "vue";
import App from "./App.vue";
import { router } from "./router";
import { applyTheme } from "./theme/tokens";
import "./styles.css";

applyTheme();

createApp(App).use(router).mount("#app");
