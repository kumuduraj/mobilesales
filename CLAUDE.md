# CLAUDE.md — mobilesales

## What this is
Frappe app `mobilesales` (module "Mobile Sales") for ERPNext v16: van/route sales —
stock issue to agent, customer visits, invoice + collection, end-of-day settlement, reports.
Full spec: docs/SPEC.md ("mobile_sales" in the spec = "mobilesales").
Repo: git@github-mobilesales:kumuduraj/mobilesales.git (github.com/kumuduraj/mobilesales)

## Environment
- Bench: /home/rajerp/AgroPublic (user rajerp, no sudo)
- Sites on this bench:
  - agrosys.evonet.lk — LIVE / pilot only: migrate, smoke (drafts + rollback), pilots, Raj's manual testing.
    NEVER run-tests here. Also installed: frappe_theme, evonav, slmfc, deliveryplan — never break them.
  - mstest.local — ALL test runs (frappe + erpnext + mobilesales only; allow_tests on; scheduler disabled;
    own test company). Test data lives only here.
- Company on site: Agro Republic (Pvt) Ltd (ARL). Batch-tracked FG items exist (spec §5.6).
- Restart: never run sudo/supervisorctl. Ask Raj to run:
  sudo supervisorctl restart AgroPublic-web: AgroPublic-workers:
  (other benches share this server — never "restart all")
- 14 DocTypes use Custom DocPerm copies (made by mobilesales/setup/permissions.py to give Mobile Sales roles
  access): Customer, Item, UOM, Price List, Item Price, Batch, Contact, Address, Territory, Customer Group,
  Sales Invoice, Payment Entry, Account, Serial and Batch Bundle. After every ERPNext upgrade check migrate output / Error Log for
  the mobilesales permission warning ("mobilesales: standard permissions changed for <DocType>"): it compares the
  standard DocPerms with a baseline taken at copy time and reports each change once. uninstall-app removes the
  role rules and every copy still equal to the standard rules (before_uninstall).

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
    `bench get-app` on a throwaway bench in /tmp also ends with `supervisorctl restart <bench>:` (it reached
    supervisord in Phase 7; the group did not exist). Add apps there by git clone + pip install -e too.
12. Never git checkout/reset/switch commits inside apps/mobilesales while the site is running.
    For checking old commits use `git worktree add /tmp/<name> <commit>` and remove it after.
13. Every business-flow test runs as the real role user (agent / store keeper / cashier / supervisor) via
    frappe.set_user. Administrator is allowed only for test data setup. A flow test that runs as
    Administrator is a bug.
14. Tests must never commit. The shared test base replaces frappe.db.commit with an error; any code path that
    commits (host pages, whitelisted endpoints) is tested with the commit blocked or mocked.
15. Before running the suite, check for leftover test data (_MS Test*, ms.test.*); if found, STOP and report.
16. Root session rules (the Claude session runs as root over VS Code Remote):
   a. Run every bench, git, python, yarn and node command as rajerp:
      sudo -u rajerp -H bash -lc 'cd /home/rajerp/AgroPublic && <command>'
      Never run bench as root.
   b. After creating or editing any file under /home/rajerp/AgroPublic, run:
      chown -R rajerp:rajerp /home/rajerp/AgroPublic/apps/mobilesales
   c. Before every commit and at the end of every task: run
      find /home/rajerp/AgroPublic/apps/mobilesales -user root
      and it must print nothing.
   d. Never use sudo/supervisorctl for restarts — ask Raj.
   e. Never touch files outside apps/mobilesales, sites/agrosys.evonet.lk and sites/mstest.local.
      Exception: /tmp for temporary files (use new, unique names; delete them when done).
17. Host pages and APIs must be tested as logged-in users of every relevant role, not only as guest.
    For www pages that means the full render (frappe.website.serve.get_response: context AND template),
    not just get_context(); the v0.5.0 host page passed its get_context test but returned 500 for a
    logged-in agent with an open trip (tojson cannot encode dates).
18. The SPA must have a mount test: vitest + jsdom (or happy-dom), mounting App with a realistic ms_boot (agent
    with open trip, agent without trip, non-agent) and every route rendered once. The build fails if any route
    throws. (frontend/tests/mount.test.js; `yarn build` runs `vitest run` first. v0.5.0 shipped a blank screen:
    templates called __() which www pages do not define — register helpers on app.config.globalProperties.)

19. Any commit that changes a DocType schema, or code that reads new fields, is followed IMMEDIATELY by
    `bench --site mstest.local migrate` and `bench --site agrosys.evonet.lk migrate` (same task, before any further
    code change). apps/mobilesales is the live code: gunicorn recycles workers (--max-requests) and they import the
    new files from disk. If the agrosys migrate cannot run, revert the working tree to the last migrated commit
    (git stash / worktree) — never leave agrosys running code ahead of its schema.

20. Phase work (from Phase 7): a feature branch in a /tmp worktree
    (`git worktree add -b feat/<name> /tmp/ms_pN origin/develop`). Tests run the worktree code on mstest.local:
    `PYTHONPATH=/tmp/ms_pN bench --site mstest.local clear-cache` (after a hooks change), then
    `PYTHONPATH=/tmp/ms_pN bench --site mstest.local run-tests --app mobilesales`; a schema change is migrated the same
    way on mstest.local only. apps/mobilesales and agrosys change only at release (fresh clone, migrate). A release
    that adds hook functions (doc_events, permission hooks, scheduler) needs Raj's restart straight after the
    agrosys migrate: old workers resolve the new hook names against modules already in memory.
21. Commit-only checks (real threads, races, install / uninstall) run on a disposable site (mst2.local) through
    mobilesales/perf/*, never in the rollback suite and never on agrosys. mobilesales/perf/seed.py is the
    performance volume (own company "_MS Perf Co"); restore mstest.local from its pre-seed backup afterwards.

## Definition of done for EVERY task
1. `bench --site mstest.local migrate` and `bench --site agrosys.evonet.lk migrate` both pass.
2. Tests on mstest.local only: rule 15 leftover check, then `bench --site mstest.local run-tests --app mobilesales`
   (with PYTHONPATH to the worktree during a phase, rule 20).
   Never run-tests on agrosys.evonet.lk.
3. Fixture-type record changed → `bench --site agrosys.evonet.lk export-fixtures --app mobilesales`.
4. Frontend changed → `cd frontend && yarn build` (runs the SPA mount test first, rule 18; never skip it).
5. Core baseline check (rule 1); only mobilesales files changed; rule 16c find prints nothing.
6. Commit (Conventional Commits) and `git push origin develop`.
7. If Python/hooks changed, tell Raj a restart is needed.
8. Report: what changed, files, test result, commit hash.

## Phase release (end of each phase)
1. Backup agrosys.evonet.lk.
2. mv apps/mobilesales ~/mobilesales.local.bak ;
   git clone -b develop git@github-mobilesales:kumuduraj/mobilesales.git apps/mobilesales ;
   ./env/bin/pip install -e apps/mobilesales ; build; migrate + tests on mstest.local;
   migrate + smoke on agrosys.evonet.lk. On failure restore the local folder, fix, push, repeat.
3. Smoke test on agrosys (drafts + rollback): standard SO → DN → SI → PE on Finished Goods - ARL;
   one SLMFC Stock Entry; one deliveryplan Trip Sheet. Anything needing real submitted documents on
   agrosys → propose a mini live run and wait for Raj's OK.
4. Set mobilesales/__init__.py `__version__` to the release version (commit on develop).
5. Merge develop → main, tag v0.N.0, push main + tags — in a worktree, never in apps/mobilesales:
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
