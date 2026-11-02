"""Whitelisted API for the mobile app (spec §6.2).

Every method first requires a Mobile Sales role, resolves the agent from frappe.session.user and re-checks
ownership of the trip / visit / settlement it touches. Inputs are validated and every number is recomputed
on the server; client totals are never trusted."""

import base64
from functools import partial

import frappe
from frappe import _
from frappe.model.workflow import apply_workflow
from frappe.utils import cint, cstr, flt, now_datetime, strip_html

from erpnext.stock.doctype.batch.batch import get_batch_qty

from mobilesales.services import customers, invoicing, receipts, reconciliation, returns, settlement
from mobilesales.services import settings as ms_settings
from mobilesales.services import trip as trip_service

AGENT_ROLE = "Mobile Sales Agent"
SUPERVISOR_ROLES = ("Mobile Sales Supervisor", "System Manager")
APP_ROLES = (AGENT_ROLE, *SUPERVISOR_ROLES)
VAN_STOCK_ROLES = ("Mobile Sales Supervisor", "Mobile Sales Store Keeper", "System Manager")
SETTLEMENT_VIEW_ROLES = (*VAN_STOCK_ROLES, "Mobile Sales Cashier")
PICKER_ROLES = (*APP_ROLES, "Mobile Sales Store Keeper", "Mobile Sales Cashier")
SETTINGS_FLAGS = (
	"company",
	"allow_credit_sales",
	"require_geolocation",
	"apply_customer_updates_directly",
	"selling_price_list",
	"returns_enabled",
)
VISIT_FIELDS = (
	"latitude",
	"longitude",
	"no_sale_reason",
	"remarks",
	"update_customer",
	"new_customer_name",
	"new_contact_person",
	"new_mobile_no",
	"new_email",
	"new_address_line1",
	"new_city",
	"new_tax_id",
	"collect_amount",
	"additional_discount_percentage",
	"discount_amount",
)
OUTCOMES = ("Sale", "No Sale", "Collection Only", "Shop Closed", "Return Only")
PHOTO_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
PHOTO_MAX_BYTES = 5 * 1024 * 1024
SEARCH_LIMIT = 20


# Access helpers


def require_roles(roles=APP_ROLES):
	if frappe.session.user == "Guest" or not set(roles) & set(frappe.get_roles()):
		frappe.throw(_("The Mobile Sales app is only for mobile sales agents."), frappe.PermissionError)


def is_supervisor() -> bool:
	return bool(set(SUPERVISOR_ROLES) & set(frappe.get_roles()))


def session_agent() -> frappe._dict | None:
	return frappe.db.get_value(
		"Mobile Sales Agent",
		{"user": frappe.session.user},
		[
			"name",
			"agent_name",
			"is_active",
			"van_warehouse",
			"cash_account",
			"mode_of_payment",
			"selling_price_list",
			"default_route",
			"max_discount_pct",
			"credit_limit_per_invoice",
			"max_return_value_per_visit",
		],
		as_dict=True,
	)


def own_trip(name, roles=APP_ROLES):
	"""The trip, if it belongs to the session agent (supervisors: any trip)."""
	require_roles(roles)
	if not name or not frappe.db.exists("Mobile Trip", name):
		frappe.throw(_("Mobile Trip {0} not found.").format(name))
	trip = frappe.get_doc("Mobile Trip", name)
	staff_roles = set(roles) - {AGENT_ROLE}  # supervisors, store keeper, cashier: any trip
	if not (trip_service.is_trip_agent(trip) or staff_roles & set(frappe.get_roles())):
		frappe.throw(_("This trip belongs to another agent."), frappe.PermissionError)
	return trip


def own_visit(name):
	require_roles()
	if not name or not frappe.db.exists("Customer Visit", name):
		frappe.throw(_("Customer Visit {0} not found.").format(name))
	visit = frappe.get_doc("Customer Visit", name)
	own_trip(visit.mobile_trip)
	return visit


