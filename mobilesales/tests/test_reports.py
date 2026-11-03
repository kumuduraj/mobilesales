"""Phase 6: reports, Mobile Trip Day Report, daily email, "My day". One seeded trip with line + invoice discounts,
a top-up, a credit sale, returns against today's invoice and against an older desk invoice, a no-sale visit off
route, a missed route customer, a stock shortage and a cash shortage; every report total is compared with the
ledgers (GL, Payment Ledger, Stock Ledger). Flows run as the real role users (rule 13)."""

from unittest.mock import patch

import frappe
from frappe.desk.query_report import run as run_report
from frappe.utils import add_days, flt, getdate, now_datetime, nowdate

from mobilesales.api import mobile as mobile_api
from mobilesales.services import day_report, invoicing, reports
from mobilesales.services import trip as trip_service
from mobilesales.tests.test_settlement import CASHIER, STORE_KEEPER, SUPERVISOR, SettlementTestBase
from mobilesales.tests.utils import PREFIX, as_user, leaf

def blank_pdf() -> bytes:
	"""A real one-page PDF: File.validate parses PDFs, so the mocked renderer must return a valid one."""
	from io import BytesIO

	from pypdf import PdfWriter

	writer, out = PdfWriter(), BytesIO()
	writer.add_blank_page(width=200, height=200)
	writer.write(out)
	return out.getvalue()


WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


