# Copyright (c) 2026, Evonet and contributors
# For license information, please see license.txt
"""No Sale Reason Analysis (spec §7). Figures: mobilesales.services.reports.no_sale_rows."""

from frappe import _
from frappe.utils import flt

from mobilesales.services import reports


def execute(filters=None):
	rows = reports.no_sale_rows(filters, group_by=(filters or {}).get("group_by") or "agent")
	return columns(), rows, None, chart(rows)


def columns():
	return [dict(c, label=_(c["label"])) for c in COLUMNS]


COLUMNS = [
 {
  "fieldname": "group_name",
  "label": "Agent / Territory",
  "fieldtype": "Data",
  "width": 160
 },
 {
  "fieldname": "reason",
  "label": "Reason",
  "fieldtype": "Data",
  "width": 160
 },
 {
  "fieldname": "category",
  "label": "Category",
  "fieldtype": "Data",
  "width": 120
 },
 {
  "fieldname": "count",
  "label": "No Sale Visits",
  "fieldtype": "Int",
  "width": 80
 },
 {
  "fieldname": "visits",
  "label": "All Visits",
  "fieldtype": "Int",
  "width": 80
 },
 {
  "fieldname": "pct",
  "label": "% of Visits",
  "fieldtype": "Percent",
  "width": 90
 }
]


def chart(rows):
	if not rows:
		return None
	totals = {}
	for row in rows:
		totals[row.reason] = totals.get(row.reason, 0) + flt(row.count)
	return {
		"data": {"labels": list(totals), "datasets": [{"name": _("No-sale visits"), "values": list(totals.values())}]},
		"type": "donut",
	}
