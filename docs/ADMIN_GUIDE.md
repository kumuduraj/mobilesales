# Mobile Sales — Administrator guide

For the person who installs, configures and looks after the Mobile Sales app (`mobilesales`) on an ERPNext
v16 site. Day-to-day use: [QUICK_START.md](QUICK_START.md), [USER_GUIDE_AGENT.md](USER_GUIDE_AGENT.md),
[USER_GUIDE_STORE_CASHIER.md](USER_GUIDE_STORE_CASHIER.md). The full design is in [SPEC.md](SPEC.md).

## 1. What the app does

A van goes out with stock and an agent (and optionally a helper). The agent visits customers with a phone,
sells from the van, collects cash and takes returns. In the evening the store keeper counts the van, the
cashier counts the cash, and the settlement posts every difference. In ERPNext terms:

| Step | Document | ERPNext postings |
|------|----------|------------------|
| Load the van | **Mobile Trip** (submit) | Stock Entry store → van; Journal Entry for the opening cash float |
| Top-up | Top-up Load button | another Stock Entry store → van |
| Each stop | **Customer Visit** (from the phone) | Sales Invoice (`update_stock`, from the van), Payment Entry to the agent's cash account, credit notes into the customer-return warehouse, a set-off Journal Entry |
| Evening | **Mobile Settlement** (workflow) | Stock Entries for returned / damaged / missing stock, Journal Entries for cash handed over and any cash difference |

Standard ERPNext documents (Sales Order → Delivery Note → Sales Invoice, Payment Entry, Stock Entry) keep working
unchanged. The app only blocks standard documents that touch a van warehouse or an agent's cash account
outside its own flow.

## 2. Install

Requirements: Frappe / ERPNext version 16 (tested on Frappe v16.32.0, ERPNext v16.33.0), Python 3.14 bench.
`pyproject.toml` allows `erpnext >= 16.0.0, < 17.0.0`.

On a bench with `restart_supervisor_on_update` (like AgroPublic), `bench get-app` would try to restart supervisor
itself, so install by hand:

```bash
cd /home/rajerp/AgroPublic
git clone -b main git@github-mobilesales:kumuduraj/mobilesales.git apps/mobilesales
./env/bin/pip install -e apps/mobilesales
# add "mobilesales" on its own line to sites/apps.txt (keep the trailing newline: check with cat -A)
bench build --app mobilesales
bench --site <site> install-app mobilesales
```

Ask the server administrator to restart **right after** `install-app`. Until the restart, the old web workers
don't know the new app and every page returns 500.

```bash
sudo supervisorctl restart AgroPublic-web: AgroPublic-workers:
```

Never restart all supervisor groups: other benches run on the same server.

`install-app` creates the four roles, custom fields on Sales Invoice / Payment Entry / Stock Entry / Journal Entry,
the settlement workflow, print formats, the **Mobile Sales** workspace, default no-sale and return reasons,
the `MB-SINV-` and `MB-SRET-` Sales Invoice series (the default series stays the default), and the role
permissions agents need on standard DocTypes.

### Updates

```bash
cd /home/rajerp/AgroPublic/apps/mobilesales && git pull
cd /home/rajerp/AgroPublic && bench build --app mobilesales && bench --site <site> migrate
```

Then ask for the restart. If the update adds DocType fields, run `migrate` straight after the pull.
Web workers recycle by themselves and load new code from disk, so new code must never run against an old schema.

### Uninstall

`bench --site <site> uninstall-app mobilesales` removes:
- the app's DocTypes, custom fields, print formats, workspace, desktop icon and the settlement workflow;
- the agents' User Permissions;
- the Mobile Sales role rules on the 14 standard DocTypes. Where the remaining rules are exactly ERPNext's standard
  ones, the copy is deleted too, so the standard permissions apply again. A copy someone has changed since is kept,
  and named in the output.

