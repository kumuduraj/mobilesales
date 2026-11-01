# CLAUDE.md — mobilesales

## What this is
Frappe app `mobilesales` (module "Mobile Sales") for ERPNext v16: van/route sales —
stock issue to agent, customer visits, invoice + collection, end-of-day settlement, reports.
Full spec: docs/SPEC.md ("mobile_sales" in the spec = "mobilesales").
Repo: git@github-mobilesales:kumuduraj/mobilesales.git (github.com/kumuduraj/mobilesales)

## Environment
- Bench: /home/rajerp/AgroPublic (user rajerp, no sudo)
- Site: agrosys.evonet.lk (dev + test). Also installed: frappe_theme, evonav, slmfc, deliveryplan — never break them.
- Company on site: Agro Republic (Pvt) Ltd (ARL). Batch-tracked FG items exist (spec §5.6).
- Restart: never run sudo/supervisorctl. Ask Raj to run:
  sudo supervisorctl restart AgroPublic-web: AgroPublic-workers:
  (other benches share this server — never "restart all")
- 14 DocTypes use Custom DocPerm copies (made by mobilesales/setup/permissions.py to give Mobile Sales roles
  access): Customer, Item, UOM, Price List, Item Price, Batch, Contact, Address, Territory, Customer Group,
  Sales Invoice, Payment Entry, Account, Serial and Batch Bundle. After every ERPNext upgrade check migrate output / Error Log for
  the mobilesales permission warning ("mobilesales: standard permissions changed for <DocType>").

## Non-negotiable rules
1. NEVER modify apps/frappe, apps/erpnext or any other app. Before every commit:
   `git -C apps/frappe status --porcelain` empty; `git -C apps/erpnext status --porcelain`
   shows only " M banking/yarn.lock" (pre-existing baseline).
2. No override_doctype_class, no monkey-patching, no override_whitelisted_methods.
3. Extend only via hooks.py doc_events / permission_query_conditions / has_permission,
   fixtures, own DocTypes, own whitelisted APIs.
4. Every hook on a standard DocType returns immediately when the doc is not mobile
   (no mobile_trip and no van warehouse / agent cash account touched). SLMFC and deliveryplan
   Stock Entries must never be blocked.
5. Nothing UI-only. Custom Field, Property Setter, Role, Workflow, Workflow State/Action,
   Print Format, Workspace, Number Card, Dashboard Chart → fixtures or DocType JSON in repo.
6. Existing-site data changes → patch in mobilesales/patches/ + patches.txt. Idempotent.
7. after_install / after_migrate idempotent (check-exists before insert).
8. No hard-coded company/warehouse/account/user names (ARL values go in Mobile Sales Settings).
9. Frontend built into mobilesales/public/frontend and www/mobile-sales.html; built output IS committed.
10. Never commit secrets, site_config.json, node_modules.
11. On this bench, never run `bench new-app`, `bench get-app`, `bench update` or `bench restart`:
    with restart_supervisor_on_update=true they call sudo supervisorctl and fail. Use:
    - new code from GitHub: git clone into apps/mobilesales + ./env/bin/pip install -e apps/mobilesales
    - apps.txt edits by hand (keep trailing newline), then ask Raj to restart immediately.
12. Never git checkout/reset/switch commits inside apps/mobilesales while the site is running.
    For checking old commits use `git worktree add /tmp/<name> <commit>` and remove it after.
13. Every business-flow test runs as the real role user (agent / store keeper / cashier / supervisor) via
    frappe.set_user. Administrator is allowed only for test data setup. A flow test that runs as
    Administrator is a bug.

## Definition of done for EVERY task
1. `bench --site agrosys.evonet.lk migrate` passes.
2. Tests: `bench --site agrosys.evonet.lk set-config allow_tests true`,
   `bench --site agrosys.evonet.lk run-tests --app mobilesales`, then set allow_tests false.
3. Fixture-type record changed → `bench --site agrosys.evonet.lk export-fixtures --app mobilesales`.
4. Frontend changed → `cd frontend && yarn build`.
5. Core baseline check (rule 1); only mobilesales files changed.
6. Commit (Conventional Commits) and `git push origin develop`.
7. If Python/hooks changed, tell Raj a restart is needed.
8. Report: what changed, files, test result, commit hash.

## Phase release (end of each phase)
1. Backup agrosys.evonet.lk.
2. mv apps/mobilesales ~/mobilesales.local.bak ;
   git clone -b develop git@github-mobilesales:kumuduraj/mobilesales.git apps/mobilesales ;
   ./env/bin/pip install -e apps/mobilesales ; migrate, build, tests.
   On failure restore the local folder, fix, push, repeat.
3. Smoke test: standard SO → DN → SI → PE on Finished Goods - ARL; one SLMFC Stock Entry; one deliveryplan Trip Sheet.
4. Merge develop → main, tag v0.N.0, push main + tags — in a worktree, never in apps/mobilesales:
   `git worktree add /tmp/ms_main main && git -C /tmp/ms_main merge --no-ff origin/develop && git -C /tmp/ms_main tag … && git -C /tmp/ms_main push origin main --tags && git worktree remove /tmp/ms_main`

## Coding conventions
- Business logic in mobilesales/services/*.py; controllers thin.
- flt(..., precision) for money/qty (Kg items → fractional qty); frappe.utils for dates.
- Whitelisted APIs resolve the agent from frappe.session.user and re-check ownership.
- Create ERPNext docs via frappe.get_doc(...).insert()/.submit(); Sales Invoice: set_missing_values()
  then calculate_taxes_and_totals().
- Batches: rely on Stock Settings auto bundle creation (FIFO) for outward; explicit bundles only at settlement return.
- frappe.db.sql only for read-only aggregation, parameterised.
- User-facing strings in _("...").
- Tests: FrappeTestCase in mobilesales/tests/, own test data, never rely on site data.

## When unsure
Stop and ask. Never disable a failing test. Never touch core to make something work.