# Context and van stock


@frappe.whitelist()
def get_context() -> dict:
	require_roles()
	agent = session_agent()
	trip = None
	if agent:
		trip = frappe.db.get_value(
			"Mobile Trip",
			{
				"agent": agent.name,
				"docstatus": ["<", 2],
				"status": ["not in", trip_service.CLOSED_STATUSES],
			},
			[
				"name",
				"status",
				"trip_date",
				"route",
				"vehicle",
				"helper",
				"van_warehouse",
				"docstatus",
				"visits",
				"sales_visits",
				"no_sale_visits",
				"invoices",
				"invoiced_amount",
				"collected_amount",
			],
			as_dict=True,
			order_by="creation desc",
		)
		agent.pop("cash_account", None)

	settings = ms_settings.get_settings()
	flags = {f: settings.get(f) for f in SETTINGS_FLAGS}
	flags["currency"] = settings.company and frappe.get_cached_value(
		"Company", settings.company, "default_currency"
	)
	return {
		"user": frappe.session.user,
		"full_name": frappe.utils.get_fullname(frappe.session.user),
		"agent": agent,
		"trip": trip,
		"settings": flags,
		"no_sale_reasons": frappe.get_all(
			"Visit No Sale Reason", fields=["name", "category", "requires_remark"], order_by="name asc"
		),
		"return_reasons": frappe.get_all("Mobile Return Reason", fields=["name", "requires_remark"], order_by="name asc"),
		"denominations": list(reconciliation.DENOMINATIONS),
	}


@frappe.whitelist()
def get_van_stock(trip: str) -> list[dict]:
	doc = own_trip(trip, roles=(*APP_ROLES, "Mobile Sales Store Keeper"))

	bin = frappe.qb.DocType("Bin")
	item = frappe.qb.DocType("Item")
	rows = (
		frappe.qb.from_(bin)
		.join(item)
		.on(bin.item_code == item.name)
		.select(
			bin.item_code,
			item.item_name,
			item.stock_uom,
			bin.actual_qty,
			bin.valuation_rate,
			item.image,
			item.has_batch_no,
		)
		.where((bin.warehouse == doc.van_warehouse) & (bin.actual_qty != 0))
		.orderby(bin.item_code)
		.run(as_dict=True)
	)
	for row in rows:
		row.batches = []
		if row.has_batch_no:
			row.batches = [
				{"batch_no": b.get("batch_no"), "qty": b.get("qty")}
				for b in get_batch_qty(warehouse=doc.van_warehouse, item_code=row.item_code)
				if b.get("qty")
			]
	return rows


# Route and customers


@frappe.whitelist()
def get_route_plan(trip: str) -> list[dict]:
	doc = own_trip(trip)
	if not doc.route:
		return []
	visited = set(
		frappe.get_all("Customer Visit", filters={"mobile_trip": doc.name, "docstatus": 1}, pluck="customer")
	)
	rows = frappe.get_all(
		"Mobile Route Customer",
		filters={"parent": doc.route, "parenttype": "Mobile Route"},
		fields=["customer", "customer_name", "sequence", "visit_frequency", "visit_day"],
		order_by="sequence asc, idx asc",
	)
	outstanding = customers.outstanding_by_customer([r.customer for r in rows], doc.company)
	for row in rows:
		row.visited = row.customer in visited
		row.outstanding = outstanding.get(row.customer, 0)
	return rows


@frappe.whitelist()
def search_customers(q: str = "") -> list[dict]:
	require_roles()
	q = (q or "").strip()
	if len(q) < 2:
		return []
	like = f"%{q}%"
	return frappe.get_all(
		"Customer",
		filters={"disabled": 0},
		or_filters={"name": ["like", like], "customer_name": ["like", like], "mobile_no": ["like", like]},
		fields=["name", "customer_name", "mobile_no", "territory"],
		order_by="customer_name asc",
		limit_page_length=SEARCH_LIMIT,
	)


