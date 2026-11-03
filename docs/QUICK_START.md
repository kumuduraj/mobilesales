# Mobile Sales — daily routine on one page

| When | Store keeper (Desk) | Agent (phone `/mobile-sales`) | Cashier (Desk) | Supervisor (Desk) |
|------|---------------------|-------------------------------|----------------|-------------------|
| **Morning** | Mobile Trip → + Add → agent, vehicle, load items, opening float → **Submit** (van must be empty) | Today → check van stock → **Start Trip** | — | Check yesterday's settlements are all Settled |
| **Day** | Top-up: trip → **Top-up Load** | Route → customer → Check-in → details → shelf stock → Sale / No Sale / Shop Closed / Collection / Return → Collection → **Submit visit** → Print Bill | — | Approve / reject customer updates on Customer Visit; cancel a wrong visit (before settlement) |
| **Evening** | Settlement *Pending Store* → count the van → correct Returned / Damaged → **Verify Stock** (or Reject) | Today → **End Day** → Settlement → returned, damaged, cash count → **Submit for Verification** | Settlement *Pending Cashier* → count cash → **Verify Cash** (posts everything; above tolerance → Pending Approval) | *Pending Approval* → Approve; read the Day Report |
| **Any time** | Van Stock on the trip | History → reprint | Mobile Cash Variance report | Mobile Sales workspace: cards, charts, 12 reports |

**Rules of thumb**
- One open trip per agent and per vehicle; the van must be empty before loading.
- The phone needs internet to save. A retry never records a visit twice.
- No price in the price list = no sale; ask the office.
- Returns become credit for the customer (never cash paid out), set off against invoices.
- Reject sends a settlement back to the agent (Draft) and clears earlier verifications.
- Only a supervisor cancels visits, settlements and trips. A visit can't be cancelled once its trip is Settled.

More: [USER_GUIDE_AGENT.md](USER_GUIDE_AGENT.md) · [USER_GUIDE_STORE_CASHIER.md](USER_GUIDE_STORE_CASHIER.md) ·
[ADMIN_GUIDE.md](ADMIN_GUIDE.md)