The four Mobile Sales roles stay (unassign them if you like). Submitted Sales Invoices, Payment Entries, Stock
Entries and Journal Entries stay too, as standard documents with their ledgers. Back up the site first. The check
that was run is in §11.

## 3. Setup checklist

Do these once, in order. Each line names the screen.

1. **Warehouses** (Stock → Warehouse):
   - a group warehouse for vans, e.g. `Mobile Vans - ARL`
   - `Damaged Returns - ARL`
   - `Customer Returns - ARL`: a leaf, **not** under the van group
2. **Accounts** (Accounting → Chart of Accounts):
   - a group under Cash In Hand for agents' cash, e.g. `Cash In Hand - Agents`
   - an expense account for cash shortages, e.g. `5227 - Mobile Cash Shortage`
   - the stock shortage account can be the company's Stock Adjustment account
3. **Sales Person**: a group, e.g. `Mobile Sales Team`.
4. **Mobile Sales Settings** (§4). Fill in every field in the Accounts and Warehouses sections.
5. **Stock Settings**:
   - *Allow Negative Stock* off
   - FIFO valuation
   - "auto create serial and batch bundle for outward" on
   - "Enable Serial / Batch No for Item" on, if you have batch items
6. **Item Prices**: every item the vans carry needs a price in the agents' selling price list, valid on the
   trip date. A visit refuses an item without a price; it never sells at 0.
7. **Mobile Vehicle** for each van, then **Create Van Warehouse** on it.
8. **Users and agents** (§5).
9. **Mobile Route** for each route, with its customers in visiting order (see *Route order* below).
10. **Outgoing email and a real supervisor user**, for the 20:00 Day Report email (§7). Until both exist, the
    email is skipped every evening (one log line, nothing queued).
11. A first **mini live run**: one trip, two visits, settle it (§6).

## 4. Mobile Sales Settings

| Field | What to set |
|-------|-------------|
| Company | The selling company |
| Selling Price List | Default for agents (an agent can have their own) |
| Sales Invoice series / Return series | `MB-SINV-.YY.-.#####` / `MB-SRET-.YY.-.#####` |
| Default Tax Template | Taxes applied to mobile invoices and credit notes (optional) |
| Source Warehouse | The store the vans are loaded from |
| Return Warehouse | Where unsold stock goes at settlement (usually the source) |
| Damage Warehouse | Quarantine for stock damaged in the van |
| Van Warehouse Group | The group from step 1. **Every** leaf under it is treated as a van |
| Agent Cash Parent Account | The group from step 2; agent cash accounts are created under it |
| Main Cash Account | The cashier's account that receives the hand-over |
| Stock Shortage Account / Cash Shortage Account | Where missing stock and cash differences are written off |
| Employee Recovery Account + Recover shortage from agent | Only if shortages are charged to the agent's Employee (needs Employee on the agent). Default: write off |
| Shortage Tolerance Value | A settlement whose total difference (cash + stock value) is above this needs a supervisor's approval |
| Sales Person Parent | The group from step 3 |
| Default Customer Group / Territory | Defaults for customers created on the phone |
| Returns enabled + Customer Return Warehouse | Customer returns from the van |
| Allow credit sales | Off = every sale is paid in full; on = up to the agent's credit limit per invoice |
| Apply customer updates directly | Off = name / phone / address changes from the phone wait for a supervisor |
| Require geolocation | Blocks a visit without GPS |
| Daily Report Email | The 20:00 email of the day's Day Reports to supervisors (§7) |

agrosys today: returns on, daily email on (skipped until outgoing email exists), recover-from-agent off,
tolerance 0.

## 5. Users, roles, agents

| Role | Who | Can |
|------|-----|-----|
| Mobile Sales Agent | Van salesperson | Phone app only: own trips, visits, invoices, settlement draft. Never other agents' or office data |
| Mobile Sales Store Keeper | Store | Create and load trips, top-up, verify the stock count |
| Mobile Sales Cashier | Cashier | Verify the cash count (this submits the settlement) |
| Mobile Sales Supervisor | Sales manager | Everything above; cancel visits, settlements and trips, approve variances and customer updates, all reports |

