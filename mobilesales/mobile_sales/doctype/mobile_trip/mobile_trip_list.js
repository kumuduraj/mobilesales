// Copyright (c) 2026, Evonet and contributors
// For license information, please see license.txt

const MOBILE_TRIP_STATUS_COLORS = {
	Draft: "gray",
	Loaded: "blue",
	"In Field": "orange",
	Settling: "yellow",
	Settled: "green",
	Cancelled: "red",
};

frappe.listview_settings["Mobile Trip"] = {
	add_fields: ["status"],
	has_indicator_for_draft: true,
	get_indicator(doc) {
		const status = doc.status || "Draft";
		return [__(status), MOBILE_TRIP_STATUS_COLORS[status] || "gray", "status,=," + status];
	},
};
