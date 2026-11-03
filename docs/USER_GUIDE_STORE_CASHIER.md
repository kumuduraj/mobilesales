# Mobile Sales — guide for store keepers and cashiers

You work in ERPNext Desk (a computer or tablet), workspace **Mobile Sales**. The agent works on the phone app.

## Store keeper

### Morning: load a van

1. **Mobile Sales → Mobile Trip → + Add**.
2. Fill in:
   - **Agent**: route and vehicle come from the agent; change them if needed.
   - **Helper**: optional.
   - **Opening cash float**: change you give the agent.
   - **Load items**: item and quantity. The unit defaults to the item's stock unit, and *available at source*
     shows what the store has.
3. **Save**, check the list, then **Submit**.

The app moves the stock from the store into the van (Stock Entry). Batch items are picked oldest batch first.
The trip shows **Loaded**, and the agent can now start it on the phone.

- *"Previous trip not settled: van … still holds stock"*: the vehicle's last trip isn't settled. Finish that
  settlement first.
- *"… already has an open trip"*: one open trip per agent and per vehicle.
- Not enough in the store: the submit is refused. Load less, or receive stock first.

**Top-up during the day:** open the trip → **Top-up Load** → items and quantities. Another transfer is made into
the van. **Van Stock** on the trip shows what the van holds now.

**Cancel a trip:** only while it is *Loaded* (no visits yet), and only a supervisor can do it. Everything goes
back to the store.

### Evening: verify the stock

When the agent has submitted the settlement, it waits in **Pending Store**:

1. **Mobile Sales → Mobile Settlement** → open the one *Pending Store* for that trip.
2. Count the van. The **Stock** table shows per item: **Issued** (load + top-ups), **Sold**, **Expected**, the
   van's ledger quantity, and what the agent entered as **Returned** and **Damaged**.
   *Missing* = expected − returned − damaged.
3. If your count differs, correct **Returned / Damaged** (and the damaged batch).
4. Check the **Customer returns** lines (goods customers gave back): *Credited Qty* on the credit notes, and what
   you received (**Received Qty**, **Damaged Qty**). The rest is *Missing*.
5. Use **Actions → Verify Stock**, or **Actions → Reject** to send it back to the agent (Draft) to recount.

## Cashier

When the store keeper has verified, the settlement waits in **Pending Cashier**:

1. Open it. **Expected cash** = opening float + cash collected (current and previous invoices).
2. Count the cash and fill in the **denominations** (or check the agent's count). Note any cheques.
3. **Variance** = counted − expected (negative = short).
4. Use **Actions → Verify Cash**:
   - Within the tolerance in Mobile Sales Settings, this **approves and submits** the settlement. The app posts:
     unsold stock back to the store, damaged stock to the damage warehouse, missing stock written off, the cash
     moved from the agent's account to the main cash account, and any cash difference written off (or charged
     to the agent if the company recovers shortages). The trip becomes **Settled**, and the Day Report PDF is
     attached to the settlement.
   - Above the tolerance, it goes to **Pending Approval** for a supervisor.
5. Or **Reject**: back to Draft, for the agent to recount. Earlier verifications are cleared.

After submission the app checks that the van is empty, every batch is 0 and the agent's cash account is 0. If
not, the submit is refused with *"Settlement post-condition failed"*. Reject and recount.

## Prints

- On the settlement: **Mobile Settlement Sheet** (A4, signature lines for agent, store keeper, cashier) and
  **Mobile Trip Day Report** (A4: visits, sales, collections, returns, stock, cash, sign-off).
- On a visit (Customer Visit): **Mobile Visit Bill**. On a Sales Invoice: **Mobile Invoice 4in** /
  **Mobile Return Note**. On a Payment Entry: **Mobile Collection Receipt**.

## Reports you can run

Daily Trip Summary, Mobile Stock Variance, Mobile Cash Variance, Customer Returns Register, Customer Visit
Register, Outstanding by Agent and the others in the Mobile Sales workspace, filtered by date, agent, vehicle,
route or territory.

## Good to know

- The van warehouses are for mobile trips only. A normal Stock Entry, Delivery Note or Sales Invoice on a van
  warehouse is refused; use the store warehouses as usual.
- Standard office sales (Sales Order → Delivery Note → Sales Invoice → Payment Entry) are not affected by the app.
- Customer returns taken in the van land in the **customer-return warehouse**. Good returns stay there until you
  move them back to the store with a normal Stock Entry.