An agent's user should have **only** the Mobile Sales Agent role. If the same person also has an accounts or
sales role, they see those documents as that role allows.

New agent:
1. Create the User (email, name), role **Mobile Sales Agent**.
2. **Mobile Sales Agent**: user, name, default vehicle, default route, selling price list, *max discount %*
   (cap of all the agent's manual discounts against the price-list value), *credit limit per invoice* (0 = cash
   only), *max return value per visit* (0 = a supervisor must take every return), Employee (only for recovery).
3. Press **Create Cash Account**. This creates the agent's cash account, mode of payment and sales person, and is
   safe to press again.
4. The agent signs in on the phone at `https://<site>/mobile-sales` and adds it to the home screen.

New vehicle: **Mobile Vehicle** (vehicle no., description, default driver), then **Create Van Warehouse**. An
inactive vehicle can't start trips. One open trip per vehicle and per agent.

## 6. The daily process

```
Store keeper           Agent (phone)                    Store keeper    Cashier          Supervisor
Mobile Trip → Submit → Start Trip → visits → End Day →  Verify Stock →  Verify Cash  →  (Approve if over tolerance)
(Loaded)               (In Field)          (Settling)   (Pending Store)  (Pending Cashier) → Settled
```

1. **Morning, store keeper:** new Mobile Trip (agent, vehicle, route, optional helper and opening cash float,
   load items), Submit. The van must be empty (the previous trip settled).
2. **Agent:** Start Trip, visits, End Day, settlement counts, Submit for Verification.
3. **Store keeper:** Mobile Settlement → check the returned / damaged counts → **Verify Stock** (or Reject back
   to the agent).
4. **Cashier:** count the cash (denominations) → **Verify Cash**. Within tolerance this approves and posts
   everything; above it the settlement goes to **Pending Approval**.
5. **Supervisor:** approve variances; the Day Report PDF is attached to the settlement on approval.

Customer updates (name, phone, address) entered on the phone wait in the visit as *Pending Approval*, unless
"apply directly" is on. The supervisor opens the visit and uses **Approve Customer Update** /
**Reject Customer Update**.

**Name changes always need approval.** A new customer name waits for the supervisor even when *Apply Customer
Updates Directly* is on (the name is what invoices and reports carry); the other fields (mobile, email, address,
contact) still follow that setting. The phone shows *"Name change pending: <new name>"* on the customer until it
is approved or rejected. To let names change directly too, tick **Allow Direct Name Change** in Mobile Sales
Settings (off by default).

### Vehicle → van warehouse → trip load

Each van is one **Mobile Vehicle**, and each vehicle has its own stock location, the **van warehouse**:

1. Mobile Vehicle `VAN-01` → **Create Van Warehouse** makes `VAN-01 Van - ARL` under the van group
   (`Mobile Vans - ARL`). Nothing else may post stock into it: SLMFC, deliveryplan and office documents are refused
   there.
2. The agent's **Default Vehicle** (`VAN-01`) fills the trip's vehicle, and the trip takes that vehicle's van
   warehouse.
3. **Load:** the trip's Submit moves the load items from the **Source Warehouse** (Settings, e.g.
   `Finished Goods - ARL`) into `VAN-01 Van - ARL`, one Stock Entry tagged with the trip. Top-ups do the same during
   the day.
4. Visits sell from `VAN-01 Van - ARL`; the settlement returns what is left to the store (and damaged / missing
   stock to their accounts), so the van is empty again before the next trip can be loaded.

