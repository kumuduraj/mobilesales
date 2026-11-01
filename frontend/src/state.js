import { reactive, ref } from "vue"

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
