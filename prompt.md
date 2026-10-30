# Supplier Price Watch: the no-code version

Paste the instruction below into a **weekly scheduled task in Claude**, with your email (e.g. Gmail) and Google Drive connected.
Replace the bracketed parts with your own. No code, no install, no new system.

---

Weekly supplier price check for [Your business].

1. **Find this week's supplier invoices.** Search my email for invoices from the last 7 days
   (attachments named invoice / bill / receipt, or from these suppliers: [list them, optional]).
   Skip anything that isn't a supplier invoice (customer receipts, newsletters, statements).

2. **Read each invoice.** For every billed line note: supplier, invoice number, date, item description,
   product code if printed, unit, quantity and unit price before tax. Include fees and surcharges
   (delivery, fuel, handling) as lines. Skip subtotal, tax and total rows. Never guess a number:
   if a line can't be read clearly, list it under "Couldn't read".

3. **Compare with the price history.** Open the Google Sheet "[Supplier price history]"
   (create it if it doesn't exist, with columns: date, supplier, item, unit, unit price, quantity, invoice).
   For each line, find the last price for the same supplier, same item and same unit.
   Never compare different units or different suppliers.
   - Report a change when the unit price moved by 3% or more.
   - Report a fee or surcharge that appears for the first time from a supplier I already buy from.

4. **Update the sheet.** Add this week's lines. Skip invoices already in the sheet.

5. **Send me one short summary** (email to myself, or a message):
   - Each increase: supplier, item, old price → new price, % change, since when.
   - New charges.
   - Decreases, in one line.
   - Total extra paid on this week's invoices because of the increases.
   - For each supplier with increases, a short, polite draft asking what's behind the change
     and whether there's flexibility given our regular orders.

Rules: never pay, dispute or reply to a supplier on my behalf, and never send the drafts. I decide.
Don't copy personal details (phone numbers, bank details, ID numbers) into the sheet or the summary.
If there were no supplier invoices this week, send one line: "No supplier invoices this week."
