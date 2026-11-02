# Copyright (c) 2026, Evonet and contributors
# For license information, please see license.txt
"""Daily Trip Summary (spec §7). Figures: mobilesales.services.reports.trip_summary_rows."""

from frappe import _

from mobilesales.services import reports


def execute(filters=None):
	rows = reports.trip_summary_rows(filters)
	return columns(), rows, None, None


def columns():
	return [dict(c, label=_(c["label"])) for c in COLUMNS]


COLUMNS = [
 {
  "fieldname": "trip",
  "label": "Trip",
  "fieldtype": "Link",
  "width": 130,
  "options": "Mobile Trip"
 },
 {
  "fieldname": "trip_date",
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
  "fieldname": "vehicle",
  "label": "Vehicle",
  "fieldtype": "Link",
  "width": 90,
  "options": "Mobile Vehicle"
 },
 {
  "fieldname": "route",
  "label": "Route",
  "fieldtype": "Link",
  "width": 110,
  "options": "Mobile Route"
 },
 {
  "fieldname": "status",
  "label": "Trip Status",
  "fieldtype": "Data",
  "width": 90
 },
 {
  "fieldname": "issued_value",
  "label": "Issued Value",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "sold_value",
  "label": "Sold Value (cost)",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "returned_qty",
  "label": "Returned",
  "fieldtype": "Float",
  "width": 90
 },
 {
  "fieldname": "damaged_qty",
  "label": "Damaged",
  "fieldtype": "Float",
  "width": 90
 },
 {
  "fieldname": "missing_qty",
  "label": "Missing",
  "fieldtype": "Float",
  "width": 90
 },
 {
  "fieldname": "missing_value",
  "label": "Missing Value",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "invoices",
  "label": "Invoices",
  "fieldtype": "Int",
  "width": 80
 },
 {
  "fieldname": "sales_total",
  "label": "Invoiced",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "cash_collected",
  "label": "Collected",
  "fieldtype": "Currency",
  "width": 120
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
  "fieldname": "credit_applied",
  "label": "Return Credit Applied",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "line_discount",
  "label": "Line Discounts",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "invoice_discount",
  "label": "Invoice Discounts",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "handed_over",
  "label": "Handed Over",
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
  "fieldname": "settlement",
  "label": "Settlement",
  "fieldtype": "Link",
  "width": 130,
  "options": "Mobile Settlement"
 },
 {
  "fieldname": "settlement_status",
  "label": "Settlement Status",
  "fieldtype": "Data",
  "width": 120
 }
]
