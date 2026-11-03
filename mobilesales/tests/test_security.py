"""Phase 7 security review (docs/SECURITY_REVIEW.md): forged links on our documents, the agent's view of masters
and office data, input limits and the per-user throttle. Every flow runs as the real role user (rule 13)."""

import base64
from unittest.mock import patch

import frappe
from frappe.desk.query_report import run as run_report
from frappe.desk.search import search_link
from frappe.utils import now_datetime
from frappe.www.printview import get_html_and_style

from mobilesales.api import mobile as api
from mobilesales.services import reports, settlement, vouchers
from mobilesales.tests.test_api import PNG_1PX
from mobilesales.tests.test_settlement import CASHIER, STORE_KEEPER, SUPERVISOR, SettlementTestBase
from mobilesales.tests.utils import PREFIX, as_user, leaf, make_receipt
from mobilesales.www import mobile_sales_print


class TestSecurity(SettlementTestBase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		currency = frappe.get_cached_value("Company", cls.company, "default_currency")
		cls.buying_list = frappe.get_doc(
			{"doctype": "Price List", "price_list_name": f"{PREFIX} Buying", "buying": 1, "selling": 0, "currency": currency}
		).insert().name
		cls.buying_price = frappe.get_doc(
			{"doctype": "Item Price", "item_code": cls.plain_item, "price_list": cls.buying_list, "price_list_rate": 40}
		).insert().name
		cls.selling_price = frappe.db.get_value("Item Price", {"item_code": cls.plain_item, "price_list": cls.price_list})
		cls.other_customer = frappe.get_doc(
			{"doctype": "Customer", "customer_name": f"{PREFIX} Other Customer", "customer_group": leaf("Customer Group"), "territory": leaf("Territory")}
		).insert().name  # fmt: skip

	def setUp(self):
		super().setUp()
		self.reason = frappe.get_doc({"doctype": "Visit No Sale Reason", "reason": f"{PREFIX} Reason", "category": "Price"}).insert().name

	def office_invoice(self, customer=None):
		si = frappe.get_doc(
			{"doctype": "Sales Invoice", "company": self.company, "customer": customer or self.customer, "update_stock": 1,
			 "items": [{"item_code": self.plain_item, "qty": 1, "rate": 90, "warehouse": self.store}]}
		).insert()  # fmt: skip
		si.submit()
		return si

	# S1: links on a visit are the app's, never the client's

	def test_forged_visit_links_are_cleared_and_never_cancelled(self):
		office = self.office_invoice()
		trip = self.run_trip([(self.plain_item, 2)], end_day=False)
		forged = {"sales_invoice": office.name, "credit_notes": office.name}
		with as_user(self.agent_a.user):
			# What a REST POST / PUT on Customer Visit can carry
			visit = frappe.get_doc(
				{"doctype": "Customer Visit", "mobile_trip": trip.name, "customer": self.customer, "visit_datetime": now_datetime(),
				 "outcome": "No Sale", "no_sale_reason": self.reason, **forged}
			).insert()  # fmt: skip
			self.assertEqual((visit.sales_invoice, visit.credit_notes), (None, None))
			visit.update(forged)
			visit.submit()
			visit = frappe.get_doc("Customer Visit", visit.name)
			visit.update(forged)  # update after submit
			visit.save()
		self.assertEqual(frappe.db.get_value("Customer Visit", visit.name, ["sales_invoice", "credit_notes"]), (None, None))

		# Even a link written straight to the database is not followed by the cancel chain.
		frappe.db.set_value("Customer Visit", visit.name, "sales_invoice", office.name)
		with as_user(SUPERVISOR), self.assertRaisesRegex(frappe.PermissionError, "was not posted by"):
			frappe.get_doc("Customer Visit", visit.name).cancel()
		self.assertEqual(frappe.db.get_value("Sales Invoice", office.name, "docstatus"), 1)

	# S2: settlement postings and verifiers

	def test_forged_settlement_links_and_verifiers_are_cleared(self):
		office_se = make_receipt(self.company, self.plain_item, 1, self.store)
		trip = self.run_trip([(self.plain_item, 2)], opening_cash_float=100)
		with as_user(self.agent_a.user):
			doc = frappe.get_doc("Mobile Settlement", settlement.make_settlement(trip.name))
			doc.update({"return_entry": office_se.name, "recovery_journal": trip.opening_float_journal,
				"verified_by_store": STORE_KEEPER, "verified_by_cashier": CASHIER})  # fmt: skip
			doc.save()
		stored = frappe.db.get_value(
			"Mobile Settlement", doc.name, ["return_entry", "recovery_journal", "verified_by_store", "verified_by_cashier"]
		)
		self.assertEqual(stored, (None, None, None, None))

		approved = self.approve_flow(self.draft(trip, returned={self.plain_item: 2}).name)
		self.assertEqual((approved.verified_by_store, approved.verified_by_cashier), (STORE_KEEPER, CASHIER))
		posted = approved.return_entry
		self.assertEqual(frappe.db.get_value("Stock Entry", posted, "mobile_trip"), trip.name)

		with as_user(SUPERVISOR):
			doc = frappe.get_doc("Mobile Settlement", approved.name)
			doc.update({"return_entry": office_se.name, "verified_by_store": SUPERVISOR})
			try:
				doc.save()  # update after submit: kept as stored (or refused by the workflow)
			except (frappe.ValidationError, frappe.PermissionError):
				pass
		self.assertEqual(
			frappe.db.get_value("Mobile Settlement", approved.name, ["return_entry", "verified_by_store"]), (posted, STORE_KEEPER)
		)

		frappe.db.set_value("Mobile Settlement", approved.name, "cash_journal", trip.opening_float_journal)
		with self.assertRaisesRegex(frappe.PermissionError, "was not posted by"):
			self.act(approved.name, "Cancel", SUPERVISOR)
		self.assertEqual(frappe.db.get_value("Journal Entry", trip.opening_float_journal, "docstatus"), 1)

	def test_cancel_chain_refuses_foreign_vouchers(self):
		office_se = make_receipt(self.company, self.plain_item, 1, self.store)
		trip = self.run_trip([(self.plain_item, 1)], end_day=False)
		with self.assertRaisesRegex(frappe.PermissionError, "was not posted by"):
			vouchers.cancel_linked("Stock Entry", office_se.name, mobile_trip=trip.name)
		self.assertEqual(frappe.db.get_value("Stock Entry", office_se.name, "docstatus"), 1)

	def test_submitted_trip_keeps_system_fields(self):
		trip = self.run_trip([(self.plain_item, 2)], end_day=False)
		with as_user(STORE_KEEPER):
			doc = frappe.get_doc("Mobile Trip", trip.name)
			doc.update({"status": "Settled", "invoiced_amount": 999, "opening_float_journal": None})
			doc.set("stock_entries", [])
			doc.save()
		trip.reload()
		self.assertEqual((trip.status, trip.invoiced_amount, len(trip.stock_entries)), ("In Field", 0, 1))

	# S3-S6: masters an agent reads for invoicing

	def test_agent_sees_selling_prices_customer_contacts_own_bundles_and_receivables(self):
		trip = self.run_trip([(self.batch_item, 1)], end_day=False)
		sale = self.sell(trip.name, [(self.batch_item, 1)])
		own_bundle = frappe.db.get_value("Sales Invoice Item", {"parent": sale.sales_invoice}, "serial_and_batch_bundle")
		office_bundle = frappe.db.get_value(
			"Serial and Batch Bundle", {"item_code": self.batch_item, "owner": "Administrator", "docstatus": 1}
		)
		contact = frappe.get_doc(
			{"doctype": "Contact", "first_name": f"{PREFIX} Shop Owner", "links": [{"link_doctype": "Customer", "link_name": self.customer}]}
		).insert().name
		private = frappe.get_doc({"doctype": "Contact", "first_name": f"{PREFIX} Office Contact"}).insert().name
		address = dict(address_line1="1 Main St", city="Kandy", country=frappe.get_cached_value("Company", self.company, "country"))
		shop_address = frappe.get_doc(
			{"doctype": "Address", "address_title": f"{PREFIX} Shop", **address, "links": [{"link_doctype": "Customer", "link_name": self.customer}]}
		).insert().name
		office_address = frappe.get_doc({"doctype": "Address", "address_title": f"{PREFIX} Office", **address}).insert().name
		receivable = frappe.get_cached_value("Company", self.company, "default_receivable_account")

		with as_user(self.agent_a.user):
			prices = frappe.get_list("Item Price", filters={"item_code": self.plain_item}, pluck="name")
			self.assertIn(self.selling_price, prices)
			self.assertNotIn(self.buying_price, prices)
			self.assertFalse(frappe.has_permission("Item Price", "read", doc=self.buying_price))
			contacts = frappe.get_list("Contact", pluck="name", limit_page_length=0)
			self.assertIn(contact, contacts)
			self.assertNotIn(private, contacts)
			self.assertFalse(frappe.has_permission("Contact", "read", doc=private))
			addresses = frappe.get_list("Address", pluck="name", limit_page_length=0)
			self.assertIn(shop_address, addresses)
			self.assertNotIn(office_address, addresses)
			self.assertFalse(frappe.has_permission("Address", "read", doc=office_address))
			bundles = frappe.get_list("Serial and Batch Bundle", pluck="name", limit_page_length=0)
			self.assertIn(own_bundle, bundles)
			self.assertNotIn(office_bundle, bundles)
			self.assertFalse(frappe.has_permission("Serial and Batch Bundle", "read", doc=office_bundle))
			self.assertFalse(frappe.has_permission("Serial and Batch Bundle", "write", doc=office_bundle))
			accounts = [r["value"] for r in search_link("Account", "", page_length=1000)]
			self.assertIn(receivable, accounts)
			self.assertIn(self.agent_a.cash_account, accounts)
			self.assertNotIn(self.agent_b.cash_account, accounts)
			self.assertNotIn(self.cash_shortage, accounts)

		# Staff keep the standard view.
		with as_user(SUPERVISOR):
			self.assertIn(self.buying_price, frappe.get_list("Item Price", filters={"item_code": self.plain_item}, pluck="name"))
		with as_user(self.users.office):
			self.assertTrue(frappe.has_permission("Contact", "read", doc=private))
			self.assertTrue(frappe.has_permission("Serial and Batch Bundle", "read", doc=office_bundle))

	# S7-S11: inputs and throttle

	def test_inputs_are_bounded(self):
		other_invoice = self.office_invoice(self.other_customer)
		trip = self.run_trip([(self.plain_item, 2)], end_day=False)
		with as_user(self.agent_a.user):
			with self.assertRaisesRegex(frappe.ValidationError, "is not an invoice of"):
				api.price_cart(trip.name, self.customer, [{"item_code": self.plain_item, "qty": 1}],
					collect_previous=[{"sales_invoice": other_invoice.name, "allocated": 1}])  # fmt: skip
			self.assertEqual(api.search_customers("x" * 5000), [])
			self.assertEqual(api.search_items("x" * 5000), [])

			visit = api.submit_visit({"client_ref": "sec-ph", "mobile_trip": trip.name, "customer": self.customer,
				"outcome": "No Sale", "no_sale_reason": self.reason})  # fmt: skip
			with self.assertRaisesRegex(frappe.ValidationError, "larger than 5 MB"):
				api.upload_visit_photo("big.png", "A" * (api.PHOTO_MAX_BYTES * 2), visit=visit["name"])
			with self.assertRaisesRegex(frappe.ValidationError, "Only JPEG, PNG or WebP"):
				api.upload_visit_photo("bad.png", "@@not base64@@", visit=visit["name"])
			api.upload_visit_photo("a.png", PNG_1PX, visit=visit["name"])
			again = api.upload_visit_photo("b.png", base64.b64encode(base64.b64decode(PNG_1PX) + b"\0").decode(), visit=visit["name"])
		photos = frappe.get_all("File", filters={"attached_to_doctype": "Customer Visit", "attached_to_name": visit["name"]}, pluck="file_url")
		self.assertEqual(photos, [again["file_url"]])

	def test_return_picker_is_one_customers_invoices_with_typed_text(self):
		mine = self.office_invoice()
		self.office_invoice()
		self.office_invoice(self.other_customer)
		filters = {"customer": self.customer, "company": self.company, "item_code": self.plain_item}
		with as_user(self.agent_a.user):
			rows = api.return_invoice_query("Sales Invoice", "", "name", 0, 50, filters)
			self.assertEqual({r[0] for r in rows}, set(frappe.get_all("Sales Invoice", {"customer": self.customer, "docstatus": 1, "is_return": 0}, pluck="name")))
			self.assertEqual([r[0] for r in api.return_invoice_query("Sales Invoice", mine.name, "name", 0, 50, filters)], [mine.name])

	def test_throttle_is_per_user(self):
		calls = []

		def ping():
			calls.append(frappe.session.user)

		limited = api.throttle(3)(ping)
		previous = getattr(frappe.local, "request", None)
		frappe.local.request = object()  # only real requests are counted
		self.addCleanup(setattr, frappe.local, "request", previous)
		for user in (self.agent_a.user, self.agent_b.user):
			self.addCleanup(frappe.cache.delete, frappe.cache.make_key(f"mobilesales:throttle:ping:{user}"))
		with as_user(self.agent_a.user):
			for _i in range(3):
				limited()
			with self.assertRaises(frappe.RateLimitExceededError):
				limited()
		with as_user(self.agent_b.user):
			limited()
		self.assertEqual(len(calls), 4)

	# The sweep: agent B reaches nothing of agent A or of the office

	def test_agent_b_reaches_nothing_of_agent_a_or_the_office(self):
		office = self.office_invoice()
		trip = self.run_trip([(self.plain_item, 3)], end_day=False)
		visit = self.sell(trip.name, [(self.plain_item, 1)])
		documents = [
			("Mobile Trip", trip.name),
			("Customer Visit", visit.name),
			("Sales Invoice", visit.sales_invoice),
			("Payment Entry", visit.payment_entry),
			("Sales Invoice", office.name),
		]
		with as_user(self.agent_b.user):
			for doctype, name in documents:
				for ptype in ("read", "print", "write"):
					self.assertFalse(frappe.has_permission(doctype, ptype, doc=name), (doctype, name, ptype))
				self.assertNotIn(name, frappe.get_list(doctype, pluck="name", limit_page_length=0))
				self.assertNotIn(name, [r["value"] for r in search_link(doctype, name)])
				with self.assertRaises(frappe.PermissionError):
					get_html_and_style(doctype, name)
			for report in ("Customer Visit Register", "Customer Stock Position", "Outstanding by Agent"):
				rows = [r for r in run_report(report, {"company": self.company})["result"] if isinstance(r, dict)]
				self.assertFalse([r for r in rows if r.get("agent") == self.agent_a.name or r.get("visit") == visit.name], report)
			# query_report logs a refused run to Error Log (MyISAM, survives the rollback): remove what this writes
			since = frappe.utils.now_datetime()
			self.addCleanup(lambda: frappe.db.delete("Error Log", {"method": "Report execution failed for: Mobile Trip Day Report", "creation": [">=", since]}))
			with self.assertRaises(frappe.PermissionError):
				run_report("Mobile Trip Day Report", {"mobile_trip": trip.name})
			with self.assertRaises(frappe.PermissionError):
				run_report("Daily Trip Summary", {"company": self.company})  # not an agent report
			self.assertEqual(reports.chart_sales_by_agent()["labels"], [])
			with patch.dict(frappe.form_dict, {"visit": visit.name}), self.assertRaises(frappe.PermissionError):
				mobile_sales_print.get_context(frappe._dict())

	# The phone app still works under the tightened agent scope (Phase 7 live-run checklist)

	def test_phone_journey_under_agent_scope(self):
		country = frappe.get_cached_value("Company", self.company, "country")
		contact = frappe.get_doc({"doctype": "Contact", "first_name": f"{PREFIX} Owner", "is_primary_contact": 1,
			"phone_nos": [{"phone": "0771112223", "is_primary_mobile_no": 1}],
			"links": [{"link_doctype": "Customer", "link_name": self.customer}]}).insert().name  # fmt: skip
		address = frappe.get_doc({"doctype": "Address", "address_title": f"{PREFIX} Shop", "address_type": "Billing", "is_primary_address": 1,
			"address_line1": "1 Main St", "city": "Kandy", "country": country,
			"links": [{"link_doctype": "Customer", "link_name": self.customer}]}).insert().name  # fmt: skip
		frappe.db.set_value("Customer", self.customer, {"customer_primary_contact": contact, "customer_primary_address": address})
		frappe.get_doc({"doctype": "Address", "address_title": f"{PREFIX} Company", "address_type": "Billing", "is_your_company_address": 1,
			"address_line1": "HQ", "city": "Colombo", "country": country,
			"links": [{"link_doctype": "Company", "link_name": self.company}]}).insert()  # fmt: skip
		delivered = frappe.get_doc({"doctype": "Sales Invoice", "company": self.company, "customer": self.customer, "update_stock": 0,
			"items": [{"item_code": self.plain_item, "qty": 1, "rate": 90}]}).insert()  # fmt: skip
		delivered.submit()
		unpriced = self.make_item(f"{PREFIX} No Price Item")
		make_receipt(self.company, unpriced, 2, self.store)
		trip = self.run_trip([(self.plain_item, 4), (unpriced, 1)], end_day=False)

		with as_user(self.agent_a.user):
			card = api.get_customer(self.customer)  # customer details: contact and address shown
			self.assertEqual((card["contact"]["mobile_no"], card["address"]["city"]), ("0771112223", "Kandy"))
			created = api.create_customer({"customer_name": f"{PREFIX} New Shop", "mobile_no": "0779998887", "address_line1": "2 Hill Rd", "city": "Galle"})
			self.assertFalse(created["existing"])
			stock = {r.item_code: r for r in api.get_van_stock(trip.name)}
			self.assertEqual(set(stock), {self.plain_item, unpriced})
			priced = api.price_cart(trip.name, self.customer, [{"item_code": self.plain_item, "qty": 2}])
			self.assertEqual(priced["lines"][0]["price_list_rate"], 100)  # price shown
			with self.assertRaisesRegex(frappe.ValidationError, "has no price in price list"):
				api.price_cart(trip.name, self.customer, [{"item_code": unpriced, "qty": 1}])
			with self.assertRaisesRegex(frappe.ValidationError, "delivered with a Delivery Note"):
				api.price_cart(trip.name, self.customer, [], returns_items=[{"item_code": self.plain_item, "qty": 1,
					"against_invoice": delivered.name, "return_reason": "Damaged", "condition": "Damaged"}])  # fmt: skip
			sale = api.submit_visit({"client_ref": "sec-journey-1", "mobile_trip": trip.name, "customer": self.customer, "outcome": "Sale",
				"sale_items": [{"item_code": self.plain_item, "qty": 2}], "collect_amount": priced["due_on_sale"], "update_customer": 1,
				"new_mobile_no": "0771112224", "new_city": "Kandy 2"})  # fmt: skip — details edited on the visit
			back = api.submit_visit({"client_ref": "sec-journey-2", "mobile_trip": trip.name, "customer": self.customer, "outcome": "Return Only",
				"return_items": [{"item_code": self.plain_item, "qty": 1, "against_invoice": sale["sales_invoice"], "return_reason": "Damaged", "condition": "Damaged"}]})  # fmt: skip
			invoice = frappe.get_doc("Sales Invoice", sale["sales_invoice"])
			self.assertEqual((invoice.customer_address, invoice.contact_person), (address, contact))
			for doctype, name, print_format in (("Customer Visit", sale["name"], "Mobile Visit Bill"), ("Sales Invoice", sale["sales_invoice"], "Mobile Invoice 4in"),
					("Sales Invoice", back["credit_notes"], "Mobile Return Note"), ("Payment Entry", sale["payment_entry"], "Mobile Collection Receipt")):  # fmt: skip
				self.assertIn(name, frappe.get_print(doctype, name, print_format=print_format), print_format)
			history = api.get_visits(trip.name)  # History: both visits, reprintable
			self.assertEqual({v.name for v in history}, {sale["name"], back["name"]})
			self.assertTrue(frappe.has_permission("Sales Invoice", "print", doc=sale["sales_invoice"]))
			day = api.get_my_day(trip.name)
			self.assertEqual((day["visits"], day["invoices"]), (2, 1))
			self.assertTrue(run_report("Mobile Trip Day Report", {"mobile_trip": trip.name})["result"])
		changes = {c.field_key: c.new_value for c in frappe.get_doc("Customer Visit", sale["name"]).changes}
		self.assertEqual(changes, {"contact.mobile_no": "0771112224", "address.city": "Kandy 2"})
