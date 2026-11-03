"""Profile of one van day on the performance volume (docs/PERFORMANCE.md): trip load, a sale with payment, a sale with a
return, end of day and the settlement chain, each step timed with cProfile and every SQL statement summed by its shape.
Runs a day for each of three agents on the three days after the last seeded day (cold, warm, profiled; one day each so
no posting goes back in time) inside one transaction that is rolled back, then writes a JSON file to compare two volumes:

	bench --site mstest.local execute mobilesales.perf.profile.run --kwargs "{'out': '/tmp/ms_profile_day30.json'}"
	bench --site mstest.local execute mobilesales.perf.profile.seed_day --kwargs "{'out': '/tmp/ms_seedday_day30.json'}"
	bench --site mstest.local execute mobilesales.perf.profile.compare --kwargs "{'before': '...', 'after': '...'}"
"""

import cProfile
import io
import json
import pstats
import random
import re
import statistics
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import patch

import frappe
from frappe.model.workflow import apply_workflow
from frappe.utils import add_days, flt, getdate, nowdate

from mobilesales.perf import seed

LITERAL = re.compile(r"'(?:[^'\\]|\\.)*'|\b\d+(?:\.\d+)?\b")


class SqlLog:
	"""Every frappe.db.sql call while active: count, total time and the slowest statement as sent, per query shape."""

	def __init__(self):
		self.shapes = defaultdict(lambda: {"count": 0, "total": 0.0, "slowest": 0.0, "sample": None})

	@contextmanager
	def active(self):
		original = frappe.db.sql

		def sql(query, *args, **kwargs):
			began = time.perf_counter()
			try:
				return original(query, *args, **kwargs)
			finally:
				took = time.perf_counter() - began
				shape = self.shapes[LITERAL.sub("?", " ".join(str(query).split()))[:600]]
				shape["count"] += 1
				shape["total"] += took
				if took >= shape["slowest"]:
					shape["slowest"], shape["sample"] = took, frappe.db.last_query

		frappe.db.sql = sql
		try:
			yield self
		finally:
			del frappe.db.sql  # back to the class method


