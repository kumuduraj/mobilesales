# Mobile Sales — guide for van agents

Your phone app, step by step. You need a phone with a browser, internet and your ERP login.

## Before your first day

1. Open `https://agrosys.evonet.lk/mobile-sales` and sign in with your email and password.
2. Add it to your home screen: Chrome menu ⋮ → **Add to Home screen**. After that it opens like an app.
3. When the phone asks for **location**, allow it: each visit records where you were.

The app needs internet. Without it you see *"No connection — you can look around, but nothing can be saved
until you are back online"*. Wait for signal, then try again; nothing is lost and nothing is saved twice.

The bottom bar has five screens: **Today**, **Route**, **Visit**, **History**, **Settlement**.

## 1. Morning — Today

- **No trip loaded:** the store keeper hasn't loaded your van yet. The screen says *"Ask the store keeper to
  load your van."* and shows your last trip (for example *"Last trip MTRIP-26-00005 · Settled · sales LKR
  4,536.00"*). Tap **Check again** once they've loaded it.
- **Trip loaded:** you see the trip number, date, route, vehicle and helper, and the **Van stock** (every item
  and batch in your van).
- Check the van stock against what is really in the van. If something is wrong, tell the store keeper before you
  leave.
- Tap **Start Trip**. Status: *In Field*. You can now record visits.

The **My day** card shows your visits (and how many were planned), sales, cash collected and returns. It updates
as you work.

## 2. Route

*Today's route* lists the planned customers in order, with their outstanding balance. A tick means you've visited
them today.

- Tap a customer to start a visit.
- A customer not on your route: use the search (name or mobile number). The visit is marked **Off route**.
- **New customer**: name, mobile number, address and city; customer group and territory start with the usual
  values. You can tick **Add to route**. If a customer with the same mobile already exists, the app opens that one.

## 3. A visit

A visit has steps; **Next** and **Back** move between them.

1. **Check-in:** tap **Capture location**. A check-in photo of the shop is optional.
2. **Customer details:** if the name, phone, contact person, address, city or Tax ID changed, tick
   **Details changed — update them** and fill only what changed (*"Leave a field empty to keep the current
   value"*). Your supervisor may need to approve it first.
3. **Shelf stock:** count what the shop has of our items (**Add shelf item**): quantity, expiry and competitor
   item if you see one.
4. **Outcome:**
   - **Sale:** add items from your van (*Cart (from van stock)*). The price comes from the price list. You may give
     a line discount (**Disc. %** or **Disc. amt**) and an **Invoice discount**, but together only up to your limit
     (*Your discounts … up to …*). If you ask for more, the app says so.
   - **No Sale:** choose the reason (some reasons need a remark).
   - **Shop Closed:** nothing else to fill.
   - **Collection Only:** only collect money owed.
   - **Return Only:** only take goods back.
5. **Returns** (step 4b, when the customer gives goods back):
   - Choose the **invoice** the goods were sold on (each shows its date, quantity, total and what is still owed).
     For items without batches you can choose **No invoice**.
   - Choose the item and quantity, the **Reason** and the **Condition** (*Resaleable* or *Damaged*), and add
     remarks if the reason asks for them.
   - Tap **+ Add return**. A return that isn't added is not saved; the app won't let you go on until you add it
     or tap **Clear**.
   - The return becomes **credit** for the customer. It's set off against today's invoice or older invoices
     first; *no cash is paid out*. Credit left over stays on the customer's account.
6. **Collection:** the app shows the invoice total, the return credit applied and **Cash to collect now**.
   You can also collect **Previous outstanding invoices** (oldest first). If the return credit covers everything,
   it says *"Return credit covers this invoice — nothing to collect."* Credit sales (collecting less than the
   total) are only possible when the office allows them, up to your limit.
7. **Review**, then **Submit visit**. A summary appears: check it, then **Confirm and submit**. After this you
   cannot change the visit.

After submitting you see **Visit saved** and the print buttons:

- **Print Bill**: the customer's bill for the visit (sales, returns, credit, cash paid, balance)
- **Print Invoice** / **Print Return Note** / **Receipt**
- **Print All**: everything on one page

Printing uses the phone's print screen (choose the printer there).

**Not enough in van:** another visit may have just sold the last units, or the van count is wrong. Change the
quantity or tell the store keeper.

**Double tap, or the network dropped while saving?** Tap Submit again. The app recognises the same visit and
never records it twice. If a supervisor cancelled that visit in the meantime, the app tells you to start a new
one.

## 4. History

Today's visits with their outcome and amounts. Open one to print its bill, invoice, return notes or receipt again.

## 5. Evening — End Day and Settlement

1. **Today → End Day** (confirm). No more visits after this. Ended too early? Use **Reopen Trip**, as long as you
   haven't submitted the settlement.
2. **Settlement:**
   - For each item, enter what you're giving back to the store: **Returned**, and **Damaged** (with the damaged
     batch, if you know it). *Expected* shows what the van should hold.
   - Customer returns: count what you're handing over from the customer-return stock.
   - Cash: enter the count of each note and coin (or the total). *Expected cash* = opening float + cash collected.
     The difference shows as **Variance**.
   - **Save** as often as you like.
3. **Submit for Verification.** If something is missing or the cash is short or over, the app warns you first
   (*"This is recorded against you. Continue?"*). After this the store keeper and cashier take it from there and
   you can't change it. If they find a mistake, they send it back to you (Draft) to recount.

## 6. If something goes wrong

| You see | Do this |
|---------|---------|
| *Your user is not set up as a Mobile Sales Agent* | Ask your supervisor |
| *Visits can only be recorded while the trip is In Field* | Tap **Start Trip** on Today (or Reopen Trip) |
| *… has no price in price list …* | Don't sell that item; call the office to add the price |
| *… delivered with a Delivery Note; return these goods at the office* | That invoice can't be returned from the van; the office takes it |
| *Too many requests. Wait a minute and try again.* | Wait a minute; if it keeps happening, tell the supervisor |
| The screen stays white / *App failed to load* | Close the app and open it again; if it keeps happening, tell the supervisor |