**Choosing a batch when loading** (optional). A load or top-up row of a batch item has a **Batch** field. Empty, the
oldest batches are taken (FIFO), as before. To send a particular batch, pick it: the list shows only that item's
enabled, unexpired batches with stock in the source warehouse, oldest first, as *"<batch> · 12 Kg available · exp
<date> · mfg <date>"*. The same item may be on several rows with different batches. Each batch's rows together
may not need more than that batch holds (*"Batch … : 5 Kg available …, the rows choosing it need 6"*), and an
expired batch is refused. *Available at source* shows the batch's quantity when a batch is chosen. Rows without a
batch of the same item take the oldest of what the chosen rows leave. Sales from the van stay FIFO among the van's
batches; the settlement returns oldest first, as before.

### Route order

A route has **one order**, the same in Desk, on the phone and in the reports: by **Sequence**, numbered 1, 2, 3…
on every save (equal numbers keep their row order; rows without a number go to the end). To reorder, either type
the new numbers and save, or drag rows in the table (the drag renumbers them) and save. New customers created on
the phone go to the end of the route they were added to. Agents may visit in any order; **Route Coverage** marks
the visits made out of sequence and counts them per trip.

## 7. Reports, workspace, Day Report email

Workspace **Mobile Sales**: shortcuts, number cards, charts, and the reports Salesperson Performance, Daily Trip
Summary, Customer Visit Register, No Sale Reason Analysis, Customer Stock Position, Route Coverage, Mobile Stock
Variance, Mobile Cash Variance, Outstanding by Agent, Customer Returns Register, Discount Report and the Mobile
Trip Day Report (also the A4 print on the settlement). Agents may run Customer Visit Register, Customer Stock
Position, Outstanding by Agent and the Day Report, always for their own trips only.

**20:00 email:** with *Daily Report Email* on, the scheduler mails the day's Day Reports to every enabled system
user with the Mobile Sales Supervisor role. It needs:

1. an **Email Account** with *Enable Outgoing* and *Default Outgoing* (Settings → Email Account), or a
   `mail_server` in the site config;
2. a **real supervisor user** (enabled, System User, with an email address). On agrosys the only supervisor is
   the disabled pilot user.

Until then the job runs, skips, and writes one line to the `mobilesales` log. Test it with **Send Now** on an
Email Queue entry after the first real evening.

## 8. Troubleshooting

| Symptom | Cause / fix |
|---------|-------------|
| Every page 500 right after an install or update | The restart hasn't happened yet: ask for `sudo supervisorctl restart AgroPublic-web: AgroPublic-workers:` |
| Phone: "Your user is not set up as a Mobile Sales Agent" | No Mobile Sales Agent with that user, or the role is missing |
| Phone: "No trip loaded" | No submitted trip for the agent today; the store keeper loads one |
| Trip submit: "Previous trip not settled: van … still holds stock" | Settle (or cancel) the earlier trip of that vehicle first |
| Visit: "… has no price in price list … on …" | Add or back-date the Item Price (valid from) |
| Visit: "Not enough … in van" | Another visit sold the last units first (the server always rechecks) |
| Return: "delivered with a Delivery Note; return these goods at the office" | That invoice was delivered through a Delivery Note. Take the return with a Delivery Note return in Desk |
| Settlement: "Variance is above the tolerance" | A supervisor must approve it (Pending Approval) |
| Settlement post-condition failed (van not empty / batch left / agent cash not 0) | Counts don't match the ledger; Reject to Draft and recount |
| A standard Sales Invoice / Stock Entry is refused because of a van warehouse | Van warehouses are only for mobile trips; use the store |
| `mobilesales: standard permissions changed for <DocType>` in the migrate output or Error Log | ERPNext changed its standard permissions in an upgrade. The app copied them into Custom DocPerm when it was installed, so review that DocType in Role Permission Manager (§10) |
| Phone: "Too many requests. Wait a minute and try again." | The per-user limit on pricing / submit / uploads (far above normal use) was hit, usually by a stuck script or a stuck button |
| A website page fails but nothing is in the Error Log | Website render errors aren't logged there; open the page while logged in and read the traceback |
| `.webmanifest` served as application/octet-stream | nginx MIME map; add `application/manifest+json webmanifest;` |
| A Mobile Sales report shows "generating" / opens as a Prepared Report | Frappe switches a report to Prepared Report by itself after one run over 15 s. Untick *Prepared Report* on the Report record; see PERFORMANCE.md §4 for what makes a run slow |

