# Copyright (c) 2026, Evonet and contributors
# For license information, please see license.txt
"""Customer Visit Register (spec §7). Figures: mobilesales.services.reports.visit_rows."""

from frappe import _

from mobilesales.services import reports


def execute(filters=None):
	rows = reports.visit_rows(filters)
	if (filters or {}).get("outcome"):
		rows = [r for r in rows if r.outcome == filters.get("outcome")]
	return columns(), rows, None, None


def columns():
	return [dict(c, label=_(c["label"])) for c in COLUMNS]


COLUMNS = [
 {
  "fieldname": "visit",
  "label": "Visit",
  "fieldtype": "Link",
  "width": 120,
  "options": "Customer Visit"
 },
 {
  "fieldname": "visit_datetime",
  "label": "Date / Time",
  "fieldtype": "Datetime",
  "width": 150
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
  "fieldname": "mobile_trip",
  "label": "Trip",
  "fieldtype": "Link",
  "width": 130,
  "options": "Mobile Trip"
 },
 {
  "fieldname": "customer",
  "label": "Customer",
  "fieldtype": "Link",
  "width": 140,
  "options": "Customer"
 },
 {
  "fieldname": "territory",
  "label": "Territory",
  "fieldtype": "Link",
  "width": 100,
  "options": "Territory"
 },
 {
  "fieldname": "outcome",
  "label": "Outcome",
  "fieldtype": "Data",
  "width": 110
 },
 {
  "fieldname": "off_route",
  "label": "Off Route",
  "fieldtype": "Check",
  "width": 70
 },
 {
  "fieldname": "no_sale_reason",
  "label": "No Sale Reason",
  "fieldtype": "Link",
  "width": 130,
  "options": "Visit No Sale Reason"
 },
 {
  "fieldname": "remarks",
  "label": "Remarks",
  "fieldtype": "Data",
  "width": 150
 },
 {
  "fieldname": "sales_invoice",
  "label": "Invoice",
  "fieldtype": "Link",
  "width": 140,
  "options": "Sales Invoice"
 },
 {
  "fieldname": "amount",
  "label": "Amount",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "discount",
  "label": "Manual Discount",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "return_total",
  "label": "Returns",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "credit_applied",
  "label": "Credit Applied",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "collected",
  "label": "Collected",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "gps",
  "label": "GPS",
  "fieldtype": "Data",
  "width": 120
 }
]