@frappe.whitelist()
def get_customer(customer: str) -> dict:
	require_roles()
	if not customer or not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer {0} not found.").format(customer))
	company = ms_settings.get_settings().company
	card = customers.customer_card(customer, company)
	card["credit_available"] = returns.credit_available(customer, company)
	return card


@frappe.whitelist()
def create_customer(payload: str | dict) -> dict:
	require_roles()
	return customers.quick_create(frappe._dict(frappe.parse_json(payload) or {}), ms_settings.get_settings())


@frappe.whitelist()
def get_customer_form_options() -> dict:
	require_roles()
	return customers.form_options(ms_settings.get_settings())


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def return_invoice_query(doctype, txt, searchfield, start, page_len, filters):
	"""Against Invoice picker on return lines: one customer's submitted, non-return invoices of the
	company (optionally containing the item). Mobile or standard, never another customer's."""
	require_roles(PICKER_ROLES)
	filters = frappe._dict(filters or {})
	if not (filters.customer and filters.company):
		return []
	conditions = {
		"customer": filters.customer,
		"company": filters.company,
		"docstatus": 1,
		"is_return": 0,
		"name": ["like", f"%{txt}%"],
	}
	if filters.item_code:
		conditions["name"] = [
			"in",
			frappe.get_all("Sales Invoice Item", filters={"item_code": filters.item_code, "docstatus": 1}, pluck="parent")
			or [""],
		]
	return frappe.get_all(
		"Sales Invoice",
		filters=conditions,
		fields=["name", "posting_date", "grand_total"],
		order_by="posting_date desc, name desc",
		start=start,
		page_length=page_len,
		as_list=True,
	)


@frappe.whitelist()
def get_returnable_lines(invoice: str, customer: str) -> list[dict]:
	"""Lines of the customer's invoice that can still be returned, with qty left and net rate."""
	require_roles()
	owner = frappe.db.get_value("Sales Invoice", invoice, ["customer", "docstatus", "is_return"], as_dict=True)
	if not owner or owner.customer != customer or owner.docstatus != 1 or owner.is_return:
		frappe.throw(_("Sales Invoice {0} is not a submitted invoice of {1}.").format(invoice, customer))
	return [
		{
			"sales_invoice_item": line.name,
			"item_code": line.item_code,
			"item_name": line.item_name,
			"uom": line.uom,
			"returnable_qty": flt(line.returnable_qty),
			"rate": flt(line.net_rate),
			"batches": [{"batch_no": b, "qty": q} for b, q in line.batches.items() if flt(q) > 0],
		}
		for line in returns.returnable_lines(invoice)
	]


@frappe.whitelist()
def get_customer_invoices(customer: str) -> list[dict]:
	"""The customer's recent submitted, non-return invoices (return picker on the phone)."""
	require_roles()
	return frappe.get_all(
		"Sales Invoice",
		filters={"customer": customer, "company": ms_settings.get_settings().company, "docstatus": 1, "is_return": 0},
		fields=["name", "posting_date", "grand_total"],
		order_by="posting_date desc, name desc",
		limit_page_length=SEARCH_LIMIT,
	)


@frappe.whitelist()
def search_items(q: str = "") -> list[dict]:
	"""Active stock items without batches for returns without an invoice."""
	require_roles()
	q = (q or "").strip()
	if len(q) < 2:
		return []
	like = f"%{q}%"
	return frappe.get_all(
		"Item",
		filters={"disabled": 0, "is_stock_item": 1, "has_batch_no": 0},
		or_filters={"name": ["like", like], "item_name": ["like", like]},
		fields=["name as item_code", "item_name", "stock_uom"],
		order_by="item_name asc",
		limit_page_length=SEARCH_LIMIT,
	)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def outstanding_invoice_query(doctype, txt, searchfield, start, page_len, filters):
	"""Previous Outstanding picker on Customer Visit: submitted invoices of one customer and company with
	an outstanding balance. Served without the agent's own-trip invoice scope, but never wider."""
	require_roles(PICKER_ROLES)
	filters = frappe._dict(filters or {})
	if not (filters.customer and filters.company):
		return []
	return frappe.get_all(
		"Sales Invoice",
		filters={
			"customer": filters.customer,
			"company": filters.company,
			"docstatus": 1,
			"outstanding_amount": [">", 0],
			"name": ["like", f"%{txt}%"],
		},
		fields=["name", "posting_date", "outstanding_amount"],
		order_by="posting_date asc, name asc",
		start=start,
		page_length=page_len,
		as_list=True,
	)


