"""/mobile-sales-print?visit=CV-…: "Print All" for a visit (bill → invoice → return notes) on one page, each
document rendered by Frappe's own print view (print permission checked per document)."""

import frappe
from frappe.www.printview import get_html_and_style

from mobilesales.api import mobile as mobile_api
from mobilesales.services import prints

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=" + frappe.utils.quote(frappe.request.full_path)
		raise frappe.Redirect

	context.no_cache = 1
	visit = mobile_api.own_visit(frappe.form_dict.visit)  # agent: own trips only; supervisors: any
	context.title = visit.name
	context.pages = []
	styles = []
	for doctype, name, print_format in prints.visit_documents(visit):
		rendered = get_html_and_style(doctype, name, print_format, no_letterhead=1)
		context.pages.append(frappe._dict(doctype=doctype, name=name, print_format=print_format, html=rendered["html"]))
		if rendered["style"] not in styles:
			styles.append(rendered["style"])
	context.styles = styles
	return context
