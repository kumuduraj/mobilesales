// Thin wrapper around Frappe's /api/method endpoint: CSRF header, plain-language errors, offline guard.
import { endSession, sessionEnded } from "./account"
import { reportFailure } from "./connection"
import { online } from "./state"
import { __ } from "./translation"

export class ApiError extends Error {}

export const SESSION_ENDED = () => __("Your session has ended — please log in again")

function serverMessage(data) {
	try {
		const messages = JSON.parse(data._server_messages || "[]").map((m) => JSON.parse(m).message)
		if (messages.length) return messages.join("\n")
	} catch (e) {
		/* fall through */
	}
	if (data.exception) return String(data.exception).split(":").slice(1).join(":").trim() || data.exception
	return null
}

function plain(text) {
	const el = document.createElement("div")
	el.innerHTML = text
	return el.textContent || el.innerText || text
}

export async function call(method, args = {}) {
	if (!online.value) throw new ApiError(__("No connection. Try again when you are back online."))
	const body = new FormData()
	for (const [key, value] of Object.entries(args)) {
		if (value === undefined || value === null) continue
		body.append(key, typeof value === "object" ? JSON.stringify(value) : value)
	}
	let response
	try {
		response = await fetch(`/api/method/${method}`, {
			method: "POST",
			body,
			headers: { Accept: "application/json", "X-Frappe-CSRF-Token": window.csrf_token },
		})
	} catch (e) {
		reportFailure()
		throw new ApiError(__("Could not reach the server. Check your connection."))
	}
	if ([502, 503, 504].includes(response.status)) {
		reportFailure() // the proxy answered, the site did not
		throw new ApiError(__("Could not reach the server. Check your connection."))
	}
	const data = await response.json().catch(() => ({}))
	// A refusal can be a real permission answer ("You can only see your own trips") or a login that has
	// ended (expired, logged out elsewhere): ask the server which before saying so.
	if ([401, 403].includes(response.status) || data.exc_type === "CSRFTokenError") {
		if (await sessionEnded()) {
			endSession()
			throw new ApiError(SESSION_ENDED())
		}
	}
	if (!response.ok || data.exc_type) {
		throw new ApiError(plain(serverMessage(data) || __("Something went wrong ({0}).", [response.status])))
	}
	return data.message
}

export const m = (name) => `mobilesales.api.mobile.${name}`
