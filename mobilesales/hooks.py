app_name = "mobilesales"
app_title = "Mobile Sales"
app_publisher = "Evonet"
app_description = "Mobile Billing / van sales for ERPNext"
app_email = "rajerp@evonet.lk"
app_license = "mit"

# Apps
# ------------------

required_apps = ["erpnext"]

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "mobilesales",
# 		"logo": "/assets/mobilesales/logo.png",
# 		"title": "Mobile Sales",
# 		"route": "/mobilesales",
# 		"has_permission": "mobilesales.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/mobilesales/css/mobilesales.css"
# app_include_js = "/assets/mobilesales/js/mobilesales.js"

# include js, css files in header of web template
# web_include_css = "/assets/mobilesales/css/mobilesales.css"
# web_include_js = "/assets/mobilesales/js/mobilesales.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "mobilesales/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "mobilesales/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# The 4-inch prints read their credit / cash figures from here (one place, unit-tested).
jinja = {
	"methods": [
		"mobilesales.services.prints.mobile_invoice_print",
		"mobilesales.services.prints.mobile_return_note_print",
		"mobilesales.services.prints.mobile_visit_bill_print",
		"mobilesales.services.reports.mobile_day_report",
	],
}

# Installation
# ------------

# before_install = "mobilesales.install.before_install"
after_install = "mobilesales.setup.install.after_install"
after_migrate = ["mobilesales.setup.install.after_migrate"]

# Fixtures
# --------
# Explicit by name: never export records this app does not own.

fixtures = [
	{
		"dt": "Role",
		"filters": [
			[
				"name",
				"in",
				[
					"Mobile Sales Agent",
					"Mobile Sales Store Keeper",
					"Mobile Sales Cashier",
					"Mobile Sales Supervisor",
				],
			]
		],
	},
	{
		"dt": "Custom Field",
		"filters": [
			[
				"name",
				"in",
				[
					"Sales Invoice-mobile_section",
					"Sales Invoice-mobile_trip",
					"Sales Invoice-customer_visit",
					"Sales Invoice-is_mobile_sale",
					"Payment Entry-mobile_section",
					"Payment Entry-mobile_trip",
					"Payment Entry-customer_visit",
					"Stock Entry-mobile_section",
					"Stock Entry-mobile_trip",
					"Stock Entry-mobile_purpose",
					"Journal Entry-mobile_section",
					"Journal Entry-mobile_trip",
					"Journal Entry-mobile_settlement",
				],
			]
		],
	},
	{
		"dt": "Workflow State",
		"filters": [["name", "in", ["Draft", "Pending Store", "Pending Cashier", "Pending Approval", "Cancelled"]]],
	},
	{
		"dt": "Workflow Action Master",
		"filters": [["name", "in", ["Submit for Verification", "Verify Stock", "Verify Cash", "Cancel"]]],
	},
	{"dt": "Workflow", "filters": [["name", "in", ["Mobile Settlement Approval"]]]},
]

# Uninstallation
# ------------

# before_uninstall = "mobilesales.uninstall.before_uninstall"
# after_uninstall = "mobilesales.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "mobilesales.utils.before_app_install"
# after_app_install = "mobilesales.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "mobilesales.utils.before_app_uninstall"
# after_app_uninstall = "mobilesales.utils.after_app_uninstall"

# Build
# ------------------
# To hook into the build process

# after_build = "mobilesales.build.after_build"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "mobilesales.notifications.get_notification_config"

# Awesome Bar
# -----------
# Extra search results: list of dicts with label, description, route, index.
# route: ["List", "ToDo"], "/desk/docs/some/page", or "https://example.com"
# awesomebar_search = ["mobilesales.search.awesomebar_results"]

# Permissions
# -----------
# Permissions evaluated in scripted ways

permission_query_conditions = {
	"Mobile Sales Agent": "mobilesales.overrides.permissions.agent_query_conditions",
	"Mobile Trip": "mobilesales.overrides.permissions.trip_query_conditions",
	"Customer Visit": "mobilesales.overrides.permissions.visit_query_conditions",
	"Sales Invoice": "mobilesales.overrides.permissions.sales_invoice_query_conditions",
	"Payment Entry": "mobilesales.overrides.permissions.payment_entry_query_conditions",
	"Mobile Settlement": "mobilesales.overrides.permissions.settlement_query_conditions",
}

has_permission = {
	"Mobile Sales Agent": "mobilesales.overrides.permissions.agent_has_permission",
	"Mobile Trip": "mobilesales.overrides.permissions.trip_has_permission",
	"Customer Visit": "mobilesales.overrides.permissions.visit_has_permission",
	"Sales Invoice": "mobilesales.overrides.permissions.mobile_voucher_has_permission",
	"Payment Entry": "mobilesales.overrides.permissions.mobile_voucher_has_permission",
	"Mobile Settlement": "mobilesales.overrides.permissions.settlement_has_permission",
}

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Sales Invoice": {
		"validate": "mobilesales.overrides.guards.validate_sales_invoice",
		"before_cancel": "mobilesales.overrides.guards.before_cancel_sales_invoice",
	},
	"Delivery Note": {"validate": "mobilesales.overrides.guards.validate_delivery_note"},
	"Stock Reconciliation": {"validate": "mobilesales.overrides.guards.validate_stock_reconciliation"},
	"Stock Entry": {"validate": "mobilesales.overrides.guards.validate_stock_entry"},
	"Purchase Receipt": {"validate": "mobilesales.overrides.guards.validate_purchase_receipt"},
	"Purchase Invoice": {"validate": "mobilesales.overrides.guards.validate_purchase_receipt"},
	"Payment Entry": {"validate": "mobilesales.overrides.guards.validate_payment_entry"},
	"Journal Entry": {"validate": "mobilesales.overrides.guards.validate_journal_entry"},
	"Warehouse": {
		"on_update": "mobilesales.overrides.guards.on_warehouse_change",
		"on_trash": "mobilesales.overrides.guards.on_warehouse_change",
		"after_rename": "mobilesales.overrides.guards.on_warehouse_change",
	},
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"cron": {
		# Mobile Trip Day Reports of the day's settled trips to the supervisors (Mobile Sales Settings switch)
		"0 20 * * *": ["mobilesales.services.day_report.send_daily_reports"],
	},
}

# scheduler_events = {
# 	"all": [
# 		"mobilesales.tasks.all"
# 	],
# 	"daily": [
# 		"mobilesales.tasks.daily"
# 	],
# 	"hourly": [
# 		"mobilesales.tasks.hourly"
# 	],
# 	"weekly": [
# 		"mobilesales.tasks.weekly"
# 	],
# 	"monthly": [
# 		"mobilesales.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "mobilesales.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "mobilesales.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "mobilesales.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "mobilesales.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["mobilesales.utils.before_request"]
# after_request = ["mobilesales.utils.after_request"]

# Job Events
# ----------
# before_job = ["mobilesales.utils.before_job"]
# after_job = ["mobilesales.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"mobilesales.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []

# Mobile phone app (SPA host page www/mobile-sales.py)
website_route_rules = [
	{"from_route": "/mobile-sales/<path:app_path>", "to_route": "mobile-sales"},
]
