"""Phase 5: phone-app API (spec §6.2) and the SPA host page, every call as the real user (rule 13)."""

import base64
import json
import re
from unittest.mock import patch

import frappe
from frappe.utils import flt, nowdate
from frappe.utils.nestedset import get_root_of
from frappe.website.serve import get_response
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

import mobilesales
from mobilesales.api import mobile as api
from mobilesales.services import trip as trip_service
from mobilesales.tests.utils import PREFIX, MobileSalesTestCase, as_user, leaf
from mobilesales.www import mobile_sales as host_page

PNG_1PX = base64.b64encode(
	bytes.fromhex(
		"89504e470d0a1a0a0000000d4948445200000001000000010806000000"
		"1f15c4890000000d49444154789c6360f8cfc0f01f0005000201e2216bc80000000049454e44ae426082"
	)
).decode()


class TestMobileAPI(MobileSalesTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.settings.update({"default_customer_group": leaf("Customer Group"), "default_territory": leaf("Territory")})
		cls.route = frappe.get_doc(
			{
				"doctype": "Mobile Route",
				"route_name": f"{PREFIX} Route",
				"customers": [{"customer": cls.customer, "sequence": 1, "visit_frequency": "Daily"}],
			}
		).insert().name
		frappe.db.set_value("Mobile Sales Agent", cls.agent_a.name, "default_route", cls.route)

	def setUp(self):
		super().setUp()
		self.reason = frappe.get_doc({"doctype": "Visit No Sale Reason", "reason": f"{PREFIX} Reason", "category": "Price"}).insert().name

	# helpers

	def load_trip(self, agent, start=True, items=None):
		trip = frappe.get_doc(
			{
				"doctype": "Mobile Trip",
				"agent": agent.name,
				"trip_date": nowdate(),
				"load_items": items or [{"item_code": self.plain_item, "qty": 10}, {"item_code": self.batch_item, "qty": 4}],
			}
		)
		with as_user(self.users.store):
			trip.insert()
			trip.submit()
		if start:
			with as_user(agent.user):
				api.start_trip(trip.name)
		return frappe.get_doc("Mobile Trip", trip.name)

	def sale_payload(self, trip, ref, qty=2, collect=None):
		with as_user(frappe.db.get_value("Mobile Sales Agent", trip.agent, "user")):
			priced = api.price_cart(trip.name, self.customer, [{"item_code": self.plain_item, "qty": qty}])
		return {
			"client_ref": ref,
			"mobile_trip": trip.name,
			"customer": self.customer,
			"outcome": "Sale",
			"sale_items": [{"item_code": self.plain_item, "qty": qty}],
			"collect_amount": priced["rounded_total"] if collect is None else collect,
		}

	def standard_invoice(self, rate):
		si = frappe.get_doc(
			{"doctype": "Sales Invoice", "company": self.company, "customer": self.customer,
			 "items": [{"item_code": self.plain_item, "qty": 1, "rate": rate, "warehouse": self.store}]}
		).insert()  # fmt: skip
		si.submit()
		return si

	# access

	def test_non_agent_refused_by_every_method_and_host_page(self):
		trip = self.load_trip(self.agent_a)
		calls = [
			lambda: api.get_context(),
			lambda: api.get_van_stock(trip.name),
			lambda: api.get_route_plan(trip.name),
			lambda: api.search_customers("Test"),
			lambda: api.get_customer(self.customer),
			lambda: api.create_customer({"customer_name": "X"}),
			lambda: api.price_cart(trip.name, self.customer, []),
			lambda: api.submit_visit({"client_ref": "x", "mobile_trip": trip.name}),
			lambda: api.upload_visit_photo("a.png", PNG_1PX, client_ref="x"),
			lambda: api.get_visits(trip.name),
			lambda: api.start_trip(trip.name),
			lambda: api.end_day(trip.name),
			lambda: api.get_settlement_draft(trip.name),
			lambda: api.save_settlement(trip.name, {}),
			lambda: api.submit_settlement_for_verification("x"),
			lambda: api.get_receipt_escpos("Sales Invoice", "x"),
			lambda: api.outstanding_invoice_query("Sales Invoice", "", "name", 0, 10, {"customer": self.customer, "company": self.company}),
		]
		with as_user(self.users.office):
			for index, fn in enumerate(calls):
				with self.assertRaises(frappe.PermissionError, msg=f"call #{index}"):
					fn()
			context = host_page.get_context(frappe._dict())
			self.assertTrue(context.not_allowed)
			self.assertIsNone(context.boot)

		# The real page commits (to store the CSRF token); never let that happen inside a test.
		with as_user(self.agent_a.user), patch.object(frappe.db, "commit") as commit:
			context = host_page.get_context(frappe._dict())
			commit.assert_called_once()
			self.assertFalse(context.get("not_allowed"))
			self.assertEqual(context.boot["context"]["agent"]["name"], self.agent_a.name)
			self.assertTrue(context.boot["csrf_token"])

	def render_host_page(self, user):
		"""Full /mobile-sales render through Frappe's page renderer (context + template), as a logged-in user.
		The page commits the CSRF token; the commit is mocked (rule 14)."""
		previous = getattr(frappe.local, "request", None)
		frappe.local.request = Request(EnvironBuilder(path="/mobile-sales", base_url="http://localhost").get_environ())
		self.addCleanup(setattr, frappe.local, "request", previous)
		with as_user(user), patch.object(frappe.db, "commit"):
			response = get_response("mobile-sales")
		return response.status_code, response.get_data(as_text=True)

	def test_host_page_renders_for_every_logged_in_role(self):
		# Agent with an open trip: the boot data carries dates (trip_date) and must still render.
		trip = self.load_trip(self.agent_a)
		status, html = self.render_host_page(self.agent_a.user)
		self.assertEqual(status, 200, html[:2000])
		# ms_boot is a JS object literal (not a quoted / HTML-escaped string) with the keys the SPA reads.
		boot = json.loads(re.search(r"window\.ms_boot = (.*?);\n", html).group(1))
		self.assertIsInstance(boot, dict)
		self.assertEqual(set(boot), {"csrf_token", "site_name", "lang", "translations", "context"})
		self.assertEqual(boot["translations"], {})  # English: no Desk message set in the page
		self.assertEqual(
			set(boot["context"]),
			{"user", "full_name", "app_version", "agent", "trip", "last_trip", "settings", "no_sale_reasons", "return_reasons", "denominations"},
		)
		self.assertIn("window.ms_fail", html)  # on-screen "App failed to load" instead of a blank page
		self.assertEqual((boot["context"]["trip"]["name"], boot["context"]["trip"]["trip_date"]), (trip.name, str(trip.trip_date)))
		self.assertEqual(boot["context"]["agent"]["name"], self.agent_a.name)
		self.assertTrue(boot["csrf_token"])
		self.assertIn('<div id="app"></div>', html)

		# Agent without an open trip.
		status, html = self.render_host_page(self.agent_b.user)
		self.assertEqual(status, 200, html[:2000])
		self.assertIsNone(json.loads(re.search(r"window\.ms_boot = (.*?);\n", html).group(1))["context"]["trip"])

		# Supervisor (no agent record): the app shell loads; the SPA itself says "not set up as an agent".
		status, html = self.render_host_page(self.users.supervisor)
		self.assertEqual(status, 200, html[:2000])
		self.assertIsNone(json.loads(re.search(r"window\.ms_boot = (.*?);\n", html).group(1))["context"]["agent"])

		# Logged-in non-agent: the clear "not allowed" page, never a 500, and no boot data.
		status, html = self.render_host_page(self.users.office)
		self.assertEqual(status, 200, html[:2000])
		self.assertIn("This app is only for mobile sales agents.", html)
		self.assertNotIn("ms_boot", html)

	def test_agent_b_cannot_use_agent_a_data(self):
		trip = self.load_trip(self.agent_a)
		with as_user(self.agent_a.user):
			visit = api.submit_visit(self.sale_payload(trip, "a-1"))
		payload_b = self.sale_payload(trip, "b-1")  # priced as A, before switching to B
		with as_user(self.agent_b.user):
			for fn in (
				lambda: api.get_van_stock(trip.name),
				lambda: api.get_route_plan(trip.name),
				lambda: api.price_cart(trip.name, self.customer, [{"item_code": self.plain_item, "qty": 1}]),
				lambda: api.get_visits(trip.name),
				lambda: api.end_day(trip.name),
				lambda: api.submit_visit(payload_b),
				lambda: api.submit_visit({"client_ref": "a-1", "mobile_trip": trip.name}),  # A's client_ref leaks nothing
				lambda: api.upload_visit_photo("a.png", PNG_1PX, visit=visit["name"]),
				lambda: api.get_settlement_draft(trip.name),
				lambda: api.save_settlement(trip.name, {}),
				lambda: api.get_receipt_escpos("Sales Invoice", visit["sales_invoice"]),
			):
				with self.assertRaises(frappe.PermissionError):
					fn()

	def test_get_context_and_route_plan(self):
		trip = self.load_trip(self.agent_a)
		self.standard_invoice(250)
		with as_user(self.agent_a.user):
			ctx = api.get_context()
			self.assertEqual((ctx["agent"].name, ctx["trip"].name, ctx["trip"].status), (self.agent_a.name, trip.name, "In Field"))
			self.assertNotIn("cash_account", ctx["agent"])
			self.assertEqual((ctx["user"], ctx["app_version"]), (self.agent_a.user, mobilesales.__version__))  # account menu
			self.assertIn(self.reason, [r.name for r in ctx["no_sale_reasons"]])
			(row,) = api.get_route_plan(trip.name)
			self.assertEqual((row.customer, row.visited, row.outstanding), (self.customer, False, 250))
			api.submit_visit({"client_ref": "r-1", "mobile_trip": trip.name, "customer": self.customer, "outcome": "No Sale", "no_sale_reason": self.reason})
			(row,) = api.get_route_plan(trip.name)
			self.assertTrue(row.visited)
			self.assertIsNone(ctx["last_trip"])  # an open trip: no "last trip" line

		frappe.db.set_value("Mobile Trip", trip.name, {"status": "Settled", "invoiced_amount": 4536})  # test-only shortcut
		with as_user(self.agent_a.user):
			ctx = api.get_context()
		self.assertIsNone(ctx["trip"])
		self.assertEqual((ctx["last_trip"].name, ctx["last_trip"].status, ctx["last_trip"].invoiced_amount), (trip.name, "Settled", 4536))
		with as_user(self.agent_b.user):
			self.assertIsNone(api.get_context()["last_trip"])  # never another agent's trip

	def test_search_and_customer_card(self):
		trip = self.load_trip(self.agent_a)
		invoice = self.standard_invoice(120)
		with as_user(self.agent_a.user):
			self.assertEqual(api.search_customers("x"), [])
			self.assertIn(self.customer, [c.name for c in api.search_customers(PREFIX)])
			api.submit_visit(
				{"client_ref": "s-1", "mobile_trip": trip.name, "customer": self.customer, "outcome": "No Sale", "no_sale_reason": self.reason,
				 "shelf_stock": [{"item_code": self.plain_item, "qty_on_shelf": 7}]}
			)  # fmt: skip
			card = api.get_customer(self.customer)
		self.assertEqual([i.name for i in card["outstanding_invoices"]], [invoice.name])
		self.assertEqual(card["outstanding"], 120)
		self.assertEqual([(s.item_code, s.qty_on_shelf) for s in card["shelf_stock"]], [(self.plain_item, 7)])

	# pricing and visits

	def test_price_cart_matches_invoice_and_checks_limits(self):
		trip = self.load_trip(self.agent_a)
		with as_user(self.agent_a.user):
			priced = api.price_cart(trip.name, self.customer, [{"item_code": self.plain_item, "qty": 3}])
			(line,) = priced["lines"]
			self.assertEqual((line["rate"], line["amount"], line["enough_stock"]), (100, 300, True))
			self.assertFalse(api.price_cart(trip.name, self.customer, [{"item_code": self.plain_item, "qty": 11}])["lines"][0]["enough_stock"])
			with self.assertRaisesRegex(frappe.ValidationError, "above your limit"):
				api.price_cart(trip.name, self.customer, [{"item_code": self.plain_item, "qty": 1, "discount_percentage": 5}])
			with self.assertRaisesRegex(frappe.ValidationError, "quantity above 0"):
				api.price_cart(trip.name, self.customer, [{"item_code": self.plain_item, "qty": 0}])
			visit = api.submit_visit(self.sale_payload(trip, "p-1", qty=3))
		si = frappe.get_doc("Sales Invoice", visit["sales_invoice"])
		self.assertEqual((priced["net_total"], priced["grand_total"], priced["rounded_total"]), (si.net_total, si.grand_total, si.rounded_total))

	def test_submit_visit_is_idempotent_on_client_ref(self):
		trip = self.load_trip(self.agent_a)
		with as_user(self.agent_a.user):
			with self.assertRaisesRegex(frappe.ValidationError, "client_ref is required"):
				api.submit_visit({"mobile_trip": trip.name, "customer": self.customer, "outcome": "No Sale"})
			first = api.submit_visit(self.sale_payload(trip, "same-ref"))
			again = api.submit_visit(self.sale_payload(trip, "same-ref", qty=5))
		self.assertFalse(first["duplicate"])
		self.assertTrue(again["duplicate"])
		self.assertEqual((again["name"], again["sales_invoice"]), (first["name"], first["sales_invoice"]))
		self.assertEqual(frappe.db.count("Customer Visit", {"client_ref": "same-ref"}), 1)
		self.assertEqual(frappe.db.count("Sales Invoice", {"mobile_trip": trip.name, "docstatus": 1}), 1)
		self.assertEqual(frappe.db.get_value("Customer Visit", first["name"], "owner"), self.agent_a.user)

	def test_submit_visit_recomputes_totals_and_rules(self):
		trip = self.load_trip(self.agent_a)
		self.settings.allow_credit_sales = 0
		self.addCleanup(setattr, self.settings, "allow_credit_sales", 0)
		with as_user(self.agent_a.user):
			with self.assertRaisesRegex(frappe.ValidationError, "Credit sales are not allowed"):
				api.submit_visit(self.sale_payload(trip, "c-1", collect=1))
			payload = self.sale_payload(trip, "c-2")
			payload["grand_total"] = 1  # client totals are ignored
			visit = api.submit_visit(payload)
		self.assertEqual(visit["rounded_total"], 200)

	def test_upload_visit_photo(self):
		trip = self.load_trip(self.agent_a)
		with as_user(self.agent_a.user):
			visit = api.submit_visit({"client_ref": "ph-1", "mobile_trip": trip.name, "customer": self.customer, "outcome": "No Sale", "no_sale_reason": self.reason})
			with self.assertRaisesRegex(frappe.ValidationError, "Only JPEG, PNG or WebP"):
				api.upload_visit_photo("a.txt", base64.b64encode(b"hello").decode(), visit=visit["name"])
			result = api.upload_visit_photo("a.png", f"data:image/png;base64,{PNG_1PX}", client_ref="ph-1")
		self.assertEqual(frappe.db.get_value("Customer Visit", visit["name"], "check_in_photo"), result["file_url"])
		self.assertTrue(frappe.db.get_value("File", {"file_url": result["file_url"]}, "is_private"))

	# customers

	def test_create_customer(self):
		with as_user(self.agent_a.user):
			self.assertFalse(frappe.has_permission("Customer", "create"))
			created = api.create_customer({"customer_name": f"{PREFIX} Shop", "mobile_no": "0771 234 567", "address_line1": "1 Main St", "city": "Kandy"})
			again = api.create_customer({"customer_name": f"{PREFIX} Another", "mobile_no": "0771234567"})
			with self.assertRaisesRegex(frappe.ValidationError, "both address line 1 and city"):
				api.create_customer({"customer_name": f"{PREFIX} Half", "address_line1": "x"})
			self.assertFalse(frappe.has_permission("Customer", "create"))
		self.assertFalse(created["existing"])
		self.assertEqual((again["existing"], again["name"]), (True, created["name"]))
		customer = frappe.get_doc("Customer", created["name"])
		self.assertEqual((customer.owner, customer.mobile_no), (self.agent_a.user, "0771234567"))
		self.assertEqual((customer.customer_group, customer.territory), (self.settings.default_customer_group, self.settings.default_territory))
		self.assertEqual(frappe.db.get_value("Address", customer.customer_primary_address, "city"), "Kandy")
		self.assertFalse(frappe.db.exists("Custom DocPerm", {"parent": "Customer", "role": "Mobile Sales Agent", "create": 1}))

	def test_create_customer_group_territory_and_route(self):
		group = frappe.get_doc({"doctype": "Customer Group", "customer_group_name": f"{PREFIX} Group", "parent_customer_group": get_root_of("Customer Group")}).insert().name
		territory = frappe.get_doc({"doctype": "Territory", "territory_name": f"{PREFIX} Territory", "parent_territory": get_root_of("Territory")}).insert().name
		route = frappe.get_doc(
			{"doctype": "Mobile Route", "route_name": f"{PREFIX} New Route", "customers": [{"customer": self.customer, "sequence": 7}]}
		).insert().name
		closed = frappe.get_doc({"doctype": "Mobile Route", "route_name": f"{PREFIX} Closed Route", "is_active": 0}).insert().name
		with as_user(self.agent_a.user):
			options = api.get_customer_form_options()
			created = api.create_customer({"customer_name": f"{PREFIX} Route Shop", "customer_group": group, "territory": territory, "route": route})
			with self.assertRaisesRegex(frappe.ValidationError, "not an active route"):
				api.create_customer({"customer_name": f"{PREFIX} Closed Shop", "route": closed})
			with self.assertRaisesRegex(frappe.ValidationError, "is a group"):
				api.create_customer({"customer_name": f"{PREFIX} Group Shop", "customer_group": get_root_of("Customer Group")})
			with self.assertRaisesRegex(frappe.ValidationError, "not found"):
				api.create_customer({"customer_name": f"{PREFIX} Nowhere Shop", "territory": f"{PREFIX} Nowhere"})
			self.assertFalse(frappe.has_permission("Mobile Route", "write"))
		self.assertIn(group, options["customer_groups"])
		self.assertIn(territory, options["territories"])
		self.assertIn(route, options["routes"])
		self.assertNotIn(closed, options["routes"])
		self.assertNotIn(get_root_of("Territory"), options["territories"])
		self.assertEqual((options["default_customer_group"], options["default_territory"]), (self.settings.default_customer_group, self.settings.default_territory))

		customer = frappe.get_doc("Customer", created["name"])
		self.assertEqual((customer.customer_group, customer.territory, created["route"]), (group, territory, route))
		rows = [(r.customer, r.sequence) for r in frappe.get_doc("Mobile Route", route).customers]
		self.assertEqual(rows, [(self.customer, 7), (created["name"], 8)])
		self.assertFalse(frappe.db.exists("Custom DocPerm", {"parent": "Mobile Route"}))

	# settlement

	def test_settlement_through_api(self):
		trip = self.load_trip(self.agent_a, items=[{"item_code": self.plain_item, "qty": 5}])
		with as_user(self.agent_a.user):
			api.submit_visit(self.sale_payload(trip, "st-1", qty=2))
			api.end_day(trip.name)
			draft = api.get_settlement_draft(trip.name)
			self.assertEqual((draft["name"], draft["editable"], draft["stock_lines"][0]["expected_balance"]), (None, True, 3))
			counts = [{"denomination": 100, "count": 2}]
			# Returned 0 writes the whole van off: the app gets the warnings to confirm first
			careless = api.save_settlement(trip.name, {"stock_lines": [{"item_code": self.plain_item, "returned_qty": 0}], "denominations": [{"denomination": 100, "count": 1}]})
			item_name = frappe.db.get_value("Item", self.plain_item, "item_name")
			self.assertEqual(len(careless["warnings"]), 2)
			self.assertIn(f"3 Nos {item_name} will be recorded as MISSING", careless["warnings"][0])
			self.assertIn("Cash is SHORT by", careless["warnings"][1])
			saved = api.save_settlement(trip.name, {"stock_lines": [{"item_code": self.plain_item, "returned_qty": 3}], "denominations": counts})
			self.assertTrue(saved["name"])
			self.assertEqual(saved["warnings"], [])
			self.assertEqual((saved["cash_handed_over"], saved["cash_variance"], saved["workflow_state"]), (200, 0, "Draft"))
			submitted = api.submit_settlement_for_verification(saved["name"])
			self.assertEqual((submitted["workflow_state"], submitted["editable"]), ("Pending Store", False))
			with self.assertRaisesRegex(frappe.ValidationError, "can no longer be changed"):
				api.save_settlement(trip.name, {"stock_lines": [{"item_code": self.plain_item, "returned_qty": 1}]})
			again = api.submit_settlement_for_verification(saved["name"])  # double tap / retry after a timeout
			self.assertEqual((again["workflow_state"], again["duplicate"], submitted["duplicate"]), ("Pending Store", True, False))

	# printing

	def test_receipt_escpos(self):
		trip = self.load_trip(self.agent_a)
		standard = self.standard_invoice(90)
		with as_user(self.agent_a.user):
			visit = api.submit_visit(self.sale_payload(trip, "e-1"))
			invoice = api.get_receipt_escpos("Sales Invoice", visit["sales_invoice"], 32)
			receipt = api.get_receipt_escpos("Payment Entry", visit["payment_entry"])
			with self.assertRaises(frappe.PermissionError):
				api.get_receipt_escpos("Sales Invoice", standard.name)
			with self.assertRaisesRegex(frappe.ValidationError, "Sales Invoice and Payment Entry only"):
				api.get_receipt_escpos("Customer", self.customer)
		self.assertTrue(all(len(line) <= 32 for line in invoice["lines"]))
		self.assertIn(visit["sales_invoice"], invoice["text"])
		self.assertIn("TOTAL DUE", invoice["text"])
		self.assertIn(visit["sales_invoice"], receipt["text"])
		self.assertTrue(all(len(line) <= 48 for line in receipt["lines"]))

	def test_trip_status_through_api(self):
		trip = self.load_trip(self.agent_a, start=False)
		with as_user(self.agent_a.user):
			self.assertEqual(api.start_trip(trip.name), "In Field")
			draft = frappe.get_doc(
				{"doctype": "Customer Visit", "mobile_trip": trip.name, "customer": self.customer, "outcome": "No Sale", "no_sale_reason": self.reason}
			).insert()  # fmt: skip
			with self.assertRaisesRegex(frappe.ValidationError, "draft visits"):
				api.end_day(trip.name)
			frappe.delete_doc("Customer Visit", draft.name)
			self.assertEqual(api.end_day(trip.name), "Settling")
		self.assertEqual(flt(frappe.db.get_value("Mobile Trip", trip.name, "visits")), 0)
		self.assertEqual(trip_service.CLOSED_STATUSES, ("Settled", "Cancelled"))