Restart rules: this bench restarts only with
`sudo supervisorctl restart AgroPublic-web: AgroPublic-workers:` (server administrator), never `bench restart`.
Ask for one after: installing / uninstalling the app, a change to `hooks.py` (new document events, permission
hooks, scheduler), or an update that adds Python files used by document events.

## 9. Backups and test site

Back up before every update: `bench --site <site> backup --with-files`. All automated tests run on
`mstest.local` (same bench, its own company); never run `run-tests` on the live site.

Database cache: MariaDB on this server runs with the default `innodb_buffer_pool_size` of 128 MB, shared by every
site of every bench. Recommended: **2 GB** (the server has 16 GB). It's a server-wide setting for the server
administrator: set `innodb_buffer_pool_size = 2G` under `[mysqld]` in the MariaDB config so it survives a restart
(MariaDB 10.11 can also change it at run time with `SET GLOBAL innodb_buffer_pool_size = 2147483648`). Without it,
the first run of a large report reads its rows from disk (PERFORMANCE.md §4.2).

## 10. Upgrade safety (ERPNext / Frappe updates)

- The app gives its roles access to 14 standard DocTypes (Customer, Item, UOM, Price List, Item Price, Batch,
  Contact, Address, Territory, Customer Group, Sales Invoice, Payment Entry, Account, Serial and Batch Bundle).
  It does this by copying ERPNext's standard rules into Custom DocPerm and adding its own. After every upgrade,
  `migrate` compares the copies with the new standard rules and prints / logs any drift. It never changes them
  itself: review them in Role Permission Manager.
- Guards on standard documents exit after one cached lookup when a document touches nothing mobile
  (performance numbers: [PERFORMANCE.md](PERFORMANCE.md)).
- The app adds two secondary indexes to ERPNext tables (patch `mobilesales.patches.v1_0.add_core_lookup_indexes`,
  also run by install; dropped by uninstall). Without them these lookups scan the whole table:

  | Table | Column | Index | Serves |
  |---|---|---|---|
  | `tabSales Invoice Item` | `sales_invoice_item` | `ms_sales_invoice_item` | rows already returned against an invoice row (every return, van or office) |
  | `tabSerial and Batch Bundle` | `voucher_no` | `ms_voucher_no` | the batch bundles of a voucher (every batch line posted, returned or cancelled) |

  The patch skips an index when ERPNext already has one leading with the same column. Never add or drop them by hand.
  Details and measurements: [PERFORMANCE.md](PERFORMANCE.md).
- Run the full test suite on the test site after every ERPNext update, before updating the live site.

## 11. Uninstall check

The v1.0.0 check, on a disposable site (`mobilesales/perf/install_check.py`):

1. Fresh install, then the setup checklist above through the same buttons and roles.
2. A full day: load, sale, return, shop closed, settlement through the workflow.
3. Standard SO → DN → SI → PE and stock entries, as an office user (Sales / Stock / Accounts roles).
4. The race tests (§12).
5. `uninstall-app`. After it:
   - no custom fields, DocTypes, workspace, workflow, User Permissions, role rules or permission copies are left
     (the four roles stay);
   - the office user's standard flow still works.

## 12. Concurrency (what the server guarantees)

Checked with real threads and separate database connections:

- **Last stock:** two phones selling the last units at the same moment: one visit is recorded, the other gets
  "Not enough … in van".
- **Same visit sent twice:** the same visit (`client_ref`) sent twice at once: one visit; the second answer is
  that same visit, marked as a duplicate.
- **Settlement started twice:** "start settlement" twice at once (double tap, or the app and Desk): one
  settlement.
