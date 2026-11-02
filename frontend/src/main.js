import { createWebHistory } from "vue-router"
import { createMobileApp } from "./app"
import "./index.css"

// window.ms_fail (inline in index.html) puts "App failed to load — <error>" on screen instead of a blank page.
function fail(err) {
	console.error(err)
	window.ms_fail?.(err?.message || String(err))
}

const mount = document.getElementById("app")
if (window.ms_boot && mount) {
	try {
		const { app } = createMobileApp(createWebHistory("/mobile-sales"), fail)
		app.mount(mount)
		window.ms_mounted = true
	} catch (err) {
		fail(err)
	}

	// App shell only (static assets + this page). No data is cached and nothing is queued offline.
	if ("serviceWorker" in navigator) {
		navigator.serviceWorker
			.register("/mobile-sales-sw.min.js", { scope: "/mobile-sales", updateViaCache: "none" })
			.then((registration) => registration.update())
			.catch(() => {})
	}
}
