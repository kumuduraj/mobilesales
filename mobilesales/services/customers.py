"""Customer look-ups and quick entry for the mobile app (spec §6.1 Route / Visit screens)."""

import re

import frappe
from frappe import _
from frappe.contacts.doctype.address.address import get_default_address
from frappe.contacts.doctype.contact.contact import get_default_contact
from frappe.utils import cint, flt

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


def customer_lines(customer_names) -> dict:
	"""{customer: {address_line1, city, mobile_no}}: what tells two shops of the same name apart on the phone
	and in Desk link search. The primary address (else the first linked one) and the customer's mobile (else its
	primary contact's)."""
	names = list(dict.fromkeys(n for n in customer_names if n))
	if not names:
		return {}
	out = {
		row.name: frappe._dict(address_line1=None, city=None, mobile_no=row.mobile_no, _primary=row.customer_primary_address)
		for row in frappe.db.sql(
			"select name, mobile_no, customer_primary_address from `tabCustomer` where name in %s", (tuple(names),), as_dict=True
		)
	}
	for row in frappe.db.sql(
		"""select dl.link_name as customer, a.name, a.address_line1, a.city from `tabDynamic Link` dl
		join `tabAddress` a on a.name = dl.parent
		where dl.parenttype = 'Address' and dl.link_doctype = 'Customer' and dl.link_name in %s and a.disabled = 0
		order by a.is_primary_address desc, a.creation asc""",
		(tuple(names),),
		as_dict=True,
	):
		line = out.get(row.customer)
		if line is not None and (line.address_line1 is None or row.name == line._primary):
			line.address_line1, line.city = row.address_line1, row.city
			if row.name == line._primary:
				line._primary = "chosen"
	missing_mobile = [n for n, line in out.items() if not line.mobile_no]
	if missing_mobile:
		for row in frappe.db.sql(
			"""select dl.link_name as customer, c.mobile_no from `tabDynamic Link` dl join `tabContact` c on c.name = dl.parent
			where dl.parenttype = 'Contact' and dl.link_doctype = 'Customer' and dl.link_name in %s
				and ifnull(c.mobile_no, '') != ''
			order by c.is_primary_contact desc, c.creation asc""",
			(tuple(missing_mobile),),
			as_dict=True,
		):
			if not out[row.customer].mobile_no:
				out[row.customer].mobile_no = row.mobile_no
	for line in out.values():
		line.pop("_primary", None)
	return out


def identification(line) -> str:
	"""'No 1, Main Road, JA-ELA · …0002' (missing parts skipped); the phone formats the same fields alike."""
	place = ", ".join(p for p in ((line or {}).get("address_line1"), (line or {}).get("city")) if p)
	digits = re.sub(r"\D", "", (line or {}).get("mobile_no") or "")
	return " · ".join(p for p in (place, f"…{digits[-4:]}" if digits else "") if p)


def with_lines(rows, key="customer"):
	"""Add address_line1, city and mobile_no of each row's customer (rows: dicts with `key`)."""
	lines = customer_lines([r[key] for r in rows])
	for row in rows:
		line = lines.get(row[key]) or {}
		for field in ("address_line1", "city", "mobile_no"):
			row[field] = line.get(field)
	return rows


def search(text, limit) -> list[str]:
	"""Customers (enabled) whose name, mobile, or a linked address's line 1 or city contains the text."""
	like = f"%{text}%"
	digits = normalise_mobile(text)
	return [
		row[0]
		for row in frappe.db.sql(
			"""select distinct c.name, c.customer_name from `tabCustomer` c
			left join `tabDynamic Link` dl on dl.link_doctype = 'Customer' and dl.link_name = c.name
				and dl.parenttype in ('Address', 'Contact')
			left join `tabAddress` a on dl.parenttype = 'Address' and a.name = dl.parent
			left join `tabContact` ct on dl.parenttype = 'Contact' and ct.name = dl.parent
			where c.disabled = 0 and (c.name like %(like)s or c.customer_name like %(like)s or c.mobile_no like %(like)s
				or a.address_line1 like %(like)s or a.city like %(like)s
				or (%(digits)s != '' and (replace(replace(c.mobile_no, ' ', ''), '-', '') like %(dlike)s
					or replace(replace(ct.mobile_no, ' ', ''), '-', '') like %(dlike)s)))
			order by c.customer_name asc, c.name asc
			limit %(limit)s""",
			{"like": like, "digits": digits if len(digits) >= 3 else "", "dlike": f"%{digits}%", "limit": limit},
		)
	]


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def customer_query(doctype, txt, searchfield, start, page_len, filters):
	"""Desk link search for Customer on Customer Visit and Mobile Route: name, customer name and the line that
	tells same-named shops apart. Matches name, mobile, address line 1 and city like the phone."""
	if not frappe.has_permission("Customer", "read"):
		return []
	start, page_len = int(start or 0), int(page_len or 20)
	if txt:
		names = search(txt, start + page_len)[start:]
	else:
		names = frappe.get_all("Customer", filters={"disabled": 0}, pluck="name", order_by="customer_name asc",
			limit_start=start, limit_page_length=page_len)  # fmt: skip
	titles = dict(frappe.get_all("Customer", filters={"name": ["in", names or [""]]}, fields=["name", "customer_name"], as_list=True))
	lines = customer_lines(names)
	return [(name, titles.get(name) or name, identification(lines.get(name))) for name in names]


