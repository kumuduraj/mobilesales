// Builds the Vue app + router; shared by main.js (browser) and the mount test (tests/mount.test.js).
import { createApp } from "vue"
import { createRouter } from "vue-router"
import App from "./App.vue"
import { __ } from "./translation"

export const routes = [
	{ path: "/", name: "today", component: () => import("./pages/Today.vue") },
	{ path: "/route", name: "route", component: () => import("./pages/RoutePlan.vue") },
	{ path: "/visit/:customer", name: "visit", component: () => import("./pages/Visit.vue"), props: true },
	{ path: "/history", name: "history", component: () => import("./pages/History.vue") },
	{ path: "/settlement", name: "settlement", component: () => import("./pages/Settlement.vue") },
	{ path: "/:pathMatch(.*)*", redirect: "/" },
]

export function createMobileApp(history, onError) {
	const router = createRouter({ history, routes })
	const app = createApp(App)
	app.config.globalProperties.__ = __
	app.config.errorHandler = (err, instance, info) => onError(err, info)
	router.onError((err) => onError(err, "router"))
	app.use(router)
	return { app, router }
}
