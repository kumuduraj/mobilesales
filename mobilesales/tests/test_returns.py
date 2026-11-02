"""Phase 5b: line and invoice discounts with the agent cap, customer returns (credit notes into the customer
return warehouse), credit set-off against the returned invoice / today's sale / previous invoices, limits,
cancel chain, customer-return warehouse guards and the phone API. Flows run as the real agent, cancel as
the real supervisor (CLAUDE.md rule 13)."""

import frappe
from frappe.utils import flt, now_datetime, nowdate

from erpnext.stock.doctype.batch.batch import get_batch_qty

from mobilesales.api import mobile as api
from mobilesales.services import invoicing, returns
from mobilesales.services import trip as trip_service
from mobilesales.tests.utils import PREFIX, MobileSalesTestCase, as_user


class TestReturnsAndDiscounts(MobileSalesTestCase):
	def setUp(self):
		super().setUp()
		trip = frappe.get_doc(
			{
				"doctype": "Mobile Trip",
				"agent": self.agent_a.name,
				"trip_date": nowdate(),
				"load_items": [{"item_code": self.plain_item, "qty": 10}, {"item_code": self.batch_item, "qty": 7}],
			}
		)
		with as_user(self.users.store):
			trip.insert()
			trip.submit()
		with as_user(self.agent_a.user):
			trip_service.start_trip(trip.name)
		self.trip = frappe.get_doc("Mobile Trip", trip.name)
		self.set_setting("allow_credit_sales", 0)

	# helpers

	def set_setting(self, fieldname, value):
		old = self.settings.get(fieldname)
		self.settings.set(fieldname, value)
		self.addCleanup(self.settings.set, fieldname, old)

	def visit(self, outcome="Sale", items=None, return_items=None, collect="due", submit=True, user=None, **fields):
		"""Record a visit as the trip's agent (or `user`); collect='due' pays exactly the cash still due."""
		with as_user(user or self.agent_a.user):
			doc = frappe.get_doc(
				{
					"doctype": "Customer Visit",
					"mobile_trip": self.trip.name,
					"customer": self.customer,
					"company": self.company,
					"visit_datetime": now_datetime(),
					"outcome": outcome,
					"sale_items": items or [],
					"return_items": return_items or [],
					**fields,
				}
			)
			if outcome == "Sale":
				doc.collect_amount = self.due_on_sale(doc) if collect == "due" else collect
			doc.insert()
			if submit:
				doc.submit()
				doc.reload()
			return doc

	def due_on_sale(self, doc):
		payable = invoicing.payable_amount(invoicing.build_invoice(doc)) if doc.sale_items else 0
		_trip, agent = invoicing.get_visit_context(doc)
		notes = returns.validate_returns(doc, agent, self.settings)
		credit = returns.credit_by_target(returns.plan_set_off(doc, notes, payable))
		return flt(payable - credit.get(returns.SALE, 0), 2)

	def ret(self, item_code=None, qty=1, against=None, reason="Damaged", condition="Resaleable", **fields):
		return {"item_code": item_code or self.plain_item, "qty": qty, "against_invoice": against,
			"return_reason": reason, "condition": condition, **fields}  # fmt: skip

	def outstanding(self, name):
		return flt(frappe.db.get_value("Sales Invoice", name, "outstanding_amount"))

	def returns_qty(self, item_code):
		return flt(frappe.db.get_value("Bin", {"warehouse": self.customer_returns, "item_code": item_code}, "actual_qty"))

	def credit_note(self, visit, index=0):
		names = [n.strip() for n in visit.credit_notes.split(",")]
		return frappe.get_doc("Sales Invoice", names[index])

	# discounts

	def test_line_and_invoice_discounts_with_cap(self):
		frappe.db.set_value("Mobile Sales Agent", self.agent_a.name, "max_discount_pct", 10)
		items = [
			{"item_code": self.plain_item, "qty": 2, "discount_percentage": 5},
			{"item_code": self.batch_item, "qty": 1, "discount_amount": 20},
		]
		visit = self.visit(items=items, discount_amount=10)
		si = frappe.get_doc("Sales Invoice", visit.sales_invoice)
		plain, batch = visit.sale_items
		self.assertEqual((plain.rate, plain.discount_amount, plain.pricing_rule_rate), (95, 5, 100))
		self.assertEqual((batch.rate, batch.discount_percentage), (180, 10))
		self.assertEqual((si.apply_discount_on, si.discount_amount), ("Net Total", 10))
		self.assertEqual([i.rate for i in si.items], [95, 180])
		self.assertEqual((visit.grand_total, si.grand_total, si.owner), (360, 360, self.agent_a.user))

		# manual 2*5 + 20 + 11 = 41 of a price-list value of 400 = 10.25% > 10%
		with self.assertRaisesRegex(frappe.ValidationError, "above your limit of 10"):
			self.visit(items=items, discount_amount=11, submit=False)
		percent = self.visit(items=[{"item_code": self.plain_item, "qty": 1}], additional_discount_percentage=10)
		self.assertEqual(percent.grand_total, 90)

	def test_pricing_rule_discount_not_capped_and_manual_on_top(self):
		frappe.get_doc(
			{
				"doctype": "Pricing Rule",
				"title": f"{PREFIX} 10 pct",
				"apply_on": "Item Code",
				"items": [{"item_code": self.plain_item}],
				"selling": 1,
				"company": self.company,
				"rate_or_discount": "Discount Percentage",
				"discount_percentage": 10,
			}
		).insert()
		frappe.db.set_value("Mobile Sales Agent", self.agent_a.name, "max_discount_pct", 5)
		visit = self.visit(items=[{"item_code": self.plain_item, "qty": 2, "discount_percentage": 5}])
		si = frappe.get_doc("Sales Invoice", visit.sales_invoice)
		self.assertEqual((visit.sale_items[0].pricing_rule_rate, visit.sale_items[0].rate), (90, 85.5))
		self.assertEqual((si.items[0].rate, si.grand_total, visit.grand_total), (85.5, 171, 171))
		self.assertEqual(si.ignore_pricing_rule, 1)  # rates frozen as priced; the visit keeps the rule's rate
		# without a manual discount the invoice keeps the pricing rule itself
		plain = self.visit(items=[{"item_code": self.plain_item, "qty": 1}])
		self.assertTrue(frappe.get_doc("Sales Invoice", plain.sales_invoice).items[0].pricing_rules)

	# returns and credit set-off

	def test_return_only_sets_off_the_returned_invoice(self):
		self.set_setting("allow_credit_sales", 1)
		frappe.db.set_value("Mobile Sales Agent", self.agent_a.name, "credit_limit_per_invoice", 1000)
		old = self.visit(items=[{"item_code": self.plain_item, "qty": 3}], collect=0)
		self.assertEqual(self.outstanding(old.sales_invoice), 300)

		visit = self.visit("Return Only", return_items=[self.ret(against=old.sales_invoice, condition="Damaged")])
		note = self.credit_note(visit)
		self.assertEqual((note.is_return, note.return_against, note.set_warehouse, note.owner), (1, old.sales_invoice, self.customer_returns, self.agent_a.user))
		self.assertTrue(note.name.startswith("MB-SRET-"))
		self.assertEqual((note.mobile_trip, note.customer_visit, note.is_mobile_sale, note.grand_total), (self.trip.name, visit.name, 1, -100))
		self.assertEqual((visit.return_total, visit.credit_applied, visit.payment_entry), (100, 100, None))
		self.assertEqual((self.outstanding(old.sales_invoice), self.outstanding(note.name)), (200, 0))
		je = frappe.get_doc("Journal Entry", visit.credit_journal)
		self.assertEqual((je.voucher_type, je.mobile_trip, je.owner), ("Credit Note", self.trip.name, self.agent_a.user))
		self.assertEqual(
			{(r.reference_name, flt(r.debit), flt(r.credit)) for r in je.accounts},
			{(note.name, 100, 0), (old.sales_invoice, 0, 100)},
		)
		self.assertEqual(self.returns_qty(self.plain_item), 1)
		self.assertEqual(frappe.db.get_value("Mobile Trip", self.trip.name, "invoices"), 1)  # credit notes are not sales

	def test_return_nets_against_todays_sale(self):
		paid = self.visit(items=[{"item_code": self.plain_item, "qty": 2}])
		self.assertEqual(self.outstanding(paid.sales_invoice), 0)
		items = [{"item_code": self.plain_item, "qty": 3}]
		with self.assertRaisesRegex(frappe.ValidationError, "between 0 and the 200"):
			self.visit(items=items, return_items=[self.ret(against=paid.sales_invoice)], collect=300, submit=False)

		visit = self.visit(items=items, return_items=[self.ret(against=paid.sales_invoice)])
		note = self.credit_note(visit)
		self.assertEqual((visit.collect_amount, visit.credit_applied, visit.total_collected), (200, 100, 200))
		self.assertEqual(frappe.db.get_value("Payment Entry", visit.payment_entry, "paid_amount"), 200)
		self.assertEqual((self.outstanding(visit.sales_invoice), self.outstanding(note.name)), (0, 0))

		# supervisor cancels: payment, set-off, credit note, invoice; stock back in van and out of returns
		with as_user(self.users.supervisor):
			frappe.get_doc("Customer Visit", visit.name).cancel()
		for doctype, name in (("Payment Entry", visit.payment_entry), ("Journal Entry", visit.credit_journal),
			("Sales Invoice", note.name), ("Sales Invoice", visit.sales_invoice)):  # fmt: skip
			self.assertEqual(frappe.db.get_value(doctype, name, "docstatus"), 2, name)
		self.assertEqual(self.returns_qty(self.plain_item), 0)
		self.assertEqual(self.outstanding(paid.sales_invoice), 0)

	def test_leftover_credit_and_previous_invoices(self):
		paid = self.visit(items=[{"item_code": self.plain_item, "qty": 3}])
		# nothing to set off: the credit stays on the customer
		alone = self.visit("Return Only", return_items=[self.ret(qty=2, against=paid.sales_invoice)])
		self.assertEqual((alone.credit_applied, alone.credit_journal), (0, None))
		self.assertEqual(self.outstanding(self.credit_note(alone).name), -200)
		with as_user(self.agent_a.user):
			self.assertEqual(api.get_customer(self.customer)["credit_available"], 200)

		# a selected previous invoice: credit first, cash for the rest
		previous = self.standard_invoice(150)
		rows = [self.ret(against=paid.sales_invoice)]
		with self.assertRaisesRegex(frappe.ValidationError, "still due on .* after the return credit"):
			self.visit("Collection Only", return_items=rows, collect_previous=[{"sales_invoice": previous, "allocated": 60}], submit=False)
		visit = self.visit("Collection Only", return_items=rows, collect_previous=[{"sales_invoice": previous, "allocated": 50}])
		self.assertEqual((visit.credit_applied, visit.total_collected), (100, 50))
		self.assertEqual(self.outstanding(previous), 0)

	def test_batch_returns_follow_the_original_invoice(self):
		sale = self.visit(items=[{"item_code": self.batch_item, "qty": 6}])  # FIFO: A 5, B 1
		with self.assertRaisesRegex(frappe.ValidationError, "batch-tracked; choose the invoice"):
			self.visit("Return Only", return_items=[self.ret(self.batch_item)], submit=False)
		with self.assertRaisesRegex(frappe.ValidationError, "can still be returned"):
			self.visit("Return Only", return_items=[self.ret(self.batch_item, 7, sale.sales_invoice)], submit=False)

		first = self.visit("Return Only", return_items=[self.ret(self.batch_item, 2, sale.sales_invoice)])
		second = self.visit("Return Only", return_items=[self.ret(self.batch_item, 4, sale.sales_invoice)])
		batches = {b.get("batch_no"): b.get("qty") for b in get_batch_qty(warehouse=self.customer_returns, item_code=self.batch_item)}
		self.assertEqual(batches, {self.batch_a: 5, self.batch_b: 1})
		self.assertEqual(first.return_items[0].batch_info, f"{self.batch_a}: 2.0")
		self.assertEqual(self.credit_note(first).items[0].rate, 200)
		self.assertEqual(len(self.credit_note(second).items), 2)  # 3 from A, 1 from B
		with self.assertRaisesRegex(frappe.ValidationError, "was not sold on|can still be returned"):
			self.visit("Return Only", return_items=[self.ret(self.batch_item, 1, sale.sales_invoice)], submit=False)

	def test_return_rules_and_limits(self):
		paid = self.visit(items=[{"item_code": self.plain_item, "qty": 3}])
		rows = [self.ret(qty=2, against=paid.sales_invoice)]
		with self.assertRaisesRegex(frappe.ValidationError, "cannot take returns"):
			self.visit("Shop Closed", return_items=rows, submit=False)
		with self.assertRaisesRegex(frappe.ValidationError, "remarks are required"):
			self.visit("Return Only", return_items=[self.ret(against=paid.sales_invoice, reason="Other")], submit=False)
		with self.assertRaisesRegex(frappe.ValidationError, "Add at least one return line"):
			self.visit("Return Only", submit=False)

		frappe.db.set_value("Mobile Sales Agent", self.agent_a.name, "max_return_value_per_visit", 150)
		with self.assertRaisesRegex(frappe.ValidationError, "needs a supervisor"):
			self.visit("Return Only", return_items=rows, submit=False)
		frappe.db.set_value("Mobile Sales Agent", self.agent_a.name, "max_return_value_per_visit", 0)
		with self.assertRaisesRegex(frappe.ValidationError, "needs a supervisor"):
			self.visit("Return Only", return_items=[self.ret(against=paid.sales_invoice)], submit=False)
		by_supervisor = self.visit("Return Only", return_items=rows, user=self.users.supervisor)
		self.assertEqual((by_supervisor.docstatus, by_supervisor.return_total), (1, 200))

		self.set_setting("returns_enabled", 0)
		with self.assertRaisesRegex(frappe.ValidationError, "not enabled"):
			self.visit("Return Only", return_items=rows, user=self.users.supervisor, submit=False)

	# guards on the customer return warehouse

	def test_customer_return_warehouse_guards(self):
		self.visit("Return Only", return_items=[self.ret(qty=3)])  # 3 in the customer return warehouse
		office = self.users.office

		def stock_entry(entry_type, source, target):
			return frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": entry_type, "company": self.company,
				"items": [{"item_code": self.plain_item, "qty": 1, "s_warehouse": source, "t_warehouse": target, "basic_rate": 50}]})  # fmt: skip

		with as_user(office):
			with self.assertRaisesRegex(frappe.ValidationError, "receives stock only from Mobile Sales credit notes"):
				stock_entry("Material Transfer", self.store, self.customer_returns).insert()
			with self.assertRaisesRegex(frappe.ValidationError, "receives stock only from Mobile Sales credit notes"):
				stock_entry("Material Receipt", None, self.customer_returns).insert()
			outward = stock_entry("Material Transfer", self.customer_returns, self.store).insert()
			outward.submit()  # the store moves good returns back: allowed
			standard_return = frappe.get_doc({"doctype": "Sales Invoice", "company": self.company, "customer": self.customer,
				"is_return": 1, "update_stock": 1, "items": [{"item_code": self.plain_item, "qty": -1, "rate": 100, "warehouse": self.customer_returns}]})  # fmt: skip
			with self.assertRaisesRegex(frappe.ValidationError, "receives stock only from Mobile Sales credit notes"):
				standard_return.insert()
			reco = frappe.get_doc({"doctype": "Stock Reconciliation", "company": self.company, "purpose": "Stock Reconciliation",
				"items": [{"item_code": self.plain_item, "warehouse": self.customer_returns, "qty": 9, "valuation_rate": 50}]})  # fmt: skip
			with self.assertRaisesRegex(frappe.ValidationError, "receives stock only from Mobile Sales credit notes"):
				reco.insert()
			manual_note = frappe.get_doc({"doctype": "Sales Invoice", "company": self.company, "customer": self.customer,
				"is_return": 1, "update_stock": 1, "mobile_trip": self.trip.name, "set_warehouse": self.customer_returns,
				"items": [{"item_code": self.plain_item, "qty": -1, "rate": 100, "warehouse": self.customer_returns}]})  # fmt: skip
			with self.assertRaisesRegex(frappe.ValidationError, "can only be created by the Mobile Sales app"):
				manual_note.insert()
		self.assertEqual(self.returns_qty(self.plain_item), 2)

	# phone API

	def test_phone_api_discount_and_returns(self):
		frappe.db.set_value("Mobile Sales Agent", self.agent_a.name, "max_discount_pct", 10)
		paid = self.visit(items=[{"item_code": self.plain_item, "qty": 2}])
		returns_payload = [self.ret(against=paid.sales_invoice, condition="Damaged")]
		with as_user(self.agent_a.user):
			lines = api.get_returnable_lines(paid.sales_invoice, self.customer)
			self.assertEqual([(l["item_code"], l["returnable_qty"], l["rate"]) for l in lines], [(self.plain_item, 2, 100)])
			self.assertIn(paid.sales_invoice, [i.name for i in api.get_customer_invoices(self.customer)])
			priced = api.price_cart(
				self.trip.name, self.customer, [{"item_code": self.plain_item, "qty": 3, "discount_percentage": 10}],
				discount={"discount_amount": 0}, returns_items=returns_payload,
			)  # fmt: skip
			self.assertEqual((priced["rounded_total"], priced["return_total"], priced["credit_on_sale"], priced["due_on_sale"]), (270, 100, 100, 170))
			self.assertEqual(priced["manual_discount_pct"], 10)
			result = api.submit_visit({
				"client_ref": "ret-1", "mobile_trip": self.trip.name, "customer": self.customer, "outcome": "Sale",
				"sale_items": [{"item_code": self.plain_item, "qty": 3, "discount_percentage": 10}],
				"return_items": returns_payload, "collect_amount": 170,
			})  # fmt: skip
			history = {v.name: v for v in api.get_visits(self.trip.name)}
		self.assertEqual((result["return_total"], result["credit_applied"]), (100, 100))
		self.assertTrue(result["credit_notes"].startswith("MB-SRET-"))
		self.assertEqual(history[result["name"]].credit_notes, result["credit_notes"])
		self.assertEqual(self.outstanding(result["sales_invoice"]), 0)

	def standard_invoice(self, rate):
		si = frappe.get_doc(
			{
				"doctype": "Sales Invoice",
				"company": self.company,
				"customer": self.customer,
				"items": [{"item_code": self.plain_item, "qty": 1, "rate": rate, "warehouse": self.store}],
			}
		)
		with as_user(self.users.office):
			si.insert()
			si.submit()
		return si.name
