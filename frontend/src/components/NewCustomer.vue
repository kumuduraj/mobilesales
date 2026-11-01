<template>
	<form class="mt-3 space-y-3 border-t border-gray-100 pt-3" @submit.prevent="save">
		<div>
			<label class="label">{{ __("Customer name") }} *</label>
			<input v-model.trim="form.customer_name" class="field" required />
		</div>
		<div>
			<label class="label">{{ __("Mobile number") }}</label>
			<input v-model.trim="form.mobile_no" class="field" type="tel" inputmode="tel" />
		</div>
		<div>
			<label class="label">{{ __("Address line 1") }}</label>
			<input v-model.trim="form.address_line1" class="field" />
		</div>
		<div>
			<label class="label">{{ __("City") }}</label>
			<input v-model.trim="form.city" class="field" />
		</div>
		<p v-if="message" class="text-sm" :class="existing ? 'text-amber-700' : 'text-red-700'">{{ message }}</p>
		<button class="btn-primary w-full" :disabled="busy || !online || !form.customer_name">{{ __("Create customer") }}</button>
	</form>
</template>

<script setup>
import { reactive, ref } from "vue"
import { call, m } from "../api"
import { online } from "../state"

const emit = defineEmits(["created"])
const form = reactive({ customer_name: "", mobile_no: "", address_line1: "", city: "" })
const busy = ref(false)
const message = ref("")
const existing = ref(false)

async function save() {
	if (busy.value) return
	busy.value = true
	message.value = ""
	try {
		const result = await call(m("create_customer"), { payload: form })
		existing.value = result.existing
		if (result.existing) message.value = __("This mobile number already belongs to {0}.", [result.customer_name])
		emit("created", result)
	} catch (e) {
		message.value = e.message
	} finally {
		busy.value = false
	}
}
</script>
