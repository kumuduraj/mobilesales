<template>
	<div class="mx-auto flex min-h-screen max-w-md flex-col">
		<header class="sticky top-0 z-20 bg-gray-900 px-4 py-3 text-white">
			<div class="flex items-center justify-between gap-2">
				<div class="min-w-0">
					<div class="text-lg font-semibold">{{ __("Mobile Sales") }}</div>
					<button
						v-if="session.ctx"
						type="button"
						class="account-button flex max-w-full items-center gap-1 truncate text-xs text-gray-300"
						:aria-expanded="menuOpen ? 'true' : 'false'"
						@click="menuOpen = !menuOpen"
					>
						<span class="truncate">{{ displayName }}</span>
						<span aria-hidden="true">▾</span>
					</button>
				</div>
				<div class="flex flex-col items-end gap-1">
					<span class="connection flex items-center gap-1 text-xs" :data-state="connection">
						<span class="inline-block h-2 w-2 rounded-full" :class="dotClass"></span>
						{{ connectionLabel }}
					</span>
					<span v-if="session.ctx?.trip" class="rounded-full bg-white/15 px-3 py-1 text-xs">
						{{ session.ctx.trip.name }} · {{ __(session.ctx.trip.status) }}
					</span>
				</div>
			</div>

			<div v-if="menuOpen && session.ctx" class="account-menu absolute inset-x-3 top-full z-30 mt-1 rounded-lg bg-white p-4 text-sm text-gray-900 shadow-lg">
				<div class="font-semibold">{{ session.ctx.full_name }}</div>
				<div class="text-gray-600">{{ session.ctx.user }}</div>
				<dl class="mt-2 grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-gray-700">
					<template v-if="session.ctx.agent">
						<dt>{{ __("Agent") }}</dt>
						<dd>{{ session.ctx.agent.name }}</dd>
					</template>
					<template v-if="session.ctx.trip?.vehicle">
						<dt>{{ __("Vehicle") }}</dt>
						<dd>{{ session.ctx.trip.vehicle }}</dd>
					</template>
					<dt>{{ __("App version") }}</dt>
					<dd>{{ session.ctx.app_version || "—" }}</dd>
				</dl>
				<button type="button" class="btn-secondary mt-3 w-full" @click="askLogout">{{ __("Log out") }}</button>
			</div>
		</header>
		<div v-if="!online" class="bg-red-600 px-4 py-2 text-center text-sm font-medium text-white">
			{{ __("No connection — you can look around, but nothing can be saved until you are back online.") }}
		</div>
		<div v-if="toast" class="toast bg-green-600 px-4 py-2 text-center text-sm font-medium text-white" role="status">{{ toast }}</div>

		<main class="flex-1 px-3 pb-24 pt-3" @click="menuOpen = false">
			<div v-if="session.expired" class="card session-ended text-center">
				<div class="font-semibold">{{ SESSION_ENDED() }}</div>
				<div class="mt-1 text-sm text-gray-500">{{ __("Opening the login page…") }}</div>
			</div>
			<template v-else>
				<div v-if="session.error" class="card mb-3 border-red-300 text-red-700">{{ session.error }}</div>
				<div v-if="!session.ctx" class="py-16 text-center text-gray-500">{{ __("Loading…") }}</div>
				<div v-else-if="!session.ctx.agent" class="card text-center">
					{{ __("Your user is not set up as a Mobile Sales Agent. Ask your supervisor.") }}
				</div>
				<router-view v-else />
			</template>
		</main>

		<div v-if="confirmingLogout" class="fixed inset-0 z-40 flex items-end bg-black/40 p-3" role="dialog" aria-modal="true">
			<div class="logout-dialog mx-auto w-full max-w-md rounded-lg bg-white p-4">
				<p class="font-medium">{{ __("Log out? Unsaved visit data on this screen will be lost.") }}</p>
				<p v-if="unsaved.visit" class="mt-2 text-sm font-medium text-red-700">
					{{ __("A visit is in progress and has not been submitted.") }}
				</p>
				<p v-if="unsaved.settlement" class="mt-2 text-sm font-medium text-red-700">
					{{ __("The settlement has changes that are not saved.") }}
				</p>
				<p v-if="logoutMessage" class="mt-2 text-sm text-red-700">{{ logoutMessage }}</p>
				<div class="mt-4 grid grid-cols-2 gap-2">
					<button ref="cancelLogout" type="button" class="btn-secondary" @click="confirmingLogout = false">{{ __("Cancel") }}</button>
					<button type="button" class="btn-primary" :disabled="loggingOut || !online" @click="doLogout">{{ __("Log out") }}</button>
				</div>
			</div>
		</div>

		<nav class="fixed inset-x-0 bottom-0 z-10 border-t border-gray-200 bg-white pb-[env(safe-area-inset-bottom)]">
			<div class="mx-auto grid max-w-md grid-cols-4">
				<router-link
					v-for="tab in tabs"
					:key="tab.to"
					:to="tab.to"
					class="flex min-h-[60px] flex-col items-center justify-center text-xs text-gray-500"
					active-class="!text-gray-900 font-semibold"
					:exact-active-class="tab.to === '/' ? '!text-gray-900 font-semibold' : ''"
				>
					<span class="text-xl leading-none">{{ tab.icon }}</span>
					<span class="mt-1">{{ tab.label }}</span>
				</router-link>
			</div>
		</nav>
	</div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue"
import { logout } from "./account"
import { SESSION_ENDED } from "./api"
import { onReconnect, startConnectionMonitor, stopConnectionMonitor } from "./connection"
import { loadContext } from "./context"
import { connection, online, session, toast, unsaved } from "./state"
import { __ } from "./translation"

const tabs = [
	{ to: "/", icon: "🚚", label: __("Today") },
	{ to: "/route", icon: "🗺️", label: __("Route") },
	{ to: "/history", icon: "🧾", label: __("History") },
	{ to: "/settlement", icon: "💵", label: __("Settlement") },
]

const menuOpen = ref(false)
const confirmingLogout = ref(false)
const loggingOut = ref(false)
const logoutMessage = ref("")
const cancelLogout = ref(null)

const displayName = computed(() => session.ctx?.agent?.agent_name || session.ctx?.full_name || session.ctx?.user)
const connectionLabel = computed(
	() => ({ online: __("Online"), offline: __("Offline"), reconnecting: __("Reconnecting…") })[connection.value]
)
const dotClass = computed(
	() => ({ online: "bg-green-400", offline: "bg-red-500", reconnecting: "bg-amber-400" })[connection.value]
)

async function askLogout() {
	menuOpen.value = false
	logoutMessage.value = ""
	confirmingLogout.value = true
	await nextTick()
	cancelLogout.value?.focus() // default: Cancel
}

async function doLogout() {
	if (loggingOut.value) return
	loggingOut.value = true
	try {
		await logout()
	} catch (e) {
		logoutMessage.value = __("Could not log out: the server cannot be reached. Try again when you are online.")
	} finally {
		loggingOut.value = false
	}
}

onReconnect(() => loadContext())

onMounted(() => {
	session.ctx = window.ms_boot.context
	if (!session.ctx) loadContext()
	startConnectionMonitor()
})
onBeforeUnmount(stopConnectionMonitor)
</script>
