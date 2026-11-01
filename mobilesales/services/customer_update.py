"""Customer master changes captured on a visit (spec §4.2, §5.1 step 4).

Old values are read from Customer, its primary Contact and primary Billing Address when the visit is
saved, so the day report can show before -> after. On submit the changes are applied directly or
left Pending Approval for a supervisor."""

import frappe
from frappe import _
from frappe.contacts.doctype.address.address import get_default_address
from frappe.contacts.doctype.contact.contact import get_default_contact

SUPERVISOR_ROLES = ("Mobile Sales Supervisor", "System Manager")

# field_key, label, visit field
UPDATE_FIELDS = (
	("customer.customer_name", "Customer Name", "new_customer_name"),
	("customer.tax_id", "Tax ID", "new_tax_id"),
	("contact.full_name", "Contact Person", "new_contact_person"),
	("contact.mobile_no", "Mobile No", "new_mobile_no"),
	("contact.email_id", "Email", "new_email"),
	("address.address_line1", "Address Line 1", "new_address_line1"),
	("address.city", "City", "new_city"),
)


def current_values(customer_name) -> dict:
	customer = frappe.get_doc("Customer", customer_name)
	values = {"customer.customer_name": customer.customer_name, "customer.tax_id": customer.tax_id}

	contact_name = customer.customer_primary_contact or get_default_contact("Customer", customer_name)
	if contact_name:
		contact = frappe.db.get_value(
			"Contact", contact_name, ["first_name", "last_name", "mobile_no", "email_id"], as_dict=True
		)
		values["contact.full_name"] = " ".join(filter(None, [contact.first_name, contact.last_name]))
		values["contact.mobile_no"] = contact.mobile_no
		values["contact.email_id"] = contact.email_id

	address_name = customer.customer_primary_address or get_default_address("Customer", customer_name)
	if address_name:
		address = frappe.db.get_value("Address", address_name, ["address_line1", "city"], as_dict=True)
		values["address.address_line1"] = address.address_line1
		values["address.city"] = address.city
	return values


def capture_changes(visit):
	"""Rebuild the Change rows from the entered new_* values (only real differences)."""
	visit.set("changes", [])
	if not visit.update_customer or not visit.customer:
		visit.customer_update_status = "Not Requested"
		return

	current = current_values(visit.customer)
	for key, label, fieldname in UPDATE_FIELDS:
		new_value = (visit.get(fieldname) or "").strip()
		old_value = current.get(key) or ""
		if new_value and new_value != old_value:
			visit.append(
				"changes", {"field_label": label, "field_key": key, "old_value": old_value, "new_value": new_value}
			)
	visit.customer_update_status = "Not Requested"


def on_visit_submit(visit, apply_directly: bool):
	if not visit.changes:
		return
	if apply_directly:
		apply_changes(visit, visit.changes)
		_set_status(visit, visit.changes, "Applied")
	else:
		_set_status(visit, visit.changes, "Pending Approval")


@frappe.whitelist()
def approve_customer_update(visit: str) -> str:
	frappe.only_for(SUPERVISOR_ROLES)
	doc = _pending_visit(visit)
	rows = [row for row in doc.changes if row.status == "Pending Approval"]
	apply_changes(doc, rows)
	_set_status(doc, rows, "Applied")
	return doc.customer_update_status


@frappe.whitelist()
def reject_customer_update(visit: str) -> str:
	frappe.only_for(SUPERVISOR_ROLES)
	doc = _pending_visit(visit)
	_set_status(doc, [row for row in doc.changes if row.status == "Pending Approval"], "Rejected")
	return doc.customer_update_status


def _pending_visit(name):
	doc = frappe.get_doc("Customer Visit", name, for_update=True)
	if doc.docstatus != 1 or doc.customer_update_status != "Pending Approval":
		frappe.throw(_("Customer Visit {0} has no customer update pending approval.").format(doc.name))
	return doc


def _set_status(visit, rows, status):
	for row in rows:
		row.db_set("status", status, update_modified=False)
	visit.db_set("customer_update_status", status)


def apply_changes(visit, rows):
	"""Write approved values to Customer, primary Contact and primary Billing Address
	(creating the Contact / Address when missing). Version log keeps the history."""
	values = {row.field_key: row.new_value for row in rows}
	if not values:
		return

	customer = frappe.get_doc("Customer", visit.customer)
	for key in ("customer.customer_name", "customer.tax_id"):
		if key in values:
			customer.set(key.split(".")[1], values[key])

	if any(key.startswith("contact.") for key in values):
		contact = _apply_contact(customer, values)
		customer.customer_primary_contact = contact.name
		customer.mobile_no = contact.mobile_no
		customer.email_id = contact.email_id

	if any(key.startswith("address.") for key in values):
		customer.customer_primary_address = _apply_address(customer, visit, values).name

	customer.flags.ignore_permissions = True
	customer.save()


def _apply_contact(customer, values):
	name = customer.customer_primary_contact or get_default_contact("Customer", customer.name)
	if name:
		contact = frappe.get_doc("Contact", name)
	else:
		contact = frappe.new_doc("Contact")
		contact.first_name = values.get("contact.full_name") or customer.customer_name
		contact.is_primary_contact = 1
		contact.append("links", {"link_doctype": "Customer", "link_name": customer.name})

	if values.get("contact.full_name"):
		contact.first_name = values["contact.full_name"]
		contact.last_name = ""
	if values.get("contact.mobile_no"):
		row = next((p for p in contact.phone_nos if p.is_primary_mobile_no), None)
		if row:
			row.phone = values["contact.mobile_no"]
		else:
			contact.append("phone_nos", {"phone": values["contact.mobile_no"], "is_primary_mobile_no": 1})
	if values.get("contact.email_id"):
		row = next((e for e in contact.email_ids if e.is_primary), None)
		if row:
			row.email_id = values["contact.email_id"]
		else:
			contact.append("email_ids", {"email_id": values["contact.email_id"], "is_primary": 1})

	contact.flags.ignore_permissions = True
	contact.save()
	return contact


def _apply_address(customer, visit, values):
	name = customer.customer_primary_address or get_default_address("Customer", customer.name)
	if name:
		address = frappe.get_doc("Address", name)
	else:
		if not (values.get("address.address_line1") and values.get("address.city")):
			frappe.throw(
				_("Customer {0} has no address yet: enter both Address Line 1 and City.").format(
					frappe.bold(customer.name)
				)
			)
		address = frappe.new_doc("Address")
		address.address_title = customer.customer_name
		address.address_type = "Billing"
		address.is_primary_address = 1
		address.country = frappe.get_cached_value("Company", visit.company, "country")
		address.append("links", {"link_doctype": "Customer", "link_name": customer.name})

	for key in ("address.address_line1", "address.city"):
		if values.get(key):
			address.set(key.split(".")[1], values[key])
	address.flags.ignore_permissions = True
	address.save()
	return address
