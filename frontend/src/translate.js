// __("text {0}", [arg]) - translations come from boot (frappe.boot.load_translations); English fallback.
export function setupTranslation(messages = {}) {
	window.__ = (text, args = []) => {
		let out = messages[text] || text
		args.forEach((arg, i) => (out = out.replaceAll(`{${i}}`, arg)))
		return out
	}
}
