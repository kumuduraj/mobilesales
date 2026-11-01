def after_install():
	"""Run once after `install-app mobilesales`.

	Phase 0: no-op. Later phases add idempotent setup here (check-exists before insert),
	so running it again must never duplicate or overwrite site data.
	"""
	pass


def after_migrate():
	"""Run after every `bench migrate`.

	Phase 0: no-op. Anything added here must be idempotent and must never touch
	documents owned by other apps (frappe, erpnext, slmfc, deliveryplan, ...).
	"""
	pass
