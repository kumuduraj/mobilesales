// Mobile Sales service worker: caches the app shell only. API calls always go to the network.
import { cleanupOutdatedCaches, precacheAndRoute } from "workbox-precaching"
import { NavigationRoute, registerRoute } from "workbox-routing"
import { NetworkFirst } from "workbox-strategies"

cleanupOutdatedCaches()
precacheAndRoute(self.__WB_MANIFEST)

// The /mobile-sales host page: fresh when online, last copy when offline (the app then shows
// "No connection" and blocks every submit).
registerRoute(
	new NavigationRoute(new NetworkFirst({ cacheName: "mobile-sales-shell", networkTimeoutSeconds: 5 }), {
		allowlist: [/^\/mobile-sales(\/|$)/],
	})
)

self.addEventListener("install", () => self.skipWaiting())
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()))
