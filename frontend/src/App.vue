<template>
	<div class="mx-auto flex min-h-screen max-w-md flex-col">
		<header class="sticky top-0 z-10 bg-gray-900 px-4 py-3 text-white">
			<div class="flex items-center justify-between">
				<div>
					<div class="text-lg font-semibold">{{ __("Mobile Sales") }}</div>
					<div class="text-xs text-gray-300">{{ session.ctx?.agent?.agent_name || session.ctx?.full_name }}</div>
				</div>
				<span v-if="session.ctx?.trip" class="rounded-full bg-white/15 px-3 py-1 text-xs">
					{{ session.ctx.trip.name }} · {{ __(session.ctx.trip.status) }}
				</span>
			</div>
		</header>
		<div v-if="!online" class="bg-red-600 px-4 py-2 text-center text-sm font-medium text-white">
			{{ __("No connection — you can look around, but nothing can be saved until you are back online.") }}
		</div>

		<main class="flex-1 px-3 pb-24 pt-3">
			<div v-if="session.error" class="card mb-3 border-red-300 text-red-700">{{ session.error }}</div>
			<div v-if="!session.ctx" class="py-16 text-center text-gray-500">{{ __("Loading…") }}</div>
			<div v-else-if="!session.ctx.agent" class="card text-center">
				{{ __("Your user is not set up as a Mobile Sales Agent. Ask your supervisor.") }}
			</div>
			<router-view v-else />
		</main>

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
import { onMounted } from "vue"
import { online, session } from "./state"
import { loadContext } from "./context"
import { __ } from "./translation"

const tabs = [
	{ to: "/", icon: "🚚", label: __("Today") },
	{ to: "/route", icon: "🗺️", label: __("Route") },
	{ to: "/history", icon: "🧾", label: __("History") },
	{ to: "/settlement", icon: "💵", label: __("Settlement") },
]

onMounted(() => {
	session.ctx = window.ms_boot.context
	if (!session.ctx) loadContext()
})
</script>
