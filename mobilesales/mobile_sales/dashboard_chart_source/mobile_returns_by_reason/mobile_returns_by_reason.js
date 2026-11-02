frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["Mobile Returns by Reason"] = {
	method: "mobilesales.mobile_sales.dashboard_chart_source.mobile_returns_by_reason.mobile_returns_by_reason.get",
	filters: [],
};
