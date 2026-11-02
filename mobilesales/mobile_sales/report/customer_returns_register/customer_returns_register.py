# Copyright (c) 2026, Evonet and contributors
# For license information, please see license.txt
"""Customer Returns Register (spec §7). Figures: mobilesales.services.reports.return_rows."""

from frappe import _

from mobilesales.services import reports


def execute(filters=None):
	rows = reports.return_rows(filters)
	return columns(), rows, None, None


def columns():
	return [dict(c, label=_(c["label"])) for c in COLUMNS]


COLUMNS = [
 {
  "fieldname": "row_type",
  "label": "Type",
  "fieldtype": "Data",
  "width": 80
 },
 {
  "fieldname": "date",
  "label": "Date",
  "fieldtype": "Date",
  "width": 95
 },
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
  "fieldname": "mobile_trip",
  "label": "Trip",
  "fieldtype": "Link",
  "width": 130,
  "options": "Mobile Trip"
 },
 {
  "fieldname": "visit",
  "label": "Visit",
  "fieldtype": "Link",
  "width": 120,
  "options": "Customer Visit"
 },
 {
  "fieldname": "customer",
  "label": "Customer",
  "fieldtype": "Link",
  "width": 140,
  "options": "Customer"
 },
 {
  "fieldname": "item_code",
  "label": "Item",
  "fieldtype": "Link",
  "width": 120,
  "options": "Item"
 },
 {
  "fieldname": "qty",
  "label": "Qty",
  "fieldtype": "Float",
  "width": 90
 },
 {
  "fieldname": "uom",
  "label": "UOM",
  "fieldtype": "Link",
  "width": 60,
  "options": "UOM"
 },
 {
  "fieldname": "rate",
  "label": "Rate",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "amount",
  "label": "Credit Amount",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "reason",
  "label": "Reason",
  "fieldtype": "Link",
  "width": 120,
  "options": "Mobile Return Reason"
 },
 {
  "fieldname": "condition",
  "label": "Condition",
  "fieldtype": "Data",
  "width": 90
 },
 {
  "fieldname": "remarks",
  "label": "Remarks",
  "fieldtype": "Data",
  "width": 130
 },
 {
  "fieldname": "against_invoice",
  "label": "Against Invoice",
  "fieldtype": "Link",
  "width": 140,
  "options": "Sales Invoice"
 },
 {
  "fieldname": "credit_note",
  "label": "Credit Note",
  "fieldtype": "Link",
  "width": 140,
  "options": "Sales Invoice"
 },
 {
  "fieldname": "credit_applied",
  "label": "Credit Applied To",
  "fieldtype": "Data",
  "width": 200
 },
 {
  "fieldname": "credit_applied_amount",
  "label": "Credit Applied",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "credit_left",
  "label": "Credit Left",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "received",
  "label": "Received (settlement)",
  "fieldtype": "Float",
  "width": 90
 },
 {
  "fieldname": "damaged",
  "label": "Damaged (settlement)",
  "fieldtype": "Float",
  "width": 90
 },
 {
  "fieldname": "missing",
  "label": "Missing (settlement)",
  "fieldtype": "Float",
  "width": 90
 },
 {
  "fieldname": "voucher",
  "label": "Voucher",
  "fieldtype": "Data",
  "width": 150
 }
]
