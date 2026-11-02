frappe.provide("frappe.dashboards.chart_sources");

frappe.dashboards.chart_sources["Mobile No Sale Reasons"] = {
	method: "mobilesales.mobile_sales.dashboard_chart_source.mobile_no_sale_reasons.mobile_no_sale_reasons.get",
	filters: [],
};