# Pricing and visits


def _sale_rows(items) -> list[dict]:
	rows = []
	for raw in frappe.parse_json(items) or []:
		raw = frappe._dict(raw)
		if not raw.item_code or flt(raw.qty) <= 0:
			frappe.throw(_("Every cart line needs an item and a quantity above 0."))
		rows.append(
			{
				"item_code": raw.item_code,
				"qty": flt(raw.qty),
				"uom": raw.uom or None,
				"discount_percentage": flt(raw.discount_percentage),
				"discount_amount": flt(raw.discount_amount),
			}
		)
	return rows


def _return_rows(items) -> list[dict]:
	rows = []
	for raw in frappe.parse_json(items) or []:
		raw = frappe._dict(raw)
		if not raw.item_code or flt(raw.qty) <= 0:
			frappe.throw(_("Every return line needs an item and a quantity above 0."))
		rows.append(
			{
				"item_code": raw.item_code,
				"qty": flt(raw.qty),
				"uom": raw.uom or None,
				"against_invoice": raw.against_invoice or None,
				"sales_invoice_item": raw.sales_invoice_item or None,
				"return_reason": raw.return_reason,
				"condition": raw.condition if raw.condition in ("Resaleable", "Damaged") else "Resaleable",
				"remarks": raw.remarks or None,
			}
		)
	return rows


def _previous_rows(rows) -> list[dict]:
	return [
		{"sales_invoice": raw.sales_invoice, "allocated": max(flt(raw.allocated), 0)}
		for raw in (frappe._dict(r) for r in frappe.parse_json(rows) or [])
		if raw.sales_invoice
	]


