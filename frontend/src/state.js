import { reactive, ref } from "vue"
import { __ } from "./translation"

// "online" only after /api/method/ping answered (never on navigator.onLine alone: captive Wi-Fi, no data);
// "reconnecting" while a check runs after a failure; "offline" when the phone is offline or the server
// stays unreachable. connection.js keeps it current.
export const connection = ref(navigator.onLine ? "reconnecting" : "offline")
// Saving and the submit buttons are blocked only when offline (a check in progress lets calls through).
export const online = ref(navigator.onLine)
export const toast = ref("")

// Session context from get_context(): agent, open trip, settings flags, reasons, denominations.
// expired: the server no longer knows this login (the app shows a message and goes to the login page).
export const session = reactive({ ctx: null, loading: false, error: null, expired: false })

// Screens holding input not yet sent to the server (the logout dialog warns about them).
export const unsaved = reactive({ visit: false, settlement: false })

export const LOGIN_URL = "/login?redirect-to=/mobile-sales"

// Log out / user switch: nothing of the previous user stays in memory.
export function resetState() {
	Object.assign(session, { ctx: null, loading: false, error: null, expired: false })
	Object.assign(unsaved, { visit: false, settlement: false })
	toast.value = ""
	window.ms_boot = null
	window.csrf_token = null
}

export function money(value) {
	const currency = session.ctx?.settings?.currency || ""
	const n = Number(value || 0)
	return `${currency} ${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`.trim()
}

// "<address line 1>, <city> · …<last 4 digits of mobile>", missing parts skipped: what tells two shops of the
// same name apart (v1.0.2). Same rule as services/customers.identification on the server.
export function customerLine(c) {
	if (!c) return ""
	const place = [c.address_line1 ?? c.address?.address_line1, c.city ?? c.address?.city].filter(Boolean).join(", ")
	const digits = String(c.mobile_no || "").replace(/\D/g, "")
	return [place, digits ? `…${digits.slice(-4)}` : ""].filter(Boolean).join(" · ")
}

// A customer balance: below 0 the customer holds credit, shown as "Credit: LKR x" (green), never as a
// negative outstanding.
export function balance(value) {
	const n = Number(value || 0)
	return n < 0 ? { credit: true, label: __("Credit"), text: money(-n) } : { credit: false, label: __("Outstanding"), text: money(n) }
}

export function qty(value) {
	return Number(value || 0).toLocaleString(undefined, { maximumFractionDigits: 3 })
}

export function printUrl(doctype, name, format) {
	const params = new URLSearchParams({ doctype, name, format, no_letterhead: 1, trigger_print: 1 })
	return `/printview?${params.toString()}`
}

export function newClientRef() {
	if (window.crypto?.randomUUID) return window.crypto.randomUUID()
	return `${Date.now()}-${Math.random().toString(16).slice(2)}-${Math.random().toString(16).slice(2)}`
}

export function splitNames(value) {
	return (value || "").split(",").map((n) => n.trim()).filter(Boolean)
}

// The prints of one visit, each only when its document exists: bill → invoice → return note(s); "Print All"
// (/mobile-sales-print, same order on the server) when there is more than one.
export function visitPrints(visit) {
	if (!visit?.name) return []
	const notes = splitNames(visit.credit_notes)
	const list = []
	if (visit.sales_invoice || notes.length || visit.payment_entry)
		list.push({ key: "bill", label: __("Print Bill"), url: printUrl("Customer Visit", visit.name, "Mobile Visit Bill"), primary: true })
	if (visit.sales_invoice)
		list.push({ key: "invoice", label: __("Print Invoice"), url: printUrl("Sales Invoice", visit.sales_invoice, "Mobile Invoice 4in") })
	for (const note of notes)
		list.push({
			key: `note:${note}`,
			label: notes.length > 1 ? `${__("Print Return Note")} ${note}` : __("Print Return Note"),
			url: printUrl("Sales Invoice", note, "Mobile Return Note"),
		})
	if (list.length > 1)
		list.push({ key: "all", label: __("Print All"), url: `/mobile-sales-print?${new URLSearchParams({ visit: visit.name })}` })
	return list
}
