"""Phase 5b: line and invoice discounts with the agent cap, customer returns (credit notes into the customer
return warehouse), credit set-off against the returned invoice / today's sale / previous invoices, limits,
cancel chain, customer-return warehouse guards and the phone API. Flows run as the real agent, cancel as
the real supervisor (CLAUDE.md rule 13)."""

from unittest.mock import patch

import frappe
from frappe.utils import flt, now_datetime, nowdate

from erpnext.stock.doctype.batch.batch import get_batch_qty

from mobilesales.api import mobile as api
from mobilesales.services import invoicing, returns
from mobilesales.services import trip as trip_service
from mobilesales.tests.utils import PREFIX, MobileSalesTestCase, as_user, leaf


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

		# the 4-inch invoice shows list price, line discount and the invoice discount
		with as_user(self.agent_a.user):
			html = frappe.get_print("Sales Invoice", visit.sales_invoice, print_format="Mobile Invoice 4in")
		for text in ("List", "Disc. 5.00%", "Disc. 10.00%", "Subtotal", "Invoice discount", "-LKR 10.00" if "LKR" in html else "10.00"):
			self.assertIn(text, html)

		# a total with cents is rounded: the invoice shows the rounding adjustment
		odd = self.visit(items=[{"item_code": self.plain_item, "qty": 1, "discount_amount": 0.5}])
		si = frappe.get_doc("Sales Invoice", odd.sales_invoice)
		with as_user(self.agent_a.user):
			html = frappe.get_print("Sales Invoice", si.name, print_format="Mobile Invoice 4in")
		self.assertEqual("Rounding adjustment" in html, bool(si.rounding_adjustment) and si.rounded_total != si.grand_total)

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

	def test_free_item_rule_kept_with_manual_discount_elsewhere(self):
		frappe.get_doc(
			{
				"doctype": "Pricing Rule",
				"title": f"{PREFIX} buy 2 get 1",
				"apply_on": "Item Code",
				"items": [{"item_code": self.plain_item}],
				"selling": 1,
				"company": self.company,
				"price_or_product_discount": "Product",
				"min_qty": 2,
				"same_item": 1,
				"free_qty": 1,
			}
		).insert()
		frappe.db.set_value("Mobile Sales Agent", self.agent_a.name, "max_discount_pct", 10)
		visit = self.visit(items=[{"item_code": self.plain_item, "qty": 2}, {"item_code": self.batch_item, "qty": 1, "discount_percentage": 5}])
		si = frappe.get_doc("Sales Invoice", visit.sales_invoice)
		free = [(i.item_code, i.qty, i.rate) for i in si.items if i.is_free_item]
		self.assertEqual(free, [(self.plain_item, 1, 0)])
		self.assertEqual([i.rate for i in si.items if not i.is_free_item], [100, 190])
		self.assertEqual((si.grand_total, visit.grand_total, si.ignore_pricing_rule), (390, 390, 0))
		# a manual discount on the free-item line itself would need the rates frozen: blocked
		with self.assertRaisesRegex(frappe.ValidationError, "free-item offer"):
			self.visit(items=[{"item_code": self.plain_item, "qty": 2, "discount_percentage": 5}], submit=False)

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
		with as_user(self.agent_a.user):  # the agent reprints the credit note on the 4-inch format
			self.assertIn(note.name, frappe.get_print("Sales Invoice", note.name, print_format="Mobile Invoice 4in"))

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

	def test_credit_note_matches_erpnext_make_sales_return(self):
		"""Our field-by-field credit note equals ERPNext's own return mapper for the same lines."""
		from erpnext.accounts.doctype.sales_invoice.sales_invoice import make_sales_return

		sale = self.visit(items=[{"item_code": self.plain_item, "qty": 3}, {"item_code": self.batch_item, "qty": 6}])
		rows = [self.ret(self.plain_item, 2, sale.sales_invoice), self.ret(self.batch_item, 6, sale.sales_invoice)]
		reference = make_sales_return(sale.sales_invoice)  # Administrator, comparison only, before ours
		reference.update_stock = 1
		for item in reference.items:
			item.warehouse = self.customer_returns
			if item.item_code == self.plain_item:
				item.qty = -2
		reference.set_warehouse = self.customer_returns
		reference.calculate_taxes_and_totals()
		ref_items = {i.item_code: i for i in reference.items}
		visit = self.visit("Return Only", return_items=rows)
		ours = self.credit_note(visit)

		def batches(item):
			return returns._bundle_batches(item)

		self.assertEqual((ours.return_against, ours.customer, ours.is_return), (reference.return_against, reference.customer, 1))
		for code in (self.plain_item, self.batch_item):
			mine = [i for i in ours.items if i.item_code == code]
			ref = ref_items[code]
			self.assertEqual(sum(flt(i.qty) for i in mine), flt(ref.qty), code)
			self.assertEqual({i.rate for i in mine}, {ref.rate}, code)
			self.assertEqual({i.sales_invoice_item for i in mine}, {ref.sales_invoice_item}, code)
			self.assertEqual({i.uom for i in mine}, {ref.uom}, code)
		# batches: ours are the batches ERPNext would return (the original line's bundle)
		original = {i.item_code: i for i in frappe.get_doc("Sales Invoice", sale.sales_invoice).items}
		sold = {b: abs(q) for b, q in returns._bundle_batches(original[self.batch_item]).items()}
		credited = {}
		for item in ours.items:
			if item.item_code == self.batch_item:
				for b, q in batches(item).items():
					credited[b] = credited.get(b, 0) + abs(q)
		self.assertEqual(credited, sold)
		self.assertEqual([(t.account_head, t.rate) for t in ours.taxes], [(t.account_head, t.rate) for t in reference.taxes])
		self.assertEqual((ours.net_total, ours.grand_total), (reference.net_total, reference.grand_total))

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
			supplier = frappe.get_doc({"doctype": "Supplier", "supplier_name": f"{PREFIX} Supplier", "supplier_group": leaf("Supplier Group")})
			supplier.flags.ignore_permissions = True
			supplier.insert()

			def receipt(warehouse):
				return frappe.get_doc({"doctype": "Purchase Receipt", "company": self.company, "supplier": supplier.name,
					"items": [{"item_code": self.plain_item, "qty": 1, "rate": 50, "warehouse": warehouse}]})  # fmt: skip

			standard = receipt(self.store).insert()  # untouched: standard purchase into a normal store
			standard.submit()
			with self.assertRaisesRegex(frappe.ValidationError, "receives stock only from Mobile Sales credit notes"):
				receipt(self.customer_returns).insert()
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

	def test_live_run_steps_sale_and_full_return_set_off(self):
		"""MTRIP-26-00005 steps as the real agent through the phone API: 6% refused, a return above the
		invoiced qty refused, then 1 sold + 1 returned against an earlier paid invoice = no cash at all."""
		frappe.db.set_value("Mobile Sales Agent", self.agent_a.name, {"max_discount_pct": 5, "max_return_value_per_visit": 2000})
		earlier = self.visit(items=[{"item_code": self.batch_item, "qty": 1}])  # like MB-SINV-26-00002: paid
		self.assertEqual(self.outstanding(earlier.sales_invoice), 0)
		sale = [{"item_code": self.batch_item, "qty": 1}]
		ret = [self.ret(self.batch_item, 1, earlier.sales_invoice, condition="Damaged")]
		with as_user(self.agent_a.user):
			with self.assertRaisesRegex(frappe.ValidationError, "above your limit of 5"):
				api.price_cart(self.trip.name, self.customer, [{"item_code": self.batch_item, "qty": 2, "discount_percentage": 6}])
			with self.assertRaisesRegex(frappe.ValidationError, "only 1.0 .* can still be returned"):
				api.price_cart(self.trip.name, self.customer, sale, returns_items=[{**ret[0], "qty": 2}])
			priced = api.price_cart(self.trip.name, self.customer, sale, returns_items=ret)
			self.assertEqual((priced["rounded_total"], priced["return_total"], priced["due_on_sale"]), (200, 200, 0))
			result = api.submit_visit({"client_ref": "live-2", "mobile_trip": self.trip.name, "customer": self.customer,
				"outcome": "Sale", "sale_items": sale, "return_items": ret, "collect_amount": 0})  # fmt: skip
		visit = frappe.get_doc("Customer Visit", result["name"])
		note = self.credit_note(visit)
		self.assertEqual(len(visit.return_items), 1)
		self.assertEqual((visit.payment_entry, visit.total_collected, visit.credit_applied), (None, 0, 200))
		self.assertEqual((self.outstanding(visit.sales_invoice), self.outstanding(note.name)), (0, 0))
		self.assertEqual((note.owner, note.return_against), (self.agent_a.user, earlier.sales_invoice))
		self.assertEqual(frappe.db.get_value("Journal Entry", visit.credit_journal, "owner"), self.agent_a.user)
		self.assertEqual({b.get("batch_no"): b.get("qty") for b in get_batch_qty(warehouse=self.customer_returns, item_code=self.batch_item)}, {self.batch_a: 1})

	def test_live_run_visit_2_percent_discount_print_and_rejection_log(self):
		"""MTRIP-26-00005 visit 2 as the real agent: a refused submit is logged for the supervisor, an
		entered 5% invoice discount stays 5% on the invoice, and the prints split credit from cash."""
		frappe.db.set_value("Mobile Sales Agent", self.agent_a.name, {"max_discount_pct": 5, "max_return_value_per_visit": 2000})
		earlier = self.visit(items=[{"item_code": self.batch_item, "qty": 1}])
		sale = [{"item_code": self.batch_item, "qty": 2}]
		ret = [self.ret(self.batch_item, 1, earlier.sales_invoice, reason="Damaged", condition="Damaged")]
		payload = {"client_ref": "live-3", "mobile_trip": self.trip.name, "customer": self.customer, "outcome": "Sale",
			"sale_items": sale, "additional_discount_percentage": 5, "return_items": ret}  # fmt: skip

		# 2 x 200 - 5% = 380, return credit 200: collecting the invoice total (380) instead of 180 is refused
		with as_user(self.agent_a.user):
			with self.assertRaisesRegex(frappe.ValidationError, "Collect Now must be between 0 and the 180"):
				api.submit_visit({**payload, "collect_amount": 380})
			log = frappe.db.after_rollback._functions.pop()  # what the request's rollback would run
			with patch.object(frappe.db, "commit") as commit:
				log()
			commit.assert_called_once()
		rejection = frappe.get_last_doc("Mobile Visit Rejection", filters={"client_ref": "live-3"})
		self.assertEqual(
			(rejection.user, rejection.agent, rejection.mobile_trip, rejection.customer, rejection.outcome),
			(self.agent_a.user, self.agent_a.name, self.trip.name, self.customer, "Sale"),
		)
		self.assertIn("Collect Now must be between 0 and the 180", rejection.message)
		self.assertNotIn("<", rejection.message)
		self.assertTrue(frappe.has_permission("Mobile Visit Rejection", "read", rejection, user=self.users.supervisor))
		self.assertFalse(frappe.has_permission("Mobile Visit Rejection", "read", rejection, user=self.agent_a.user))

		with as_user(self.agent_a.user):
			result = api.submit_visit({**payload, "collect_amount": 180})
		visit = frappe.get_doc("Customer Visit", result["name"])
		si = frappe.get_doc("Sales Invoice", visit.sales_invoice)
		note = self.credit_note(visit)
		self.assertEqual((si.additional_discount_percentage, si.discount_amount, si.grand_total), (5, 20, 380))
		self.assertEqual((visit.additional_discount_percentage, visit.discount_amount), (5, 20))
		self.assertEqual((visit.total_collected, visit.credit_applied, self.outstanding(si.name)), (180, 200, 0))

		def amounts(html):
			return " ".join(frappe.utils.strip_html(html).split())

		with as_user(self.agent_a.user):
			invoice_html = amounts(frappe.get_print("Sales Invoice", si.name, print_format="Mobile Invoice 4in"))
			note_html = amounts(frappe.get_print("Sales Invoice", note.name, print_format="Mobile Invoice 4in"))
		self.assertRegex(invoice_html, r"Invoice discount \(5%\)\s*-\D*20\.00")
		self.assertNotRegex(invoice_html, r"Invoice discount \(5%\)\s*-[^\d]*-")  # one minus sign, not "-Rs -20.00"
		self.assertRegex(invoice_html, r"Return credit applied\s*-\D*200\.00")
		self.assertRegex(invoice_html, r"Paid \(cash\)\s*\D*180\.00")
		self.assertNotRegex(invoice_html, r"Paid \(cash\) \D*380")
		self.assertRegex(note_html, rf"Credit applied to {si.name}\s*\D*200\.00")
		self.assertRegex(note_html, r"Credit left on account\s*\D*0\.00")
		self.assertNotIn("Paid (cash)", note_html)

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
