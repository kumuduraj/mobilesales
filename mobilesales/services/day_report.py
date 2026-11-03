"""Mobile Trip Day Report as a PDF (spec §7.1): attached to the settlement when it is submitted (Approved), so
the signed version never changes, and mailed every evening to the Mobile Sales Supervisors."""

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from mobilesales.services import settings as ms_settings

PRINT_FORMAT = "Mobile Trip Day Report"
SUPERVISOR_ROLE = "Mobile Sales Supervisor"


def queue_attach(settlement):
	"""on_submit: render after the commit, in the background — a slow PDF never holds up the approval."""
	frappe.enqueue(
		"mobilesales.services.day_report.attach_day_report",
		queue="long",
		settlement=settlement.name,
		enqueue_after_commit=True,
	)


def file_name(settlement) -> str:
	return f"{settlement.mobile_trip} Day Report.pdf"


def render_pdf(settlement) -> bytes:
	return frappe.get_print("Mobile Settlement", settlement.name, PRINT_FORMAT, as_pdf=True, no_letterhead=1)


def attach_day_report(settlement):
	"""Render and attach the Day Report PDF (private file) once; returns the File name."""
	doc = frappe.get_doc("Mobile Settlement", settlement)
	existing = frappe.db.get_value(
		"File", {"attached_to_doctype": doc.doctype, "attached_to_name": doc.name, "file_name": file_name(doc)}, "name"
	)
	if existing:
		return existing
	file = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name(doc),
			"attached_to_doctype": doc.doctype,
			"attached_to_name": doc.name,
			"is_private": 1,
			"content": render_pdf(doc),
		}
	)
	file.flags.ignore_permissions = True
	file.insert()
	return file.name


def settled_today(day=None) -> list:
	"""Settlements submitted (Approved) on the day."""
	day = getdate(day or nowdate())
	return frappe.get_all(
		"Mobile Settlement",
		filters={"docstatus": 1, "modified": ["between", [f"{day} 00:00:00", f"{day} 23:59:59.999999"]]},
		fields=["name", "mobile_trip", "agent_name", "trip_date", "expected_cash", "cash_handed_over", "cash_variance"],
		order_by="mobile_trip asc",
	)


def supervisors() -> list:
	users = frappe.get_all("Has Role", filters={"role": SUPERVISOR_ROLE, "parenttype": "User"}, pluck="parent")
	return frappe.get_all(
		"User", filters={"name": ["in", users or [""]], "enabled": 1, "user_type": "System User"}, pluck="email"
	)


def outgoing_email_ready() -> bool:
	"""A default outgoing Email Account, or a mail server in the site config (docs/ADMIN_GUIDE.md: email)."""
	return bool(
		frappe.db.exists("Email Account", {"enable_outgoing": 1, "default_outgoing": 1}) or frappe.conf.get("mail_server")
	)


def send_daily_reports(day=None):
	"""Scheduler, 20:00: one email with every Day Report of the trips settled today. Skipped when switched off
	in Mobile Sales Settings, when the site has no outgoing email yet (one log line, no Error Log, nothing
	queued), when nothing was settled or when there is no supervisor to send to."""
	if not ms_settings.get_settings().daily_report_email:
		return None
	if not outgoing_email_ready():
		frappe.logger("mobilesales").info("Daily Report Email skipped: no default outgoing Email Account on this site")
		return None
	settlements = settled_today(day)
	recipients = [r for r in supervisors() if r]
	if not settlements or not recipients:
		return None
	attachments = []
	for s in settlements:
		doc = frappe.get_doc("Mobile Settlement", s.name)
		attachments.append({"fname": file_name(doc), "fcontent": render_pdf(doc)})
	rows = "".join(
		f"<tr><td>{s.mobile_trip}</td><td>{frappe.utils.escape_html(s.agent_name or '')}</td><td>{s.name}</td>"
		f"<td style='text-align:right'>{frappe.format(s.expected_cash, 'Currency')}</td>"
		f"<td style='text-align:right'>{frappe.format(s.cash_handed_over, 'Currency')}</td>"
		f"<td style='text-align:right'>{frappe.format(s.cash_variance, 'Currency')}</td></tr>"
		for s in settlements
	)
	day = getdate(day or nowdate())
	frappe.sendmail(
		recipients=recipients,
		subject=_("Mobile Sales day reports {0}: {1} trip(s) settled").format(frappe.format(day, "Date"), len(settlements)),
		message=(
			f"<p>{_('The Mobile Trip Day Reports of the trips settled today are attached.')}</p>"
			f"<table border='1' cellpadding='4' style='border-collapse:collapse'><tr><th>{_('Trip')}</th><th>{_('Agent')}</th>"
			f"<th>{_('Settlement')}</th><th>{_('Expected')}</th><th>{_('Handed over')}</th><th>{_('Variance')}</th></tr>{rows}</table>"
		),
		attachments=attachments,
		reference_doctype="Mobile Settlement",
		reference_name=settlements[0].name,
	)
	return [s.name for s in settlements]
