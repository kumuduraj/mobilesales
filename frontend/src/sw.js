// Mobile Sales service worker: caches the app shell only. API calls always go to the network.
import { setCacheNameDetails } from "workbox-core"
import { precacheAndRoute } from "workbox-precaching"
import { NavigationRoute, registerRoute } from "workbox-routing"
import { NetworkFirst } from "workbox-strategies"

// Bump CACHE_VERSION when installed apps must drop everything cached before (v2: blank-screen fix, v0.5.0).
const CACHE_VERSION = "v2"
const SHELL_CACHE = `mobile-sales-shell-${CACHE_VERSION}`
setCacheNameDetails({ prefix: "mobile-sales", suffix: CACHE_VERSION })

precacheAndRoute(self.__WB_MANIFEST)

// The /mobile-sales host page: fresh when online, last copy when offline (the app then shows
// "No connection" and blocks every submit).
registerRoute(
	new NavigationRoute(new NetworkFirst({ cacheName: SHELL_CACHE, networkTimeoutSeconds: 5 }), {
		allowlist: [/^\/mobile-sales(\/|$)/],
	})
)

// A new worker takes over at once and removes every cache of older versions (and workbox's defaults).
self.addEventListener("install", () => self.skipWaiting())
self.addEventListener("activate", (event) =>
	event.waitUntil(
		caches
			.keys()
			.then((names) => Promise.all(names.filter((name) => !name.endsWith(CACHE_VERSION)).map((name) => caches.delete(name))))
			.then(() => self.clients.claim())
	)
)
