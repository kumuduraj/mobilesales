# Deferred after v1.0.0

Items agreed to come after v1.0.0, each with the reason and what is already in place.

## 1. Android ESC/POS print hand-off

Bluetooth printing on the van's 4-inch printer through the Evonet Android print service (`lk.evonet.escposprint`).

- **Now:** the phone prints through the browser print view (Print Bill / Invoice / Return Note / Receipt / Print All).
- **Ready:** `get_receipt_escpos(doctype, name, width)` returns the plain-text receipt lines for the agent's own
  mobile Sales Invoices and Payment Entries.
- **To do:** an intent / deep link from the SPA to the service, receipt lines for the Visit Bill and Return Note,
  paper-width setting per agent or vehicle, a printer test page.

## 2. Offline mode

- **Now:** the app shell is cached (PWA); every API call needs the network. Offline, the app shows a banner and
  blocks every submit. `client_ref` makes every visit submit idempotent, so a retry never records twice.
- **To do:**
  - cache the item master, prices and route customers
  - IndexedDB queue of visits keyed by `client_ref`, synced in order when back online
  - server re-validates stock, price and credit on sync, and the phone shows refused visits (Mobile Visit
    Rejection already logs them)
  - conflict rules for customer updates
  - a limit on how long a phone may stay offline

## 3. GPS tracking

- **Now:** each visit records latitude / longitude at check-in (optionally required); the Day Report links each
  visit to the map.
- **To do:** a background location trail during the trip (battery and privacy rules agreed with staff), a map of
  the day's route against the visits, and alerts for long stops or off-route driving.

## 4. Separate development bench

- **Now:** development tests run on `mstest.local` on the live AgroPublic bench (same code folder as the live
  site; see CLAUDE.md rules 11–19). Releases swap a fresh clone into `apps/mobilesales`.
- **To do:** its own bench (own supervisor group and ports) for development and upgrade trials, so a code change
  never touches the folder the live site runs from. The v1.0.0 upgrade check (ERPNext version-16 head) used a
  throwaway bench in /tmp; see [PERFORMANCE.md](PERFORMANCE.md) and the CHANGELOG.

## 5. Cheque collections

- **Now:** collections are cash only (Mode of Payment = the agent's cash). The settlement has a cheque table for
  the cashier's notes, but cheques don't post separately.
- **To do:** a cheque mode on the collection step (cheque no., date, bank) posting a Payment Entry to a
  "cheques in hand" account; settlement counts cheques apart from cash; post-dated cheques and bounced-cheque
  reversal.

## 6. Salary deduction of agent shortages

- **Now (decision 2026-11-03):** shortages are written off by default. With *Recover shortage from agent* on,
  they post to the employee recovery account against the agent's Employee.
- **To do:** HRMS isn't installed on agrosys. When it is, turn the recovery balance into salary deductions
  (Additional Salary / loan), with the supervisor's approval per settlement.

## 7. Van returns against invoices delivered with a Delivery Note

- **Now (decision 2026-11-03):** an invoice made from a Delivery Note (SO → DN → SI, `update_stock` off) moved no stock
  itself, so ERPNext doesn't accept a stock credit note against it. The van's return pickers leave such invoices out,
  and a return against one is refused with "delivered with a Delivery Note; return these goods at the office". The
  office takes the return in Desk (Delivery Note return, then its credit note).
- **To do:** take these returns from the van too, by creating a Delivery Note return into the customer return
  warehouse and the credit note against the invoice, set off like other van returns and counted at settlement.

## 8. Outgoing email and real supervisor users (agrosys)

- **Now:** the 20:00 Day Report email is switched on in Mobile Sales Settings, but agrosys has no Email Account,
  so the job skips every evening (one log line, nothing queued). The only supervisor user is the disabled pilot
  user.
- **To do (admin, no code):** set up an outgoing Email Account (Default Outgoing), create the real supervisor
  user(s) with the Mobile Sales Supervisor role, then check the first evening's email (ADMIN_GUIDE.md §7).

## 9. Repost after a settlement with returns and damage

- **Now (found 2026-11-03, docs/PERFORMANCE.md §3):** a settlement posts its return Stock Entry and its damage Stock
  Entry from the van at the same posting time. When both carry the same item, ERPNext counts the second as back-dated
  (a stock posting at the same moment already exists) and queues a Repost Item Valuation for that item and van. On the
  seed that was about 6 per day for 10 vans. Each is small (the van has no later postings that evening) and the
  scheduler runs it within the hour. Valuation is correct after the repost.
- **To do:** post both movements in one Stock Entry (one row per target warehouse), or give the damage entry its own
  posting second, so the settlement queues no repost at all.

## 10. Reading whole histories (performance, docs/PERFORMANCE.md §4)

- **Now (measured 2026-11-03):** every target is met at 10 agents × 60 days by the median. Three things read history
  and are slow only when the rows are not in the database cache (MariaDB's 128 MB default on this server):
  - the settlement's last check sums the agent cash account's whole GL history (0.4–1.2 s cold at 60 days; 3–7 s
    estimated cold after a year);
  - Salesperson Performance and Daily Trip Summary build every trip's full summary (4.6–4.7 s median for 600 trips,
    worst 6.7 s cold);
  - ERPNext's own FIFO batch pick sums every batch entry of the item in the warehouse (core, not changed).
- **Decided for v1.1 (Raj, 2026-11-04):**
  - The settlement cash check becomes bounded: the agent cash account's balance is summed from the last settlement
    that left it at zero, not over the whole history. Our code only; no new index on an ERPNext table.
  - Each trip's summary figures are stored on the trip at settlement (and cleared on cancel); Salesperson Performance
    and Daily Trip Summary read those rows instead of rebuilding every trip's summary.
  - `innodb_buffer_pool_size`: the server owner raises it (2 GB recommended, ADMIN_GUIDE.md §9). Not app work.
  - The ERPNext FIFO batch sum stays (core).
