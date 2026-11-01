// __("text {0}", [arg]): this app's translations come in window.ms_boot.translations (host page); the
// original text is the fallback. Registered as app.config.globalProperties.__ for templates (www pages have
// no Frappe Desk global __) and imported by scripts.
export function __(text, args = []) {
	const translations = window.ms_boot?.translations || {}
	let out = translations[text] || text
	args.forEach((arg, i) => (out = String(out).replaceAll(`{${i}}`, arg)))
	return out
}