@frappe.whitelist()
def price_cart(
	trip: str,
	customer: str,
	items: str | list,
	discount: str | dict | None = None,
	returns_items: str | list | None = None,
	collect_previous: str | list | None = None,
) -> dict:
	"""Prices a cart exactly as the invoice and credit notes will be priced (ERPNext pricing rules, taxes),
	checks the discount cap and the return limit, and plans the return credit set-off."""
	doc = own_trip(trip)
	if doc.docstatus != 1 or doc.status not in ("Loaded", "In Field"):
		frappe.throw(_("Trip {0} is {1}; nothing can be sold on it.").format(doc.name, _(doc.status)))
	if not frappe.db.exists("Customer", customer):
		frappe.throw(_("Customer {0} not found.").format(customer))
	rows = _sale_rows(items)
	return_rows = _return_rows(returns_items)
	discount = frappe._dict(frappe.parse_json(discount) or {})
	agent = frappe.db.get_value(
		"Mobile Sales Agent", doc.agent, ["max_discount_pct", "max_return_value_per_visit"], as_dict=True
	)
	settings = ms_settings.get_settings()

	cart = frappe.new_doc("Customer Visit")
	cart.update(
		{
			"mobile_trip": doc.name,
			"customer": customer,
			"company": doc.company,
			"visit_datetime": now_datetime(),
			"outcome": "Sale" if rows else "Return Only",
			"additional_discount_percentage": flt(discount.additional_discount_percentage),
			"discount_amount": flt(discount.discount_amount),
		}
	)
	for row in rows:
		cart.append("sale_items", row)
	for row in return_rows:
		cart.append("return_items", row)
	for row in _previous_rows(collect_previous):
		row["outstanding"] = flt(frappe.db.get_value("Sales Invoice", row["sales_invoice"], "outstanding_amount"))
		cart.append("collect_previous", row)
	notes = returns.validate_returns(cart, agent, settings) if return_rows else []
	result = {
		"lines": [],
		"net_total": 0,
		"total_taxes": 0,
		"grand_total": 0,
		"rounded_total": 0,
		"taxes": [],
		"discount_amount": 0,
		"additional_discount_percentage": 0,
		"manual_discount_pct": 0,
		"max_discount_pct": flt(agent.max_discount_pct),
		"returns": [
			{"item_code": r.item_code, "qty": r.qty, "uom": r.uom, "rate": r.rate, "amount": r.amount, "against_invoice": r.against_invoice}
			for r in cart.return_items
		],
		"return_total": flt(cart.return_total),
	}
	payable = 0.0
	if rows:
		result.update(_priced_sale(cart, doc, agent))
		payable = flt(result["rounded_total"])
	plan = returns.plan_set_off(cart, notes, payable)
	credit = returns.credit_by_target(plan)
	result["credit_applied"] = flt(sum(credit.values()), 2)
	result["credit_on_sale"] = flt(credit.get(returns.SALE, 0), 2)
	result["credit_on_previous"] = {k: flt(v, 2) for k, v in credit.items() if k != returns.SALE}
	result["due_on_sale"] = flt(payable - result["credit_on_sale"], 2)
	result["credit_left"] = flt(flt(cart.return_total) - result["credit_applied"], 2)
	return result


def _priced_sale(cart, doc, agent) -> dict:
	si = invoicing.build_invoice(cart, save=False)
	invoicing.check_discount_cap(si, agent.max_discount_pct)
	invoicing.copy_invoice_to_visit(cart, si)
	available = {}
	for code, qty in frappe.get_all(
		"Bin",
		filters={"warehouse": doc.van_warehouse, "item_code": ["in", [r.item_code for r in cart.sale_items]]},
		fields=["item_code", "actual_qty"],
		as_list=True,
	):
		available[code] = flt(qty)

	lines = []
	for row, item in zip(cart.sale_items, si.items, strict=False):
		lines.append(
			{
				"item_code": row.item_code,
				"item_name": item.item_name,
				"uom": row.uom,
				"conversion_factor": row.conversion_factor,
				"qty": row.qty,
				"stock_qty": row.stock_qty,
				"price_list_rate": row.price_list_rate,
				"pricing_rule_rate": row.pricing_rule_rate,
				"discount_percentage": row.discount_percentage,
				"discount_amount": row.discount_amount,
				"rate": row.rate,
				"amount": row.amount,
				"pricing_rules": item.pricing_rules,
				"available_in_van": available.get(row.item_code, 0),
				"enough_stock": flt(row.stock_qty, 6) <= flt(available.get(row.item_code, 0), 6),
			}
		)
	return {
		"lines": lines,
		"net_total": cart.net_total,
		"total_taxes": cart.total_taxes,
		"grand_total": cart.grand_total,
		"rounded_total": cart.rounded_total,
		"taxes": [{"description": t.description, "amount": t.tax_amount} for t in si.taxes],
		"discount_amount": cart.discount_amount,
		"additional_discount_percentage": cart.additional_discount_percentage,
		"manual_discount_pct": si.flags.manual_discount.percentage,
	}


def _visit_summary(visit) -> dict:
	return {
		"name": visit.name,
		"docstatus": visit.docstatus,
		"outcome": visit.outcome,
		"customer": visit.customer,
		"customer_name": visit.customer_name,
		"sales_invoice": visit.sales_invoice,
		"payment_entry": visit.payment_entry,
		"grand_total": visit.grand_total,
		"rounded_total": visit.rounded_total,
		"total_collected": visit.total_collected,
		"return_total": visit.get("return_total"),
		"credit_applied": visit.get("credit_applied"),
		"credit_notes": visit.get("credit_notes"),
		"credit_journal": visit.get("credit_journal"),
		"customer_update_status": visit.customer_update_status,
		"client_ref": visit.client_ref,
	}


