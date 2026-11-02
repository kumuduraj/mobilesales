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
		<div>
			<label class="label">{{ __("Customer group") }} *</label>
			<select v-model="form.customer_group" class="field" required>
				<option v-for="g in options.customer_groups" :key="g" :value="g">{{ g }}</option>
			</select>
		</div>
		<div>
			<label class="label">{{ __("Territory") }} *</label>
			<select v-model="form.territory" class="field" required>
				<option v-for="t in options.territories" :key="t" :value="t">{{ t }}</option>
			</select>
		</div>
		<div>
			<label class="label">{{ __("Add to route") }}</label>
			<select v-model="form.route" class="field">
				<option value="">{{ __("No route") }}</option>
				<option v-for="r in options.routes" :key="r" :value="r">{{ r }}</option>
			</select>
		</div>
		<p v-if="message" class="text-sm" :class="existing ? 'text-amber-700' : 'text-red-700'">{{ message }}</p>
		<button class="btn-primary w-full" :disabled="busy || !online || !form.customer_name || !form.customer_group || !form.territory">{{ __("Create customer") }}</button>
	</form>
</template>

<script setup>
import { onMounted, reactive, ref } from "vue"
import { call, m } from "../api"
import { online } from "../state"
import { __ } from "../translation"

const emit = defineEmits(["created"])
const form = reactive({ customer_name: "", mobile_no: "", address_line1: "", city: "", customer_group: "", territory: "", route: "" })
const options = reactive({ customer_groups: [], territories: [], routes: [] })
const busy = ref(false)
const message = ref("")
const existing = ref(false)

onMounted(async () => {
	try {
		const result = await call(m("get_customer_form_options"))
		Object.assign(options, result)
		form.customer_group ||= result.default_customer_group || ""
		form.territory ||= result.default_territory || ""
	} catch (e) {
		message.value = e.message
	}
})

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
