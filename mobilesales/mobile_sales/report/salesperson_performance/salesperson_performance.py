# Copyright (c) 2026, Evonet and contributors
# For license information, please see license.txt
"""Salesperson Performance (spec §7). Figures: mobilesales.services.reports.performance_rows."""

from frappe import _
from frappe.utils import flt

from mobilesales.services import reports


def execute(filters=None):
	rows = reports.performance_rows(filters)
	return columns(), rows, None, chart(rows)


def columns():
	return [dict(c, label=_(c["label"])) for c in COLUMNS]


COLUMNS = [
 {
  "fieldname": "agent",
  "label": "Agent",
  "fieldtype": "Link",
  "width": 110,
  "options": "Mobile Sales Agent"
 },
 {
  "fieldname": "agent_name",
  "label": "Agent Name",
  "fieldtype": "Data",
  "width": 140
 },
 {
  "fieldname": "trips",
  "label": "Trips",
  "fieldtype": "Int",
  "width": 80
 },
 {
  "fieldname": "working_days",
  "label": "Working Days",
  "fieldtype": "Int",
  "width": 80
 },
 {
  "fieldname": "visits",
  "label": "Visits",
  "fieldtype": "Int",
  "width": 80
 },
 {
  "fieldname": "planned_visits",
  "label": "Planned",
  "fieldtype": "Int",
  "width": 80
 },
 {
  "fieldname": "route_coverage",
  "label": "Route Coverage %",
  "fieldtype": "Percent",
  "width": 90
 },
 {
  "fieldname": "sales_visits",
  "label": "Sales Visits",
  "fieldtype": "Int",
  "width": 80
 },
 {
  "fieldname": "strike_rate",
  "label": "Strike Rate %",
  "fieldtype": "Percent",
  "width": 90
 },
 {
  "fieldname": "invoices",
  "label": "Invoices",
  "fieldtype": "Int",
  "width": 80
 },
 {
  "fieldname": "net_sales",
  "label": "Net Sales",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "sales_total",
  "label": "Sales (Invoice Total)",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "avg_invoice",
  "label": "Avg Invoice",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "lines_per_invoice",
  "label": "Lines / Invoice",
  "fieldtype": "Float",
  "width": 90
 },
 {
  "fieldname": "collections",
  "label": "Collections",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "collection_pct",
  "label": "Collection % of Sales",
  "fieldtype": "Percent",
  "width": 90
 },
 {
  "fieldname": "credit_given",
  "label": "Credit Sales",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "return_value",
  "label": "Customer Returns",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "returns_pct",
  "label": "Van Returns % of Issued",
  "fieldtype": "Percent",
  "width": 90
 },
 {
  "fieldname": "damage_pct",
  "label": "Damage %",
  "fieldtype": "Percent",
  "width": 90
 },
 {
  "fieldname": "missing_value",
  "label": "Stock Shortage Value",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "cash_variance",
  "label": "Cash Variance",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "manual_discount",
  "label": "Manual Discounts",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "discount_pct",
  "label": "Discount % of List",
  "fieldtype": "Percent",
  "width": 90
 },
 {
  "fieldname": "sales_per_day",
  "label": "Sales / Day",
  "fieldtype": "Currency",
  "width": 120
 }
]


def chart(rows):
	if not rows:
		return None
	totals = {}
	for row in rows:
		totals[row.agent_name] = totals.get(row.agent_name, 0) + flt(row.sales_total)
	return {
		"data": {"labels": list(totals), "datasets": [{"name": _("Sales"), "values": list(totals.values())}]},
		"type": "bar",
	}