class TestReports(SettlementTestBase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.others = [
			frappe.get_doc({"doctype": "Customer", "customer_name": f"{PREFIX} Customer {n}", "customer_group": leaf("Customer Group"),
				"territory": leaf("Territory")}).insert().name  # fmt: skip
			for n in (2, 3, 4)
		]
		other_day = WEEKDAYS[(getdate(nowdate()).weekday() + 1) % 7]
		cls.route = frappe.get_doc(
			{
				"doctype": "Mobile Route",
				"route_name": f"{PREFIX} Report Route",
				"customers": [
					{"customer": cls.customer, "sequence": 1, "visit_frequency": "Daily"},
					{"customer": cls.others[0], "sequence": 2, "visit_frequency": "Daily"},
					{"customer": cls.others[1], "sequence": 3, "visit_frequency": "Weekly", "visit_day": other_day},
				],
			}
		).insert().name
		cls.reason = frappe.get_all("Visit No Sale Reason", filters={"requires_remark": 0}, pluck="name", limit=1)[0]

	# seed

	def visit(self, customer, outcome="Sale", items=(), returns=(), collect=None, **fields):
		with as_user(self.agent_a.user):
			doc = frappe.get_doc(
				{
					"doctype": "Customer Visit",
					"mobile_trip": self.trip.name,
					"customer": customer,
					"company": self.company,
					"visit_datetime": now_datetime(),
					"outcome": outcome,
					"sale_items": list(items),
					"return_items": list(returns),
					**fields,
				}
			)
			if outcome == "Sale":
				doc.collect_amount = self.due(doc) if collect is None else collect(self.due(doc))
			doc.insert()
			doc.submit()
			return frappe.get_doc("Customer Visit", doc.name)

	def due(self, doc):
		from mobilesales.services import returns

		payable = invoicing.payable_amount(invoicing.build_invoice(doc))
		_trip, agent = invoicing.get_visit_context(doc)
		notes = returns.validate_returns(doc, agent, self.settings)
		credit = returns.credit_by_target(returns.plan_set_off(doc, notes, payable))
		return flt(payable - credit.get(returns.SALE, 0), 2)

	def seed(self):
		"""The reference day of agent A; returns the approved settlement."""
		self.set_setting("allow_credit_sales", 1)
		frappe.db.set_value("Mobile Sales Agent", self.agent_a.name, {"credit_limit_per_invoice": 1000, "max_discount_pct": 10})
		older = frappe.get_doc(
			{"doctype": "Sales Invoice", "company": self.company, "customer": self.customer, "update_stock": 1,
				"items": [{"item_code": self.plain_item, "qty": 1, "rate": 100, "warehouse": self.store}]}  # fmt: skip
		)
		with as_user(self.users.office):
			older.insert()
			older.submit()
		self.older = older.name

		trip = frappe.get_doc(
			{"doctype": "Mobile Trip", "agent": self.agent_a.name, "trip_date": nowdate(), "route": self.route,
				"load_items": [{"item_code": self.plain_item, "qty": 10}, {"item_code": self.cash_item, "qty": 5}]}  # fmt: skip
		)
		with as_user(self.users.store):
			trip.insert()
			trip.submit()
		with as_user(self.agent_a.user):
			trip_service.start_trip(trip.name)
		with as_user(self.users.store):
			trip_service.top_up(trip.name, [{"item_code": self.plain_item, "qty": 2}])
		self.trip = frappe.get_doc("Mobile Trip", trip.name)

		# 1. 3 x 100 - 5% per line, invoice discount 10 = 275; 225 cash, 50 on credit
		self.v1 = self.visit(self.customer, items=[{"item_code": self.plain_item, "qty": 3, "discount_percentage": 5}],
			discount_amount=10, collect=lambda due: due - 50)  # fmt: skip
		# 2. 1 x 485 and 1 returned (damaged) against visit 1's invoice: the credit pays visit 1's 50 first,
		#    the rest goes off today's invoice; 30 left on credit
		self.v2 = self.visit(self.customer, items=[{"item_code": self.cash_item, "qty": 1}],
			returns=[{"item_code": self.plain_item, "qty": 1, "against_invoice": self.v1.sales_invoice, "return_reason": "Damaged",
				"condition": "Damaged"}], collect=lambda due: due - 30)  # fmt: skip
		# 3. Return Only against the older desk invoice (100 open): its credit clears it
		self.v3 = self.visit(self.customer, outcome="Return Only",
			returns=[{"item_code": self.plain_item, "qty": 1, "against_invoice": self.older, "return_reason": "Unsold / Slow-moving",
				"condition": "Resaleable"}])  # fmt: skip
		# 4. No Sale at a customer off the route; route customer 2 is missed
		self.v4 = self.visit(self.others[2], outcome="No Sale", no_sale_reason=self.reason)
		with as_user(self.agent_a.user):
			trip_service.end_day(self.trip.name)

		# van: plain 12 issued - 3 sold = 9 expected, 8 back = 1 missing; cash item 4 back; cash 20 short
		draft = self.draft(self.trip, returned={self.plain_item: 8, self.cash_item: 4})
		draft.reload()
		frappe.set_user(self.agent_a.user)
		draft.cash_handed_over = flt(draft.expected_cash - 20, 2)
		draft.save()
		frappe.set_user("Administrator")
		with patch("frappe.enqueue") as enqueue:
			done = self.approve_flow(draft.name)
		self.assertEqual(done.docstatus, 1)
		self.queued = [c for c in enqueue.call_args_list if c.args and c.args[0] == "mobilesales.services.day_report.attach_day_report"]
		self.trip = frappe.get_doc("Mobile Trip", self.trip.name)
		return done

	# ledger helpers

	def gl(self, account, vouchers, side):
		if not vouchers:
			return 0
		return flt(
			frappe.db.sql(
				f"select sum({side}) from `tabGL Entry` where account = %s and voucher_no in %s and is_cancelled = 0",
				(account, tuple(vouchers)),
			)[0][0],
			2,
		)

	def vouchers(self, doctype, **filters):
		return frappe.get_all(doctype, filters={"mobile_trip": self.trip.name, "docstatus": 1, **filters}, pluck="name")

	def sle_value(self, warehouse, vouchers):
		if not vouchers:
			return 0
		return flt(
			frappe.db.sql(
				"select sum(stock_value_difference) from `tabStock Ledger Entry` where warehouse = %s and voucher_no in %s and is_cancelled = 0",
				(warehouse, tuple(vouchers)),
			)[0][0],
			2,
		)

	def run_as(self, user, report, **filters):
		with as_user(user):
			result = run_report(report, filters={"company": self.company, "from_date": nowdate(), "to_date": nowdate(), **filters})
		return [r for r in result["result"] if isinstance(r, dict)]  # the total row is a plain list

	# tests

	def test_trip_figures_equal_the_ledgers(self):
		done = self.seed()
		trip = reports.trip_rows({"mobile_trip": self.trip.name})[0]
		s = reports.trip_summary(trip)
		receivable = frappe.get_cached_value("Company", self.company, "default_receivable_account")
		sales = self.vouchers("Sales Invoice", is_return=0)
		notes = self.vouchers("Sales Invoice", is_return=1)
		payments = self.vouchers("Payment Entry")
		journals = self.vouchers("Journal Entry", voucher_type="Credit Note")
		issues = self.vouchers("Stock Entry", mobile_purpose=["in", ["Issue", "Top-up"]])

		self.assertEqual((s.visits, s.sales_visits, s.no_sale_visits, s.return_visits, s.invoices), (4, 2, 1, 1, 2))
		self.assertEqual((s.planned_visits, s.planned_visited, s.missed, s.off_route), (2, 1, 1, 1))
		self.assertAlmostEqual(s.sales_total, self.gl(receivable, sales, "debit"), 2)
		self.assertAlmostEqual(s.return_value, self.gl(receivable, notes, "credit"), 2)
		self.assertAlmostEqual(s.credit_applied, self.gl(receivable, journals, "debit"), 2)
		self.assertAlmostEqual(s.cash_collected, self.gl(self.agent_a.cash_account, payments, "debit"), 2)
		self.assertAlmostEqual(s.issued_value, self.sle_value(self.agent_a.van_warehouse, issues), 2)
		self.assertAlmostEqual(s.sold_value, -self.sle_value(self.agent_a.van_warehouse, sales), 2)
		self.assertAlmostEqual(s.missing_value, -self.sle_value(self.agent_a.van_warehouse, [done.shortage_entry]), 2)
		self.assertAlmostEqual(s.cash_variance, -20, 2)
		self.assertAlmostEqual(-s.cash_variance, self.gl(self.cash_shortage, [done.variance_journal], "debit"), 2)
		# credit given at the sale (50 + 30), never the return credit; settlement agrees (v0.7.0 fix)
		self.assertAlmostEqual(s.credit_given, 80, 2)
		self.assertAlmostEqual(done.credit_sales_amount, 80, 2)
		self.assertEqual((s.line_discount, s.invoice_discount, s.pricing_rule_discount), (15, 10, 0))
		self.assertEqual((s.issued_qty, s.sold_qty, s.returned_qty, s.missing_qty), (17, 4, 12, 1))
		self.assertEqual((s.customer_returns_received, s.customer_returns_damaged), (2, 1))
		self.assertEqual((s.settlement, s.settlement_status, s.settled), (done.name, "Approved", True))

		# Daily Trip Summary / Salesperson Performance are the same figures
		(row,) = self.run_as(SUPERVISOR, "Daily Trip Summary")
		self.assertEqual((row["trip"], row["sales_total"], row["cash_collected"]), (self.trip.name, s.sales_total, s.cash_collected))
		(perf,) = self.run_as(SUPERVISOR, "Salesperson Performance")
		self.assertEqual((perf["trips"], perf["working_days"], perf["visits"], perf["invoices"]), (1, 1, 4, 2))
		self.assertAlmostEqual(perf["sales_total"], s.sales_total, 2)
		self.assertAlmostEqual(perf["collections"], s.cash_collected, 2)
		self.assertEqual((perf["strike_rate"], perf["route_coverage"]), (50, 50))
		self.assertAlmostEqual(perf["cash_variance"], -20, 2)
		self.assertAlmostEqual(perf["missing_value"], s.missing_value, 2)

		# Customer Visit Register: amounts add up to the ledgers
		visits = self.run_as(SUPERVISOR, "Customer Visit Register")
		self.assertEqual(len(visits), 4)
		self.assertAlmostEqual(sum(flt(r["amount"]) for r in visits), s.sales_total, 2)
		self.assertAlmostEqual(sum(flt(r["collected"]) for r in visits), s.cash_collected, 2)
		self.assertAlmostEqual(sum(flt(r["return_total"]) for r in visits), s.return_value, 2)
		self.assertAlmostEqual(sum(flt(r["discount"]) for r in visits), 25, 2)
		self.assertEqual([r["off_route"] for r in visits], [0, 0, 0, 1])

		# Outstanding by Agent = the Payment Ledger
		(owed,) = self.run_as(SUPERVISOR, "Outstanding by Agent")
		ple = flt(frappe.db.sql(
			"select sum(amount) from `tabPayment Ledger Entry` where against_voucher_no in %s and delinked = 0", (tuple(sales),))[0][0], 2)  # fmt: skip
		self.assertEqual((owed["customer"], owed["invoices"]), (self.customer, 1))
		self.assertAlmostEqual(owed["outstanding"], ple, 2)
		self.assertAlmostEqual(owed["outstanding"], 30, 2)
		self.assertAlmostEqual(owed["range_0_30"], 30, 2)

		# Discount Report: line + invoice discounts against the cap, pricing rules apart
		discount = {r["sales_invoice"]: r for r in self.run_as(SUPERVISOR, "Discount Report")}
		d1 = discount[self.v1.sales_invoice]
		self.assertEqual((d1["price_list_value"], d1["line_discount"], d1["invoice_discount"], d1["manual_discount"]), (300, 15, 10, 25))
		self.assertEqual((d1["manual_pct"], d1["cap_pct"], d1["within_cap"]), (8.33, 10, "Yes"))
		si = frappe.get_doc("Sales Invoice", self.v1.sales_invoice)
		self.assertAlmostEqual(d1["line_discount"] + d1["invoice_discount"], sum((i.price_list_rate - i.rate) * i.qty for i in si.items) + si.discount_amount, 2)

		# Mobile Stock / Cash Variance = the settlement and its postings
		stock = {r["item_code"]: r for r in self.run_as(SUPERVISOR, "Mobile Stock Variance")}
		self.assertEqual((stock[self.plain_item]["issued"], stock[self.plain_item]["sold"], stock[self.plain_item]["returned"], stock[self.plain_item]["missing"]), (12, 3, 8, 1))
		self.assertAlmostEqual(sum(flt(r["missing_value"]) for r in stock.values()), s.missing_value, 2)
		(cash,) = self.run_as(CASHIER, "Mobile Cash Variance")
		self.assertEqual((cash["settlement"], cash["variance"], cash["action"], cash["journal"]), (done.name, -20, "Write Off", done.variance_journal))

		# Customer Returns Register: the quantity column adds up to the customer return warehouse's Stock Ledger
		register = self.run_as(STORE_KEEPER, "Customer Returns Register")
		returns = [r for r in register if r["row_type"] == "Return"]
		self.assertEqual(len(returns), 2)
		self.assertEqual({(r["reason"], r["condition"], r["against_invoice"]) for r in returns},
			{("Damaged", "Damaged", self.v1.sales_invoice), ("Unsold / Slow-moving", "Resaleable", self.older)})  # fmt: skip
		ledger_qty = flt(frappe.db.sql(
			"select sum(actual_qty) from `tabStock Ledger Entry` where warehouse = %s and is_cancelled = 0", self.customer_returns)[0][0])  # fmt: skip
		self.assertAlmostEqual(sum(flt(r["qty"]) for r in register), ledger_qty, 3)
		self.assertEqual(ledger_qty, 1)  # the damaged one moved to the damage warehouse
		self.assertIn(done.return_damage_entry, [r["voucher"] for r in register if r["row_type"] == "Moved out"])
		self.assertAlmostEqual(sum(flt(r["credit_applied_amount"]) for r in returns), s.credit_applied, 2)
		counted = [r for r in returns if r.get("received") is not None]
		self.assertEqual([(r["received"], r["damaged"], r["missing"]) for r in counted], [(2, 1, 0)])
		older_row = next(r for r in returns if r["against_invoice"] == self.older)
		self.assertEqual(older_row["credit_applied"], f"{self.older}: 100.0")

		# Route Coverage / No Sale Reason Analysis / Customer Stock Position
		coverage = {r["customer"]: r["status"] for r in self.run_as(SUPERVISOR, "Route Coverage")}
		self.assertEqual(coverage, {self.customer: "Visited", self.others[0]: "Missed", self.others[2]: "Off route"})
		(no_sale,) = self.run_as(SUPERVISOR, "No Sale Reason Analysis")
		self.assertEqual((no_sale["reason"], no_sale["count"], no_sale["visits"], no_sale["pct"]), (self.reason, 1, 4, 25))

	def test_day_report_pdf_email_and_my_day(self):
		done = self.seed()
		# queued on submit, after the commit
		self.assertEqual(len(self.queued), 1)
		self.assertEqual((self.queued[0].kwargs["settlement"], self.queued[0].kwargs["enqueue_after_commit"]), (done.name, True))

		with as_user(self.agent_a.user):
			report = reports.day_report(self.trip.name)
			rows = [r for r in run_report("Mobile Trip Day Report", filters={"mobile_trip": self.trip.name})["result"] if isinstance(r, dict)]
		s = report.summary
		self.assertEqual(len(report.visit_log), 4)
		self.assertEqual([m.customer for m in report.missed], [self.others[0]])
		self.assertEqual(len(report.invoices), 2)
		self.assertAlmostEqual(sum(i.total for i in report.invoices), s.sales_total, 2)
		self.assertAlmostEqual(sum(c.amount for c in report.collections), s.cash_collected, 2)
		self.assertEqual({st.item: (st.issued, st.topped_up, st.sold, st.returned, st.missing) for st in report.stock},
			{self.plain_item: (10, 2, 3, 8, 1), self.cash_item: (5, 0, 1, 4, 0)})  # fmt: skip
		self.assertAlmostEqual(report.cash.variance, -20, 2)
		self.assertEqual([x.state for x in report.signoff], ["Pending Store", "Pending Cashier", "Approved"])
		self.assertEqual([x.user for x in report.signoff], [self.agent_a.user, STORE_KEEPER, CASHIER])
		sections = [r["section"] for r in rows if r.get("is_section")]
		self.assertEqual(len(sections), 13)
		self.assertTrue(sections[0].startswith("1.") and sections[-1].startswith("12."))

		# the A4 print renders every section; the PDF is attached once
		with as_user(SUPERVISOR):
			html = frappe.get_print("Mobile Settlement", done.name, print_format="Mobile Trip Day Report")
		for text in ("Mobile Trip Day Report", "Visit log", "Missed customers", "Sales by invoice", "Customer returns",
			"Stock reconciliation", "Cash reconciliation", "Sign-off", self.v1.sales_invoice, self.others[0]):  # fmt: skip
			self.assertIn(text, html)
		with patch("frappe.utils.pdf.get_pdf", return_value=blank_pdf()) as pdf:
			first = day_report.attach_day_report(done.name)
			again = day_report.attach_day_report(done.name)
		self.assertEqual(first, again)
		self.assertEqual(pdf.call_count, 1)
		file = frappe.get_doc("File", first)
		self.assertEqual((file.attached_to_doctype, file.attached_to_name, file.is_private, file.file_name),
			("Mobile Settlement", done.name, 1, f"{self.trip.name} Day Report.pdf"))  # fmt: skip

		# 20:00 email: off by default, skipped without trips, built (not sent) for the day's settlements
		with patch("frappe.sendmail") as sendmail, patch("frappe.utils.pdf.get_pdf", return_value=blank_pdf()):
			self.assertIsNone(day_report.send_daily_reports())
			self.set_setting("daily_report_email", 1)
			# switched on, but no outgoing email account yet (agrosys today): skipped, nothing queued
			with patch.object(day_report, "outgoing_email_ready", return_value=False):
				self.assertIsNone(day_report.send_daily_reports())
			sendmail.assert_not_called()
			with patch.object(day_report, "outgoing_email_ready", return_value=True):
				self.assertIsNone(day_report.send_daily_reports(add_days(nowdate(), 1)))
				self.assertEqual(day_report.send_daily_reports(), [done.name])
		sendmail.assert_called_once()
		mail = sendmail.call_args.kwargs
		self.assertIn(frappe.db.get_value("User", SUPERVISOR, "email"), mail["recipients"])
		self.assertEqual([a["fname"] for a in mail["attachments"]], [f"{self.trip.name} Day Report.pdf"])
		self.assertIn(self.trip.name, mail["message"])

		# "My day" on the phone: the same figures, own trip only
		with as_user(self.agent_a.user):
			mine = mobile_api.get_my_day(self.trip.name)
		self.assertEqual((mine["visits"], mine["planned_visits"], mine["invoices"]), (4, 2, 2))
		self.assertAlmostEqual(mine["sales_total"], s.sales_total, 2)
		self.assertAlmostEqual(mine["cash_collected"], s.cash_collected, 2)
		self.assertAlmostEqual(mine["return_value"], s.return_value, 2)
		with as_user(self.agent_b.user), self.assertRaises(frappe.PermissionError):
			mobile_api.get_my_day(self.trip.name)

	def test_agents_see_only_their_own_data_and_report_roles(self):
		self.seed()
		# agent B: nothing of agent A, even when asking for A by name
		with as_user(self.agent_b.user):
			self.assertEqual(reports.trip_rows({}), [])
			self.assertEqual(reports.trip_rows({"agent": self.agent_a.name}), [])
			self.assertEqual([r for r in run_report("Customer Visit Register", filters={"agent": self.agent_a.name})["result"] if isinstance(r, dict)], [])
			with self.assertRaises(frappe.PermissionError):
				reports.day_report(self.trip.name)
		# agent A: own data in the 4 agent reports, refused elsewhere
		self.assertEqual(len(self.run_as(self.agent_a.user, "Customer Visit Register")), 4)
		self.assertEqual(len(self.run_as(self.agent_a.user, "Outstanding by Agent")), 1)
		self.assertEqual(self.run_as(self.agent_a.user, "Customer Stock Position"), [])
		for report in ("Daily Trip Summary", "Salesperson Performance", "Customer Returns Register", "Discount Report",
			"Mobile Cash Variance", "Mobile Stock Variance", "Route Coverage", "No Sale Reason Analysis"):  # fmt: skip
			with self.subTest(report=report), self.assertRaises(frappe.PermissionError):
				self.run_as(self.agent_a.user, report)
		# Accounts Manager (office) and the store keeper see every report
		self.assertEqual(len(self.run_as(self.users.office, "Daily Trip Summary")), 1)
		self.assertEqual(len(self.run_as(self.users.office, "Mobile Cash Variance")), 1)
		self.assertEqual(len(self.run_as(STORE_KEEPER, "Customer Visit Register")), 4)
		# anyone without a Mobile Sales or staff role gets nothing, even through the shared logic
		self.assertEqual(reports.restricted_agent("Guest"), reports.NOBODY)
		with as_user("Guest"):
			self.assertEqual(reports.trip_rows({}), [])

	def test_workspace_cards_and_charts(self):
		self.seed()
		for name in ("Mobile Sales by Agent", "Mobile Strike Rate", "Mobile No Sale Reasons", "Mobile Returns by Reason"):
			module = frappe.scrub(name)
			source = frappe.get_attr(f"mobilesales.mobile_sales.dashboard_chart_source.{module}.{module}.get")
			with as_user(SUPERVISOR):
				data = source()
			self.assertTrue(data["labels"], name)
		with as_user(SUPERVISOR):
			self.assertEqual(reports.chart_sales_by_agent()["datasets"][0]["values"],
				[reports.trip_summary(reports.trip_rows({"mobile_trip": self.trip.name})[0]).sales_total])  # fmt: skip
			self.assertEqual(reports.chart_strike_rate()["datasets"][0]["values"], [50])
		from frappe.desk.doctype.number_card.number_card import get_result

		expected = {
			"Open Trips": 0,
			"Today's Visits": 4,
			"Today's Returns": flt(self.v2.return_total + self.v3.return_total, 2),
			"Today's Cash Variance": -20,
		}
		for card, value in expected.items():
			with as_user(SUPERVISOR):
				doc = frappe.get_doc("Number Card", card)
				self.assertAlmostEqual(flt(get_result(doc, doc.filters_json)), value, 2, card)
		workspace = frappe.get_doc("Workspace", "Mobile Sales")
		self.assertEqual({r.role for r in workspace.roles}, {"Mobile Sales Supervisor", "Mobile Sales Store Keeper",
			"Mobile Sales Cashier", "Accounts Manager", "System Manager"})  # fmt: skip
		self.assertIn("Mobile Visit Rejection", [s.link_to for s in workspace.shortcuts])
		self.assertEqual(len(workspace.number_cards), 7)
		self.assertEqual(len(workspace.charts), 4)
		self.assertEqual(frappe.db.get_value("Desktop Icon", "Mobile Sales", ["link_type", "link_to", "hidden"]), ("Workspace Sidebar", "Mobile Sales", 0))