def pending_name_change(customer) -> str | None:
	"""The newest customer name still waiting for a supervisor (Customer Visit Change rows)."""
	rows = frappe.db.sql(
		"""select ch.new_value from `tabCustomer Visit Change` ch join `tabCustomer Visit` v on v.name = ch.parent
		where v.customer = %s and v.docstatus = 1 and ch.parenttype = 'Customer Visit'
			and ch.field_key = 'customer.customer_name' and ch.status = 'Pending Approval'
		order by v.visit_datetime desc, v.creation desc limit 1""",
		customer,
	)
	return rows[0][0] if rows else None


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
	# net of every submitted invoice and credit note: below 0 the phone shows "Credit" (v1.0.2)
	card["balance"] = flt(outstanding_by_customer([customer], company).get(customer, 0), 2)
	card["pending_name"] = pending_name_change(customer)
	card.update(with_lines([{"customer": customer}])[0])
	card.pop("customer", None)
	card["mobile_no"] = card["mobile_no"] or doc.mobile_no
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

	customer_group = data.customer_group or settings.default_customer_group
	territory = data.territory or settings.default_territory
	if not (customer_group and territory):
		frappe.throw(_("Set Default Customer Group and Default Territory in Mobile Sales Settings first."))
	_require_leaf("Customer Group", customer_group)
	_require_leaf("Territory", territory)
	if data.route and not frappe.db.get_value("Mobile Route", data.route, "is_active"):
		frappe.throw(_("Mobile Route {0} is not an active route.").format(frappe.bold(data.route)))

	existing = find_by_mobile(mobile)
	if existing:
		return {"name": existing, "customer_name": frappe.db.get_value("Customer", existing, "customer_name"), "existing": True}

	customer = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": name,
			"customer_type": "Company",
			"customer_group": customer_group,
			"territory": territory,
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
	if data.route:
		add_to_route(data.route, customer.name)
	return {"name": customer.name, "customer_name": customer.customer_name, "existing": False, "route": data.route or None}


def add_to_route(route, customer):
	"""Append the customer at the end of the route (agents have read only on Mobile Route)."""
	doc = frappe.get_doc("Mobile Route", route)
	if any(row.customer == customer for row in doc.customers):
		return
	last = max((cint(row.sequence) for row in doc.customers), default=0)
	doc.append("customers", {"customer": customer, "sequence": last + 1})
	doc.flags.ignore_permissions = True
	doc.save()


def form_options(settings) -> dict:
	"""Pickers of the new-customer form: leaf customer groups and territories, active routes, defaults."""
	return {
		"customer_groups": frappe.get_all("Customer Group", filters={"is_group": 0}, pluck="name", order_by="name asc"),
		"territories": frappe.get_all("Territory", filters={"is_group": 0}, pluck="name", order_by="name asc"),
		"routes": frappe.get_all("Mobile Route", filters={"is_active": 1}, pluck="name", order_by="name asc"),
		"default_customer_group": settings.default_customer_group,
		"default_territory": settings.default_territory,
	}


def _require_leaf(doctype, name):
	is_group = frappe.db.get_value(doctype, name, "is_group")
	if is_group is None:
		frappe.throw(_("{0} {1} not found.").format(_(doctype), frappe.bold(name)))
	if is_group:
		frappe.throw(_("{0} {1} is a group; choose one below it.").format(_(doctype), frappe.bold(name)))
