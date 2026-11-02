# Copyright (c) 2026, Evonet and contributors
# For license information, please see license.txt
"""Outstanding by Agent (spec §7). Figures: mobilesales.services.reports.outstanding_rows."""

from frappe import _

from mobilesales.services import reports


def execute(filters=None):
	rows = reports.outstanding_rows(filters)
	return columns(), rows, None, None


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
  "fieldname": "customer",
  "label": "Customer",
  "fieldtype": "Link",
  "width": 140,
  "options": "Customer"
 },
 {
  "fieldname": "customer_name",
  "label": "Customer Name",
  "fieldtype": "Data",
  "width": 160
 },
 {
  "fieldname": "invoices",
  "label": "Invoices",
  "fieldtype": "Int",
  "width": 80
 },
 {
  "fieldname": "outstanding",
  "label": "Outstanding",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "range_0_30",
  "label": "0-30",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "range_31_60",
  "label": "31-60",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "range_61_90",
  "label": "61-90",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "range_90_above",
  "label": "90+",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "oldest",
  "label": "Oldest Invoice",
  "fieldtype": "Date",
  "width": 100
 }
]
