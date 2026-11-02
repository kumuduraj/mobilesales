# Copyright (c) 2026, Evonet and contributors
# For license information, please see license.txt
"""Mobile Stock Variance (spec §7). Figures: mobilesales.services.reports.stock_variance_rows."""

from frappe import _

from mobilesales.services import reports


def execute(filters=None):
	rows = reports.stock_variance_rows(filters)
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
  "fieldname": "item_code",
  "label": "Item",
  "fieldtype": "Link",
  "width": 130,
  "options": "Item"
 },
 {
  "fieldname": "item_name",
  "label": "Item Name",
  "fieldtype": "Data",
  "width": 160
 },
 {
  "fieldname": "uom",
  "label": "UOM",
  "fieldtype": "Link",
  "width": 70,
  "options": "UOM"
 },
 {
  "fieldname": "trips",
  "label": "Trips",
  "fieldtype": "Int",
  "width": 80
 },
 {
  "fieldname": "issued",
  "label": "Issued",
  "fieldtype": "Float",
  "width": 90
 },
 {
  "fieldname": "sold",
  "label": "Sold",
  "fieldtype": "Float",
  "width": 90
 },
 {
  "fieldname": "returned",
  "label": "Returned",
  "fieldtype": "Float",
  "width": 90
 },
 {
  "fieldname": "damaged",
  "label": "Damaged",
  "fieldtype": "Float",
  "width": 90
 },
 {
  "fieldname": "missing",
  "label": "Missing",
  "fieldtype": "Float",
  "width": 90
 },
 {
  "fieldname": "excess",
  "label": "Excess",
  "fieldtype": "Float",
  "width": 90
 },
 {
  "fieldname": "issued_value",
  "label": "Issued Value",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "damaged_value",
  "label": "Damaged Value",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "missing_value",
  "label": "Missing Value",
  "fieldtype": "Currency",
  "width": 120
 }
]
