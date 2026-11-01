<template>
	<div class="space-y-3">
		<div v-if="!trip" class="card text-center text-gray-500">{{ __("No open trip today.") }}</div>
		<div v-else-if="!visits.length" class="card text-center text-gray-500">{{ loading ? __("Loading…") : __("No visits yet.") }}</div>
		<div v-for="v in visits" :key="v.name" class="card">
			<div class="flex items-start justify-between">
				<div>
					<div class="font-semibold">{{ v.customer_name }}</div>
					<div class="text-xs text-gray-500">{{ v.name }} · {{ time(v.visit_datetime) }}</div>
				</div>
				<span class="rounded-full px-2 py-0.5 text-xs" :class="v.docstatus === 1 ? 'bg-green-100 text-green-800' : 'bg-amber-100 text-amber-800'">
					{{ v.docstatus === 1 ? __(v.outcome) : __("Draft") }}
				</span>
			</div>
			<div class="mt-2 text-sm text-gray-600">
				<span v-if="v.no_sale_reason">{{ v.no_sale_reason }}</span>
				<span v-if="v.sales_invoice">{{ __("Invoice") }} {{ money(v.rounded_total || v.grand_total) }}</span>
				<span v-if="v.total_collected"> · {{ __("collected") }} {{ money(v.total_collected) }}</span>
			</div>
			<div v-if="v.sales_invoice || v.payment_entry" class="mt-3 grid grid-cols-2 gap-2">
				<a v-if="v.sales_invoice" class="btn-secondary min-h-[44px] text-sm" :href="printUrl('Sales Invoice', v.sales_invoice, 'Mobile Invoice 4in')" target="_blank">
					{{ __("Invoice") }}
				</a>
				<a v-if="v.payment_entry" class="btn-secondary min-h-[44px] text-sm" :href="printUrl('Payment Entry', v.payment_entry, 'Mobile Collection Receipt')" target="_blank">
					{{ __("Receipt") }}
				</a>
			</div>
		</div>
		<p v-if="message" class="text-sm text-red-700">{{ message }}</p>
	</div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue"
import { call, m } from "../api"
import { money, printUrl, session } from "../state"

const trip = computed(() => session.ctx?.trip)
const visits = ref([])
const loading = ref(false)
const message = ref("")
const time = (value) => (value || "").slice(11, 16)

onMounted(async () => {
	if (!trip.value) return
	loading.value = true
	try {
		visits.value = await call(m("get_visits"), { trip: trip.value.name })
	} catch (e) {
		message.value = e.message
	} finally {
		loading.value = false
	}
})
</script>
