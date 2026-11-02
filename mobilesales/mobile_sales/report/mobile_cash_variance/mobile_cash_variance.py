# Copyright (c) 2026, Evonet and contributors
# For license information, please see license.txt
"""Mobile Cash Variance (spec §7). Figures: mobilesales.services.reports.cash_variance_rows."""

from frappe import _

from mobilesales.services import reports


def execute(filters=None):
	rows = reports.cash_variance_rows(filters)
	return columns(), rows, None, None


def columns():
	return [dict(c, label=_(c["label"])) for c in COLUMNS]


COLUMNS = [
 {
  "fieldname": "mobile_trip",
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
  "fieldname": "settlement",
  "label": "Settlement",
  "fieldtype": "Link",
  "width": 130,
  "options": "Mobile Settlement"
 },
 {
  "fieldname": "opening_float",
  "label": "Opening Float",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "expected",
  "label": "Expected",
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
  "fieldname": "variance",
  "label": "Variance",
  "fieldtype": "Currency",
  "width": 120
 },
 {
  "fieldname": "action",
  "label": "Action",
  "fieldtype": "Data",
  "width": 130
 },
 {
  "fieldname": "journal",
  "label": "Journal",
  "fieldtype": "Link",
  "width": 140,
  "options": "Journal Entry"
 }
]
