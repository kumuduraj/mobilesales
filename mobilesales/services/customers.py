"""Customer look-ups and quick entry for the mobile app (spec §6.1 Route / Visit screens)."""

import re

import frappe
from frappe import _
from frappe.contacts.doctype.address.address import get_default_address
from frappe.contacts.doctype.contact.contact import get_default_contact
from frappe.utils import flt

from mobilesales.services import customer_update


def outstanding_by_customer(customer_names, company) -> dict:
	if not customer_names:
		return {}
	return {
		row.customer: flt(row.outstanding)
		for row in frappe.db.sql(
			"""select customer, sum(outstanding_amount) as outstanding from `tabSales Invoice`
			where docstatus = 1 and company = %s and customer in %s group by customer""",
			(company, tuple(customer_names)),
			as_dict=True,
		)
	}


def outstanding_invoices(customer, company) -> list[dict]:
	"""Same rule as the Previous Outstanding picker: submitted, outstanding, this customer and company."""
	return frappe.get_all(
		"Sales Invoice",
		filters={"customer": customer, "company": company, "docstatus": 1, "outstanding_amount": [">", 0]},
		fields=["name", "posting_date", "grand_total", "rounded_total", "outstanding_amount"],
		order_by="posting_date asc, name asc",
	)


def last_shelf_stock(customer) -> list[dict]:
	"""Latest counted shelf quantity per item from the customer's submitted visits."""
	rows = frappe.db.sql(
		"""select s.item_code, s.qty_on_shelf, s.uom, s.expiry_date, s.competitor_item, v.visit_datetime
		from `tabCustomer Visit Shelf Stock` s
		join `tabCustomer Visit` v on v.name = s.parent and s.parenttype = 'Customer Visit'
		where v.customer = %s and v.docstatus = 1
		order by v.visit_datetime desc, s.idx asc""",
		customer,
		as_dict=True,
	)
	latest = {}
	for row in rows:
		latest.setdefault(row.item_code, row)
	return list(latest.values())


def customer_card(customer, company) -> dict:
	doc = frappe.get_doc("Customer", customer)
	card = {
		"name": doc.name,
		"customer_name": doc.customer_name,
		"customer_group": doc.customer_group,
		"territory": doc.territory,
		"tax_id": doc.tax_id,
		"mobile_no": doc.mobile_no,
		"email_id": doc.email_id,
		"contact": None,
		"address": None,
	}
	contact = doc.customer_primary_contact or get_default_contact("Customer", customer)
	if contact:
		card["contact"] = frappe.db.get_value(
			"Contact", contact, ["name", "first_name", "last_name", "mobile_no", "email_id"], as_dict=True
		)
	address = doc.customer_primary_address or get_default_address("Customer", customer)
	if address:
		card["address"] = frappe.db.get_value(
			"Address", address, ["name", "address_line1", "city", "country"], as_dict=True
		)
	invoices = outstanding_invoices(customer, company)
	card["outstanding_invoices"] = invoices
	card["outstanding"] = sum(flt(i.outstanding_amount) for i in invoices)
	card["shelf_stock"] = last_shelf_stock(customer)
	return card


def normalise_mobile(value) -> str:
	return re.sub(r"[^0-9+]", "", value or "")


def find_by_mobile(mobile) -> str | None:
	if not mobile:
		return None
	customer = frappe.db.get_value("Customer", {"mobile_no": mobile, "disabled": 0}, "name")
	if customer:
		return customer
	contact = frappe.db.get_value("Contact Phone", {"phone": mobile, "parenttype": "Contact"}, "parent")
	if contact:
		return frappe.db.get_value(
			"Dynamic Link", {"parent": contact, "parenttype": "Contact", "link_doctype": "Customer"}, "link_name"
		)
	return None


def quick_create(data, settings) -> dict:
	"""Create a customer from the phone. Runs with ignore_permissions (agents have no Customer create
	right); the owner is the agent. A known mobile number returns the existing customer instead."""
	name = (data.customer_name or "").strip()
	mobile = normalise_mobile(data.mobile_no)
	line1, city = (data.address_line1 or "").strip(), (data.city or "").strip()
	if not name:
		frappe.throw(_("Customer name is required."))
	if mobile and len(re.sub(r"\D", "", mobile)) < 9:
		frappe.throw(_("Mobile number looks too short."))
	if bool(line1) != bool(city):
		frappe.throw(_("Enter both address line 1 and city, or neither."))

	existing = find_by_mobile(mobile)
	if existing:
		return {"name": existing, "customer_name": frappe.db.get_value("Customer", existing, "customer_name"), "existing": True}

	if not (settings.default_customer_group and settings.default_territory):
		frappe.throw(_("Set Default Customer Group and Default Territory in Mobile Sales Settings first."))

	customer = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": name,
			"customer_type": "Company",
			"customer_group": settings.default_customer_group,
			"territory": settings.default_territory,
		}
	)
	customer.flags.ignore_permissions = True
	customer.insert()

	values = {}
	if mobile:
		values["contact.mobile_no"] = mobile
		values["contact.full_name"] = name
	if line1:
		values.update({"address.address_line1": line1, "address.city": city})
	if values:
		visit_like = frappe._dict(customer=customer.name, company=settings.company)
		rows = [frappe._dict(field_key=k, new_value=v) for k, v in values.items()]
		customer_update.apply_changes(visit_like, rows)
	return {"name": customer.name, "customer_name": customer.customer_name, "existing": False}
