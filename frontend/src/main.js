import { createApp } from "vue"
import { createRouter, createWebHistory } from "vue-router"
import { setupTranslation } from "./translate"
import App from "./App.vue"
import "./index.css"

const boot = window.ms_boot
setupTranslation(boot?.messages)

const mount = document.getElementById("app")
if (boot && mount) {
	const router = createRouter({
		history: createWebHistory("/mobile-sales"),
		routes: [
			{ path: "/", name: "today", component: () => import("./pages/Today.vue") },
			{ path: "/route", name: "route", component: () => import("./pages/RoutePlan.vue") },
			{ path: "/visit/:customer", name: "visit", component: () => import("./pages/Visit.vue"), props: true },
			{ path: "/history", name: "history", component: () => import("./pages/History.vue") },
			{ path: "/settlement", name: "settlement", component: () => import("./pages/Settlement.vue") },
			{ path: "/:pathMatch(.*)*", redirect: "/" },
		],
	})
	createApp(App).use(router).mount(mount)

	// App shell only (static assets + this page). No data is cached and nothing is queued offline.
	if ("serviceWorker" in navigator) {
		navigator.serviceWorker.register("/mobile-sales-sw.min.js", { scope: "/mobile-sales" }).catch(() => {})
	}
}
