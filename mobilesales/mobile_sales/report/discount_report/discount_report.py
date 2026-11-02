# Copyright (c) 2026, Evonet and contributors
# For license information, please see license.txt
"""Discount Report (spec §7). Figures: mobilesales.services.reports.discount_rows."""

from frappe import _

from mobilesales.services import reports


def execute(filters=None):
	rows = reports.discount_rows(filters)
	return columns(), rows, None, None


def columns():
	return [dict(c, label=_(c["label"])) for c in COLUMNS]


COLUMNS = [
 {
  "fieldname": "sales_invoice",
  "label": "Invoice",
  "fieldtype": "Link",
  "width": 140,
  "options": "Sales Invoice"
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
  "fieldname": "customer",
  "label": "Customer",
  "fieldtype": "Link",
  "width": 140,
  "options": "Customer"
 },
 {
  "fieldname": "price_list_value",
  "label": "Price List Value",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "pricing_rule_discount",
  "label": "Pricing Rule Effect",
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
  "label": "Invoice Discount",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "invoice_discount_pct",
  "label": "Invoice Disc. %",
  "fieldtype": "Percent",
  "width": 90
 },
 {
  "fieldname": "manual_discount",
  "label": "Manual Discounts",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "manual_pct",
  "label": "Manual % of List",
  "fieldtype": "Percent",
  "width": 90
 },
 {
  "fieldname": "cap_pct",
  "label": "Agent Cap %",
  "fieldtype": "Percent",
  "width": 90
 },
 {
  "fieldname": "within_cap",
  "label": "Within Cap",
  "fieldtype": "Data",
  "width": 80
 },
 {
  "fieldname": "net_total",
  "label": "Net Total",
  "fieldtype": "Currency",
  "width": 120
 }
]
