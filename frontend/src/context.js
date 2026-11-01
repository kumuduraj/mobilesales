import { call, m } from "./api"
import { session } from "./state"

export async function loadContext() {
	session.loading = true
	session.error = null
	try {
		session.ctx = await call(m("get_context"))
	} catch (e) {
		session.error = e.message
	} finally {
		session.loading = false
	}
}