def run(out=None, visits=8, returns=5, top=25, explain=12):
	seed.guard()
	frappe.flags.mute_emails = True
	from mobilesales.api import mobile as api

	with seed.jobs_inline():
		world = seed.ensure_world(0, add_days(nowdate(), -61))
	agents = frappe.get_all("Mobile Sales Agent", filters={"agent_name": ["like", f"{seed.PREFIX}%"]}, fields=["name", "user", "default_route"], order_by="name", limit=3)
	last = frappe.db.sql("select max(trip_date) from `tabMobile Trip` where agent in %s and docstatus = 1", [[a.name for a in agents]])[0][0]
	day = getdate(add_days(last, 1)) if last else getdate(add_days(nowdate(), -60))
	volume = {dt: frappe.db.count(dt) for dt in ("Mobile Trip", "Customer Visit", "Sales Invoice", "Payment Entry", "Stock Ledger Entry", "GL Entry", "Repost Item Valuation")}
	print("day", day, "volume", volume, flush=True)
	plain = [i.item_code for i in world.stock_items if not i.has_batch_no]
	lines = [{"item_code": world.stock_items[0].item_code, "qty": 1}, {"item_code": plain[1], "qty": 1}, {"item_code": plain[5], "qty": 1}]

	result = {"day": str(day), "volume": volume, "runs": []}
	try:
		with seed.jobs_inline(), patch.object(frappe.db, "commit"):
			for slot, agent in enumerate(agents):
				profiled = slot == len(agents) - 1
				run_day = getdate(add_days(day, slot))
				morning = datetime.combine(run_day, datetime.min.time()).replace(hour=6)
				route = frappe.get_all("Mobile Route Customer", filters={"parent": agent.default_route}, pluck="customer", order_by="sequence")
				steps, profilers = {}, defaultdict(cProfile.Profile)

				def step(name, moment, user, fn):
					"""One call of a step; repeated calls of a step add up (walls listed, SQL summed, one profile)."""
					frappe.set_user(user)
					log = SqlLog()
					with seed.at(moment), log.active():
						began = time.perf_counter()
						if profiled:
							profilers[name].enable()
						value = fn()
						profilers[name].disable()
						wall = time.perf_counter() - began
					data = steps.setdefault(name, {"walls": [], "sql_count": 0, "sql_total": 0.0, "shapes": {}})
					data["walls"].append(wall)
					for key, shape in log.shapes.items():
						data["sql_count"] += shape["count"]
						data["sql_total"] += shape["total"]
						into = data["shapes"].setdefault(key, {"count": 0, "total": 0.0, "slowest": 0.0, "sample": None})
						into["count"] += shape["count"]
						into["total"] += shape["total"]
						if shape["slowest"] >= into["slowest"]:
							into["slowest"], into["sample"] = shape["slowest"], shape["sample"]
					return value

				def load():
					trip = frappe.get_doc({"doctype": "Mobile Trip", "agent": agent.name, "trip_date": run_day, "opening_cash_float": 0,
						"load_items": [{"item_code": i.item_code, "qty": 12 if i.has_batch_no else 18} for i in world.stock_items]})  # fmt: skip
					trip.insert()
					trip.submit()
					return trip

				trip = step("load", morning, seed.STORE, load)
				frappe.set_user(agent.user)
				api.start_trip(trip.name)
				invoices = []
				for k in range(visits):
					customer, moment = route[k], morning.replace(hour=8) + timedelta(minutes=15 * k)
					priced = step("price_cart", moment, agent.user, lambda: api.price_cart(trip.name, customer, lines))
					payload = {"client_ref": f"prof-{trip.name}-s{k}", "mobile_trip": trip.name, "customer": customer, "outcome": "Sale",
						"sale_items": lines, "collect_amount": priced["due_on_sale"]}  # fmt: skip
					step("sale_payment", moment, agent.user, lambda: api.submit_visit(payload))
					invoices.append((customer, frappe.db.get_value("Customer Visit", {"client_ref": payload["client_ref"]}, "sales_invoice")))

				for k, (customer, invoice) in enumerate(invoices[:returns]):
					moment = morning.replace(hour=13) + timedelta(minutes=15 * k)
					back = [{"item_code": plain[1], "qty": 1, "against_invoice": invoice, "return_reason": "Damaged", "condition": "Resaleable"}]

					def sale_return():
						again = api.price_cart(trip.name, customer, lines[1:], returns_items=back)
						return api.submit_visit({"client_ref": f"prof-{trip.name}-r{k}", "mobile_trip": trip.name, "customer": customer,
							"outcome": "Sale", "sale_items": lines[1:], "return_items": back, "collect_amount": again["due_on_sale"]})  # fmt: skip

					step("sale_return", moment, agent.user, sale_return)

				def settle():
					api.end_day(trip.name)
					draft = api.get_settlement_draft(trip.name)
					saved = api.save_settlement(trip.name, {"stock_lines": [{"item_code": r["item_code"], "returned_qty": flt(r["expected_balance"])} for r in draft["stock_lines"]],
						"cash_handed_over": flt(draft["expected_cash"])})  # fmt: skip
					api.submit_settlement_for_verification(saved["name"])
					for user_id, action in ((seed.STORE, "Verify Stock"), (seed.CASHIER, "Verify Cash")):
						frappe.set_user(user_id)
						apply_workflow(frappe.get_doc("Mobile Settlement", saved["name"]), action)

				step("settlement", morning.replace(hour=20), agent.user, settle)
				for name, data in steps.items():
					data["wall"] = statistics.median(data["walls"])
					data["per_call_sql"] = data["sql_total"] / len(data["walls"])
					if profiled:
						text = io.StringIO()
						pstats.Stats(profilers[name], stream=text).sort_stats("cumulative").print_stats(top)
						data["profile"] = text.getvalue()
				print(("profiled " if profiled else "run ") + agent.name + "  " + "  ".join(f"{k} {v['wall']:.2f}s x{len(v['walls'])}" for k, v in steps.items()), flush=True)
				result["runs"].append(steps)

			frappe.set_user("Administrator")
			result["explain"] = explain_top(result["runs"][-1], explain)
	finally:
		frappe.set_user("Administrator")
		frappe.db.rollback()
	if out:
		with open(out, "w") as f:
			json.dump(result, f, indent=1, default=str)
		print("wrote", out, flush=True)
	return {k: round(v["wall"], 3) for k, v in result["runs"][-1].items()}  # medians of the profiled day


