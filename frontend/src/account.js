// Log out and session end. The service worker caches the app shell only (static files and the /mobile-sales
// host page, never an API answer), but the cached host page carries the user's boot data, so log out drops
// that cache too: the next user on this phone never sees the previous user's data, online or offline.
import { LOGIN_URL, resetState, session } from "./state"

export const SHELL_CACHE_PREFIX = "mobile-sales-shell"
export const timing = { expiredRedirect: 2500 } // ms before the login page opens; the tests shorten it

// window.location in one place so the tests can watch it.
export const nav = { go: (url) => window.location.assign(url) }

export async function clearShellCache() {
	if (typeof caches === "undefined") return
	const names = await caches.keys()
	await Promise.all(names.filter((name) => name.startsWith(SHELL_CACHE_PREFIX)).map((name) => caches.delete(name)))
}

// Throws when the server could not be reached: the login must end on the server, or the next user of the
// phone would still be logged in as this one.
export async function logout() {
	const response = await fetch("/api/method/logout", {
		method: "POST",
		headers: { Accept: "application/json", "X-Frappe-CSRF-Token": window.csrf_token || "" },
	})
	if (!response.ok) throw new Error(String(response.status))
	await clearShellCache().catch(() => {})
	resetState()
	nav.go(LOGIN_URL)
}

// Is this login still known to the server? Only a Guest answer (or a refusal) means it has ended; other
// failures (no connection) say nothing about the session.
export async function sessionEnded() {
	try {
		const response = await fetch("/api/method/frappe.auth.get_logged_user", { headers: { Accept: "application/json" }, cache: "no-store" })
		if (response.status === 401 || response.status === 403) return true
		const data = await response.json().catch(() => ({}))
		return response.ok && (!data.message || data.message === "Guest")
	} catch (e) {
		return false
	}
}

let redirecting = null
export function endSession() {
	session.expired = true
	if (!redirecting)
		redirecting = setTimeout(() => {
			redirecting = null
			clearShellCache()
				.catch(() => {})
				.finally(() => {
					resetState()
					nav.go(LOGIN_URL)
				})
		}, timing.expiredRedirect)
}
