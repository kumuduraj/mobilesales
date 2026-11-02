# Copyright (c) 2026, Evonet and contributors
# For license information, please see license.txt
"""Mobile Strike Rate (workspace chart, last 30 days): mobilesales.services.reports.chart_strike_rate."""

import frappe

from mobilesales.services import reports


@frappe.whitelist()
def get(chart_name=None, chart=None, no_cache=None, filters=None, from_date=None, to_date=None, timespan=None, time_interval=None, heatmap_year=None):
	return reports.chart_strike_rate()