@frappe.whitelist()
def submit_visit(payload: str | dict) -> dict:
	"""Create and submit a Customer Visit (and its invoice / payment). Idempotent on client_ref.
	A refused visit is logged in Mobile Visit Rejection, so the supervisor sees what the agent was told."""
	require_roles()
	data = frappe._dict(frappe.parse_json(payload) or {})
	try:
		return _submit_visit(data)
	except frappe.ValidationError as e:
		frappe.db.after_rollback.add(partial(log_rejection, data, e))  # `e` is unbound after the except block
		raise


def log_rejection(data, error):
	"""Runs after the request's rollback (the visit itself is gone), in its own small transaction."""
	try:
		frappe.get_doc(
			{
				"doctype": "Mobile Visit Rejection",
				"user": frappe.session.user,
				"agent": (session_agent() or {}).get("name"),
				"mobile_trip": data.mobile_trip if data.mobile_trip and frappe.db.exists("Mobile Trip", data.mobile_trip) else None,
				"customer": data.customer if data.customer and frappe.db.exists("Customer", data.customer) else None,
				"outcome": cstr(data.outcome)[:140],
				"client_ref": cstr(data.client_ref)[:140],
				"message": strip_html(cstr(error)).strip()[:2000] or error.__class__.__name__,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		# best effort: the agent already gets the message; never hide it behind a logging failure
		frappe.db.rollback()


def _submit_visit(data) -> dict:
	client_ref = (data.client_ref or "").strip()
	if not client_ref or len(client_ref) > 140:
		frappe.throw(_("client_ref is required."))

	existing = frappe.db.get_value("Customer Visit", {"client_ref": client_ref}, "name")
	if existing:
		return {**_visit_summary(own_visit(existing)), "duplicate": True}

	trip = own_trip(data.mobile_trip)
	if data.outcome not in OUTCOMES:
		frappe.throw(_("Choose a visit outcome."))
	if not data.customer or not frappe.db.exists("Customer", data.customer):
		frappe.throw(_("Choose a customer."))

	visit = frappe.new_doc("Customer Visit")
	visit.update(
		{
			"mobile_trip": trip.name,
			"customer": data.customer,
			"visit_datetime": now_datetime(),
			"outcome": data.outcome,
			"client_ref": client_ref,
			**{f: data.get(f) for f in VISIT_FIELDS if data.get(f) is not None},
		}
	)
	visit.update_customer = cint(data.update_customer)
	for row in _sale_rows(data.sale_items or []):
		visit.append("sale_items", row)
	for raw in frappe.parse_json(data.shelf_stock) or []:
		raw = frappe._dict(raw)
		if raw.item_code:
			visit.append(
				"shelf_stock",
				{
					"item_code": raw.item_code,
					"qty_on_shelf": flt(raw.qty_on_shelf),
					"uom": raw.uom,
					"expiry_date": raw.expiry_date or None,
					"competitor_item": raw.competitor_item,
					"remarks": raw.remarks,
				},
			)
	for row in _return_rows(data.return_items or []):
		visit.append("return_items", row)
	for row in _previous_rows(data.collect_previous):
		visit.append("collect_previous", row)

	try:
		visit.insert()
		visit.submit()
	except frappe.UniqueValidationError:
		# The same client_ref was submitted in parallel: return the visit that won.
		frappe.db.rollback()
		existing = frappe.db.get_value("Customer Visit", {"client_ref": client_ref}, "name")
		if not existing:
			raise
		return {**_visit_summary(own_visit(existing)), "duplicate": True}
	return {**_visit_summary(visit), "duplicate": False}


@frappe.whitelist()
def upload_visit_photo(
	filename: str, filedata: str, visit: str | None = None, client_ref: str | None = None
) -> dict:
	"""Attach a check-in photo (jpeg / png / webp, at most 5 MB) to the agent's own visit."""
	require_roles()
	if not visit and client_ref:
		visit = frappe.db.get_value("Customer Visit", {"client_ref": client_ref}, "name")
	doc = own_visit(visit)

	content = base64.b64decode((filedata or "").split(",")[-1], validate=True)
	if len(content) > PHOTO_MAX_BYTES:
		frappe.throw(_("Photo is larger than 5 MB."))
	content_type = _image_type(content)
	if not content_type:
		frappe.throw(_("Only JPEG, PNG or WebP photos can be uploaded."))

	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": f"{doc.name}-check-in.{PHOTO_TYPES[content_type]}",
			"attached_to_doctype": "Customer Visit",
			"attached_to_name": doc.name,
			"attached_to_field": "check_in_photo",
			"is_private": 1,
			"content": content,
		}
	)
	file.flags.ignore_permissions = True
	file.insert()
	doc.db_set("check_in_photo", file.file_url, update_modified=False)
	return {"file_url": file.file_url, "visit": doc.name}


