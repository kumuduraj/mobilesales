// Online / offline status shown in the header. The app is "online" only when /api/method/ping answers: the
// phone's navigator.onLine is true on a captive Wi-Fi or without data too. Checks run every 30 s, when the
// phone reports a network change and after any failed request; a failed check is retried once quickly
// ("Reconnecting…") before the app shows "Offline". Coming back shows "Back online" and refreshes the screen.
import { onBeforeUnmount, onMounted } from "vue"
import { connection, online, toast } from "./state"
import { __ } from "./translation"

// ms; the tests shorten them
export const timing = { every: 30000, retry: 3000, pingTimeout: 8000, toast: 3000 }

const handlers = new Set()
let timer = null
let retryTimer = null
let toastTimer = null
let checking = null
let wasDown = false

function set(state) {
	connection.value = state
	online.value = state !== "offline"
}

async function ping() {
	const abort = typeof AbortController !== "undefined" ? new AbortController() : null
	const stop = abort && setTimeout(() => abort.abort(), timing.pingTimeout)
	try {
		const response = await fetch("/api/method/ping", { cache: "no-store", signal: abort?.signal })
		const data = await response.json().catch(() => ({}))
		return response.ok && data.message === "pong"
	} catch (e) {
		return false
	} finally {
		clearTimeout(stop)
	}
}

function backOnline() {
	toast.value = __("Back online")
	clearTimeout(toastTimer)
	toastTimer = setTimeout(() => (toast.value = ""), timing.toast)
	for (const fn of handlers) Promise.resolve().then(fn).catch(() => {})
}

// One check at a time; resolves true when the server answered.
export function checkConnection() {
	if (checking) return checking
	checking = (async () => {
		if (!navigator.onLine) {
			wasDown = true
			set("offline")
			return false
		}
		const ok = await ping()
		if (ok) {
			clearTimeout(retryTimer)
			const recovered = wasDown
			wasDown = false
			set("online")
			if (recovered) backOnline()
		} else if (connection.value === "online" || (connection.value === "reconnecting" && !wasDown)) {
			// first failure: show "Reconnecting…" and try again soon
			wasDown = true
			set("reconnecting")
			clearTimeout(retryTimer)
			retryTimer = setTimeout(() => checkConnection(), timing.retry)
		} else {
			wasDown = true
			set("offline")
		}
		return ok
	})().finally(() => (checking = null))
	return checking
}

// A request could not reach the server (api.js).
export function reportFailure() {
	if (connection.value === "online") set("reconnecting")
	checkConnection()
}

function onOnline() {
	set("reconnecting")
	checkConnection()
}

function onOffline() {
	wasDown = true
	set("offline")
}

export function startConnectionMonitor() {
	stopConnectionMonitor()
	window.addEventListener("online", onOnline)
	window.addEventListener("offline", onOffline)
	timer = setInterval(checkConnection, timing.every)
	return checkConnection()
}

export function stopConnectionMonitor() {
	window.removeEventListener("online", onOnline)
	window.removeEventListener("offline", onOffline)
	clearInterval(timer)
	clearTimeout(retryTimer)
	clearTimeout(toastTimer)
	timer = retryTimer = toastTimer = null
	wasDown = false
}

// A screen's data reload when the connection comes back (registered while the screen is shown).
export function onReconnect(fn) {
	onMounted(() => handlers.add(fn))
	onBeforeUnmount(() => handlers.delete(fn))
}
