import frappe

SETTINGS_DOCTYPE = "Mobile Sales Settings"


def get_settings():
	"""Cached Mobile Sales Settings. Always call through this module so tests can patch it."""
	return frappe.get_cached_doc(SETTINGS_DOCTYPE)