def _image_type(content: bytes) -> str | None:
	if content.startswith(b"\xff\xd8\xff"):
		return "image/jpeg"
	if content.startswith(b"\x89PNG\r\n\x1a\n"):
		return "image/png"
	if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
		return "image/webp"
	return None


@frappe.whitelist()
def get_visits(trip: str) -> list[dict]:
	"""The trip's visits for the History screen."""
	doc = own_trip(trip)
	return frappe.get_all(
		"Customer Visit",
		filters={"mobile_trip": doc.name, "docstatus": ["<", 2]},
		fields=[
			"name",
			"docstatus",
			"visit_datetime",
			"customer",
			"customer_name",
			"off_route",
			"outcome",
			"no_sale_reason",
			"sales_invoice",
			"payment_entry",
			"credit_notes",
			"return_total",
			"credit_applied",
			"grand_total",
			"rounded_total",
			"total_collected",
		],
		order_by="visit_datetime desc",
	)


# Trip status


@frappe.whitelist()
def start_trip(trip: str) -> str:
	own_trip(trip)
	return trip_service.start_trip(trip)


@frappe.whitelist()
def end_day(trip: str) -> str:
	own_trip(trip)
	return trip_service.end_day(trip)


@frappe.whitelist()
def reopen_trip(trip: str) -> str:
	own_trip(trip)
	return trip_service.reopen_trip(trip)


# Settlement


def _settlement_payload(doc) -> dict:
	data = doc.as_dict(no_default_fields=True)
	data["name"] = doc.name if not doc.is_new() else None
	data["workflow_state"] = doc.get("workflow_state") or "Draft"
	data["docstatus"] = doc.docstatus
	data["editable"] = bool(doc.is_new() or (doc.docstatus == 0 and data["workflow_state"] == "Draft"))
	data["warnings"] = settlement_warnings(doc)
	return data


def settlement_warnings(doc) -> list[str]:
	"""What Submit for Verification will record against the agent: shown in a confirm dialog first."""
	warnings = []
	for row in doc.stock_lines:
		if flt(row.missing_qty) > 0:
			warnings.append(
				_("{0} {1} {2} will be recorded as MISSING").format(
					frappe.format(flt(row.missing_qty), "Float"), row.uom, row.item_name or row.item_code
				)
			)
	variance = flt(doc.cash_variance, 2)
	currency = frappe.get_cached_value("Company", doc.company, "default_currency") if doc.company else None
	if variance < 0:
		warnings.append(_("Cash is SHORT by {0}").format(frappe.format(-variance, {"fieldtype": "Currency", "options": currency})))
	elif variance > 0:
		warnings.append(_("Cash is OVER by {0}").format(frappe.format(variance, {"fieldtype": "Currency", "options": currency})))
	return warnings


