frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["Mobile Sales by Agent"] = {
	method: "mobilesales.mobile_sales.dashboard_chart_source.mobile_sales_by_agent.mobile_sales_by_agent.get",
	filters: [],
};
