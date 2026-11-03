"""Cancelling the vouchers a mobile document posted (visit, settlement, trip cancel chains).

The link fields on our documents can be typed in through a REST save of a draft, so a chain never cancels a
voucher on the strength of the link alone: the voucher must point back to the document (mobile_trip,
customer_visit, mobile_settlement), or the cancel is refused."""

import frappe
from frappe import _


def cancel_linked(doctype, name, **back_links):
	"""Cancel `doctype` `name` if submitted, after checking every back link (fieldname=value)."""
	if not name:
		return
	doc = frappe.get_doc(doctype, name)
	for fieldname, value in back_links.items():
		if doc.get(fieldname) != value:
			frappe.throw(
				_("{0} {1} was not posted by {2}; it is not cancelled with it.").format(
					_(doctype), frappe.bold(name), frappe.bold(value)
				),
				frappe.PermissionError,
			)
	if doc.docstatus == 1:
		doc.flags.ignore_permissions = True
		doc.cancel()


def keep_system_fields(doc, fieldnames):
	"""Update after submit: fields the app sets with db_set (status, links, summaries) keep their stored
	values, whatever the saved form sends (a stale form or a REST save)."""
	before = doc.get_doc_before_save()
	if not before:
		return
	for fieldname in fieldnames:
		value = before.get(fieldname)
		doc.set(fieldname, [row.as_dict() for row in value] if isinstance(value, list) else value)