@frappe.whitelist()
def get_settlement_draft(trip: str) -> dict:
	"""The trip's open settlement as saved, or a computed draft when none exists yet (nothing saved)."""
	doc = own_trip(trip, roles=SETTLEMENT_VIEW_ROLES + (AGENT_ROLE,))
	existing = settlement.open_settlement(doc.name)
	if existing:
		return _settlement_payload(frappe.get_doc("Mobile Settlement", existing))
	draft = frappe.new_doc("Mobile Settlement")
	draft.mobile_trip = trip
	reconciliation.refresh_settlement(draft)
	return _settlement_payload(draft)


@frappe.whitelist()
def save_settlement(trip: str, payload: str | dict) -> dict:
	"""Agent fields only (returned / damaged / damaged batch per item, denomination counts, cash handed
	over), and only while the settlement is in Draft."""
	doc_trip = own_trip(trip)
	data = frappe._dict(frappe.parse_json(payload) or {})
	name = settlement.open_settlement(doc_trip.name) or settlement.make_settlement(doc_trip.name)
	doc = frappe.get_doc("Mobile Settlement", name)
	if doc.docstatus != 0 or (doc.workflow_state or "Draft") != "Draft":
		frappe.throw(_("Settlement {0} is {1}; it can no longer be changed from the app.").format(doc.name, _(doc.workflow_state)))

	lines = {frappe._dict(r).item_code: frappe._dict(r) for r in frappe.parse_json(data.stock_lines) or []}
	for row in doc.stock_lines:
		entered = lines.get(row.item_code)
		if entered:
			row.returned_qty = flt(entered.returned_qty)
			row.damaged_qty = flt(entered.damaged_qty)
			row.damaged_batch_no = entered.damaged_batch_no or None
	counts = {flt(frappe._dict(r).denomination): cint(frappe._dict(r).count) for r in frappe.parse_json(data.denominations) or []}
	for row in doc.denominations:
		if flt(row.denomination) in counts:
			row.count = max(counts[flt(row.denomination)], 0)
	if data.get("cash_handed_over") is not None:
		doc.cash_handed_over = flt(data.cash_handed_over)
	doc.save()
	return _settlement_payload(doc)


@frappe.whitelist()
def submit_settlement_for_verification(settlement_name: str) -> dict:
	require_roles()
	if not frappe.db.exists("Mobile Settlement", settlement_name):
		frappe.throw(_("Mobile Settlement {0} not found.").format(settlement_name))
	doc = frappe.get_doc("Mobile Settlement", settlement_name)
	own_trip(doc.mobile_trip)
	if (doc.workflow_state or "Draft") != "Draft":
		frappe.throw(_("Settlement {0} is already {1}.").format(doc.name, _(doc.workflow_state)))
	apply_workflow(doc, "Submit for Verification")
	return _settlement_payload(frappe.get_doc("Mobile Settlement", settlement_name))


# Printing


@frappe.whitelist()
def get_receipt_escpos(doctype: str, name: str, width: int = 48) -> dict:
	"""Plain-text receipt lines (for a later ESC/POS hand-off) for the agent's own mobile documents."""
	require_roles()
	if doctype not in receipts.SUPPORTED:
		frappe.throw(_("Receipts are available for Sales Invoice and Payment Entry only."))
	if not frappe.db.exists(doctype, name):
		frappe.throw(_("{0} {1} not found.").format(_(doctype), name))
	doc = frappe.get_doc(doctype, name)
	if not doc.get("mobile_trip"):
		frappe.throw(_("{0} is not a mobile document.").format(name), frappe.PermissionError)
	own_trip(doc.mobile_trip)
	lines = receipts.render(doc, max(24, min(cint(width) or 48, 64)))
	return {"lines": lines, "text": "\n".join(lines)}