def seed_day(out=None, agents=3, visits=30, top=40, explain=12):
	"""One whole seed day (seed.run_day: loads, every visit kind, return picker, settlements) for `agents` agents on the
	day after the last seeded day, profiled as one step and rolled back: what a seed day costs beyond the profiled steps."""
	seed.guard()
	frappe.flags.mute_emails = True
	with seed.jobs_inline():
		world = seed.ensure_world(10, add_days(nowdate(), -61))
	last = frappe.db.sql("select max(trip_date) from `tabMobile Trip` where docstatus = 1")[0][0]
	day = getdate(add_days(last, 1)) if last else getdate(add_days(nowdate(), -60))
	volume = {dt: frappe.db.count(dt) for dt in ("Mobile Trip", "Customer Visit", "Sales Invoice", "Stock Ledger Entry", "Repost Item Valuation")}
	print("day", day, "volume", volume, flush=True)
	log, profiler, stats = SqlLog(), cProfile.Profile(), defaultdict(int)
	try:
		with seed.jobs_inline(), patch.object(frappe.db, "commit"), log.active():
			began = time.perf_counter()
			profiler.enable()
			seed.run_day(world, world.agents[: int(agents)], day, int(visits), random.Random(7), stats)
			profiler.disable()
			wall = time.perf_counter() - began
		data = {"walls": [wall], "wall": wall, "stats": dict(stats), "shapes": dict(log.shapes),
			"sql_count": sum(s["count"] for s in log.shapes.values()), "sql_total": sum(s["total"] for s in log.shapes.values())}  # fmt: skip
		for order in ("cumulative", "tottime"):
			text = io.StringIO()
			pstats.Stats(profiler, stream=text).sort_stats(order).print_stats(top)
			data[f"profile_{order}"] = text.getvalue()
		result = {"day": str(day), "volume": volume, "runs": [{"seed_day": data}]}
		result["explain"] = explain_top(result["runs"][-1], explain)
	finally:
		frappe.set_user("Administrator")
		frappe.db.rollback()
	print(f"seed day {wall:.1f}s  sql {data['sql_total']:.1f}s/{data['sql_count']}q  {dict(stats)}", flush=True)
	if out:
		with open(out, "w") as f:
			json.dump(result, f, indent=1, default=str)
		print("wrote", out, flush=True)
	return round(wall, 1)


def process_growth(days=4, agents=3, visits=15, prefill=0):
	"""Seed days one after another in ONE process (as seed.run does), rolled back: per-day wall time and the frappe.local /
	frappe.flags containers that grow, to tell volume growth from state that piles up in a long-running process."""
	seed.guard()
	frappe.flags.mute_emails = True
	with seed.jobs_inline():
		world = seed.ensure_world(10, add_days(nowdate(), -61))
	last = frappe.db.sql("select max(trip_date) from `tabMobile Trip` where docstatus = 1")[0][0] or add_days(nowdate(), -61)
	stats, walls = defaultdict(int), []
	frappe.flags.currently_saving.extend(("Stock Ledger Entry", f"leaked-{n}") for n in range(int(prefill)))  # as after 30 seed days
	try:
		with seed.jobs_inline(), patch.object(frappe.db, "commit"):
			for n in range(int(days)):
				day = getdate(add_days(last, n + 1))
				began = time.perf_counter()
				seed.run_day(world, world.agents[: int(agents)], day, int(visits), random.Random(n), stats)
				walls.append(round(time.perf_counter() - began, 1))
				leaked = Counter(doctype for doctype, _name in frappe.flags.currently_saving)
				print(day, f"{walls[-1]:6.1f}s", local_sizes(), dict(leaked.most_common(8)), flush=True)
	finally:
		frappe.set_user("Administrator")
		frappe.db.rollback()
	return walls


def local_sizes(least=50) -> dict:
	sizes = {}
	for prefix, space in (("local.", dict(iter(frappe.local))), ("flags.", dict(frappe.flags))):
		for key, value in space.items():
			try:
				size = len(value)
			except TypeError:
				continue
			if size >= least:
				sizes[prefix + key] = size
	return sizes


def explain_top(steps, n):
	"""EXPLAIN for the n slowest select shapes of the profiled day (by total time over all steps)."""
	shapes = defaultdict(lambda: {"total": 0.0, "sample": None})
	for data in steps.values():
		for key, s in data["shapes"].items():
			shapes[key]["total"] += s["total"]
			shapes[key]["sample"] = shapes[key]["sample"] or s["sample"]
	plans = {}
	for key, s in sorted(shapes.items(), key=lambda kv: -kv[1]["total"])[:n]:
		sample = (s["sample"] or "").strip()
		if not sample.lower().startswith("select"):
			continue
		try:
			plans[key] = frappe.db.sql("explain " + sample.removesuffix("for update").removesuffix("FOR UPDATE"), as_dict=True)
		except Exception as e:
			plans[key] = str(e)
	return plans


