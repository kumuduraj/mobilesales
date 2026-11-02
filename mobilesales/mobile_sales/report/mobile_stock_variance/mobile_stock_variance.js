frappe.query_reports["Mobile Stock Variance"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.month_start(), reqd: 1 },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.get_today(), reqd: 1 },
		{ fieldname: "agent", label: __("Agent"), fieldtype: "Link", options: "Mobile Sales Agent" },
		{ fieldname: "vehicle", label: __("Vehicle"), fieldtype: "Link", options: "Mobile Vehicle" },
		{ fieldname: "route", label: __("Route"), fieldtype: "Link", options: "Mobile Route" },
		{ fieldname: "territory", label: __("Territory"), fieldtype: "Link", options: "Territory" },
	],
};
