# Copyright (c) 2026, Evonet and contributors
# For license information, please see license.txt
"""Customer Stock Position (spec §7). Figures: mobilesales.services.reports.stock_position_rows."""

from frappe import _

from mobilesales.services import reports


def execute(filters=None):
	rows = reports.stock_position_rows(filters)
	return columns(), rows, None, None


def columns():
	return [dict(c, label=_(c["label"])) for c in COLUMNS]


COLUMNS = [
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
  "fieldname": "item_code",
  "label": "Item",
  "fieldtype": "Link",
  "width": 130,
  "options": "Item"
 },
 {
  "fieldname": "qty_on_shelf",
  "label": "Qty on Shelf",
  "fieldtype": "Float",
  "width": 90
 },
 {
  "fieldname": "uom",
  "label": "UOM",
  "fieldtype": "Link",
  "width": 70,
  "options": "UOM"
 },
 {
  "fieldname": "counted_on",
  "label": "Counted On",
  "fieldtype": "Date",
  "width": 95
 },
 {
  "fieldname": "expiry_date",
  "label": "Expiry",
  "fieldtype": "Date",
  "width": 95
 },
 {
  "fieldname": "competitor_item",
  "label": "Competitor Item",
  "fieldtype": "Data",
  "width": 130
 },
 {
  "fieldname": "days_since_visit",
  "label": "Days Since Visit",
  "fieldtype": "Int",
  "width": 80
 },
 {
  "fieldname": "last_purchase_qty",
  "label": "Last Purchase Qty",
  "fieldtype": "Float",
  "width": 90
 },
 {
  "fieldname": "last_purchase_date",
  "label": "Last Purchase",
  "fieldtype": "Date",
  "width": 95
 }
]
