# Mobile Sales — guide for van agents

Your phone app, step by step. You need a phone with a browser, internet and your ERP login.

## Before your first day

1. Open `https://agrosys.evonet.lk/mobile-sales` and sign in with your email and password.
2. Add it to your home screen: Chrome menu ⋮ → **Add to Home screen**. After that it opens like an app.
3. When the phone asks for **location**, allow it: each visit records where you were.

The app needs internet. The top right corner always shows the connection:

- green **Online**: the server answered in the last 30 seconds;
- amber **Reconnecting…**: a check is running after a failed call;
- red **Offline**: no connection to the server (also on a Wi-Fi that asks you to log in first, or with no data).
  You see *"No connection — you can look around, but nothing can be saved until you are back online"*. Wait for
  signal; nothing is lost and nothing is saved twice. When it comes back you see **Back online** and the screen
  refreshes.

**Your account / log out:** tap your name under *Mobile Sales*. The menu shows your name, email, agent code, the
vehicle of your open trip and the app version, and **Log out**. If a visit or the settlement has input not saved
yet, the dialog says so. Log out needs a connection. Always log out before someone else uses the phone; after log
out nothing of yours is left on it.

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

*Today's route* lists your customers in route order, numbered 1, 2, 3…. Under each name you see its address,
city and the last four digits of its mobile (*"No 1, Main Road, JA-ELA · …0002"*), so two shops with the same name
can't be mixed up, and its balance: **Outstanding** (what they owe) or, in green, **Credit** (credit they hold
from returns).

- **NEXT** (yellow) is the first customer due today you haven't visited yet; tap **Start visit**. After the visit,
  NEXT moves on.
- Visited customers show **✓** and the outcome (*Sale*, *No Sale*, …).
- You may visit in another order; nothing is blocked. NEXT stays on the first one you skipped. Your supervisor sees
  out-of-order visits in the Route Coverage report.
- **A customer not on your route:** type part of the name, mobile number, address or city in the search box, then
  **Visit**. The visit is marked **Off route**.
- **New customer**: name, mobile number, address and city; customer group and territory start with the usual
  values. You can tick **Add to route**. If a customer with the same mobile already exists, the app opens that one.

## 3. A visit

A visit has steps; **Next** and **Back** move between them.

1. **Check-in:** tap **Capture location**. A check-in photo of the shop is optional.
2. **Customer details:** if the name, phone, contact person, address, city or Tax ID changed, tick
   **Details changed — update them** and fill only what changed (*"Leave a field empty to keep the current
   value"*). Your supervisor may need to approve it first; a **new name always** waits for the supervisor, and
   the customer shows *"Name change pending: <new name>"* until then.
3. **Shelf stock:** count what the shop has of our items (**Add shelf item**): quantity, expiry and competitor
   item if you see one.
4. **Outcome:**
   - **Sale:** add items from your van (*Cart (from van stock)*). Each item shows its code, how much is in the van,
     its price and a picture if it has one. With many items, type part of the name or code in the search box;
     **In cart** shows only what you've added, **All van items** everything. Items you've added move to the top
     and show their line total (*2 × LKR 1,325.00 = LKR 2,650.00*). You may give a line discount (**Disc. type**
     % or Amount, then **Discount**) and an **Invoice discount**, but together only up to your limit (*Your
     discounts … up to …*). If you ask for more, the app says so.
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
| *Your session has ended — please log in again* | The app opens the login page by itself; sign in again (a visit not submitted must be entered again) |
| *Could not log out: the server cannot be reached* | Wait for **Online**, then log out again |
| The screen stays white / *App failed to load* | Close the app and open it again; if it keeps happening, tell the supervisor |
