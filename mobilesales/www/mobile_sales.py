"""Host page of the Mobile Sales phone app (/mobile-sales). The SPA itself is built from frontend/."""

import frappe
from frappe.boot import load_translations

from mobilesales.api import mobile as mobile_api

no_cache = 1


def get_context(context):
	if frappe.session.user == "Guest":
		frappe.local.flags.redirect_location = "/login?redirect-to=/mobile-sales"
		raise frappe.Redirect

	context.no_cache = 1
	if not set(mobile_api.APP_ROLES) & set(frappe.get_roles()):
		context.not_allowed = True
		context.boot = None
		return context

	csrf_token = frappe.sessions.get_csrf_token()
	frappe.db.commit()  # the CSRF token is stored on the session (same as Frappe's own SPA hosts)
	boot = frappe._dict(
		csrf_token=csrf_token,
		site_name=frappe.local.site,
		lang=frappe.local.lang,
		context=mobile_api.get_context(),
	)
	load_translations(boot)
	boot.messages = boot.pop("__messages", {})
	context.boot = boot
	return context
