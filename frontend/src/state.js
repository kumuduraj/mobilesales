import { reactive, ref } from "vue"
import { __ } from "./translation"

export const online = ref(navigator.onLine)
window.addEventListener("online", () => (online.value = true))
window.addEventListener("offline", () => (online.value = false))

// Session context from get_context(): agent, open trip, settings flags, reasons, denominations.
export const session = reactive({ ctx: null, loading: false, error: null })

export function money(value) {
	const currency = session.ctx?.settings?.currency || ""
	const n = Number(value || 0)
	return `${currency} ${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`.trim()
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
