frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["Mobile Strike Rate"] = {
	method: "mobilesales.mobile_sales.dashboard_chart_source.mobile_strike_rate.mobile_strike_rate.get",
	filters: [],
};
