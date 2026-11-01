// Thin wrapper around Frappe's /api/method endpoint: CSRF header, plain-language errors, offline guard.
import { online } from "./state"
import { __ } from "./translation"

export class ApiError extends Error {}

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
		throw new ApiError(__("Could not reach the server. Check your connection."))
	}
	const data = await response.json().catch(() => ({}))
	if (response.status === 403 && !serverMessage(data)) {
		throw new ApiError(__("Your session has expired. Please log in again."))
	}
	if (!response.ok || data.exc_type) {
		throw new ApiError(plain(serverMessage(data) || __("Something went wrong ({0}).", [response.status])))
	}
	return data.message
}

export const m = (name) => `mobilesales.api.mobile.${name}`
