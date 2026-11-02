"""Host page of the Mobile Sales phone app (/mobile-sales). The SPA itself is built from frontend/."""

import json

import frappe
from frappe.translate import get_translations_from_apps

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
		translations=app_translations(frappe.local.lang),
	)
	# The template's tojson uses plain json.dumps (no dates); encode like /api/method responses do.
	context.boot = json.loads(frappe.as_json(boot))
	return context


def app_translations(lang: str) -> dict:
	"""Only this app's strings (the SPA's __()), not Desk's whole message set; English needs none."""
	if not lang or lang == "en":
		return {}
	return get_translations_from_apps(lang, ["mobilesales"])