def explain_file(path, least=500):
	"""EXPLAIN every select shape of a saved profile on the current data; prints the plans that examine `least`+ rows."""
	data = json.load(open(path))
	plans = explain_top(data["runs"][-1], 100000)
	for key, plan in plans.items():
		if isinstance(plan, str):
			continue
		big = [p for p in plan if int(re.match(r"\d*", str(p.get("rows") or 0)).group() or 0) >= int(least)]
		if big:
			print(key[:260])
			for p in big:
				print("    ", p.get("table"), p.get("type"), p.get("key"), p.get("rows"), p.get("Extra"))
	return len(plans)


def time_samples(path, needles, repeat=20):
	"""Warm median time of the saved sample statement of each query shape containing one of `needles` (a list)."""
	data = json.load(open(path))
	samples = {}
	for step in data["runs"][-1].values():
		for key, shape in step["shapes"].items():
			for needle in needles:
				if needle in key and shape["sample"] and needle not in samples:
					samples[needle] = shape["sample"]
	timings = {}
	for needle, sample in samples.items():
		frappe.db.sql(sample)
		runs = []
		for _i in range(int(repeat)):
			began = time.perf_counter()
			frappe.db.sql(sample)
			runs.append(time.perf_counter() - began)
		timings[needle] = round(statistics.median(runs) * 1000, 2)
		print(f"{timings[needle]:8.2f} ms  {needle}", flush=True)
	return timings


def compare(before, after, top=20):
	"""Per step median wall and SQL time per call of two profiles, and the query shapes whose time per call grew most."""
	a, b = (json.load(open(p)) for p in (before, after))
	print("volume before", a["volume"], "\nvolume after ", b["volume"])
	names = [n for n in a["runs"][-1] if n in b["runs"][-1]]
	for name in names:
		walls = [r[name]["wall"] for r in a["runs"]], [r[name]["wall"] for r in b["runs"]]
		x, y = a["runs"][-1][name], b["runs"][-1][name]
		n0, n1 = len(x["walls"]), len(y["walls"])
		print(f"{name:13} median wall (warm, profiled) {" ".join(f"{w:6.2f}" for w in walls[0][1:])}s -> {" ".join(f"{w:6.2f}" for w in walls[1][1:])}s"
			f"   sql per call {x['sql_total'] / n0:6.3f}s/{x['sql_count'] // n0}q -> {y['sql_total'] / n1:6.3f}s/{y['sql_count'] // n1}q")
	grew = []
	for name in names:
		x, y = a["runs"][-1][name]["shapes"], b["runs"][-1][name]["shapes"]
		for key in set(x) | set(y):
			n0, n1 = len(a["runs"][-1][name]["walls"]), len(b["runs"][-1][name]["walls"])
			t0, t1 = x.get(key, {}).get("total", 0) / n0, y.get(key, {}).get("total", 0) / n1
			grew.append((t1 - t0, name, t0, t1, y.get(key, {}).get("count", 0) // n1, key))
	for delta, name, t0, t1, count, key in sorted(grew, reverse=True)[:top]:
		print(f"+{delta * 1000:8.1f}ms {name:12} {t0 * 1000:8.1f} -> {t1 * 1000:8.1f}ms x{count}  {key[:220]}")


def reports(names=None, days=60, top=8):
	"""Each report over the last `days` days as the supervisor: wall time, query count and the heaviest query shapes."""
	from frappe.desk.query_report import run as run_report

	from mobilesales.perf.timings import REPORTS

	seed.guard()
	frappe.set_user(seed.SUPERVISOR)
	filters = {"company": seed.COMPANY, "from_date": add_days(nowdate(), -days), "to_date": nowdate()}
	out = {}
	for name in names or REPORTS:
		run_report(name, filters)  # warm
		log = SqlLog()
		began = time.perf_counter()
		with log.active():
			rows = run_report(name, filters)["result"]
		took = time.perf_counter() - began
		shapes = sorted(log.shapes.items(), key=lambda kv: -kv[1]["total"])
		queries = sum(s["count"] for _q, s in shapes)
		sql = sum(s["total"] for _q, s in shapes)
		out[name] = {"seconds": took, "rows": len(rows), "queries": queries, "sql": sql}
		print(f"{name:40} {took:6.2f}s rows {len(rows):5} queries {queries:6} sql {sql:6.2f}s", flush=True)
		for query, s in shapes[:top]:
			print(f"    {s['count']:6} x {s['total']:6.2f}s  {query[:150]}", flush=True)
	frappe.set_user("Administrator")
	return out
