frappe.query_reports["Mobile Trip Day Report"] = {
	filters: [{ fieldname: "mobile_trip", label: __("Mobile Trip"), fieldtype: "Link", options: "Mobile Trip", reqd: 1 }],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		return data && data.is_section ? `<b>${value}</b>` : value;
	},
};
