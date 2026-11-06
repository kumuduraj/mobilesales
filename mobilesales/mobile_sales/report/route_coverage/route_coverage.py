# Copyright (c) 2026, Evonet and contributors
# For license information, please see license.txt
"""Route Coverage (spec §7). Figures: mobilesales.services.reports.coverage_rows."""

from frappe import _

from mobilesales.services import reports


def execute(filters=None):
	rows = reports.coverage_rows(filters)
	return columns(), rows, None, None


def columns():
	return [dict(c, label=_(c["label"])) for c in COLUMNS]


COLUMNS = [
 {
  "fieldname": "trip_date",
  "label": "Date",
  "fieldtype": "Date",
  "width": 95
 },
 {
  "fieldname": "mobile_trip",
  "label": "Trip",
  "fieldtype": "Link",
  "width": 130,
  "options": "Mobile Trip"
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
  "fieldname": "route",
  "label": "Route",
  "fieldtype": "Link",
  "width": 110,
  "options": "Mobile Route"
 },
 {
  "fieldname": "sequence",
  "label": "Seq",
  "fieldtype": "Int",
  "width": 50
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
  "fieldname": "planned",
  "label": "Planned",
  "fieldtype": "Check",
  "width": 70
 },
 {
  "fieldname": "visited",
  "label": "Visited",
  "fieldtype": "Check",
  "width": 70
 },
 {
  "fieldname": "outcome",
  "label": "Outcome",
  "fieldtype": "Data",
  "width": 110
 },
 {
  "fieldname": "status",
  "label": "Status",
  "fieldtype": "Data",
  "width": 120
 },
 {
  "fieldname": "out_of_sequence",
  "label": "Visited out of sequence",
  "fieldtype": "Check",
  "width": 110
 },
 {
  "fieldname": "trip_out_of_sequence",
  "label": "Out-of-sequence visits (trip)",
  "fieldtype": "Int",
  "width": 120
 }
]
