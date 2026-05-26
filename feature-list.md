# Guriaphoto Kodak — App Feature List

Derived from analysis of the current `Kodak.xlsx` workbook. This document maps every function of the existing spreadsheet to proposed features for the lightweight replacement app, plus a few improvements the spreadsheet format makes hard.

## 1. How the current Excel works (quick recap)

The workbook has 17 sheets:

- **ანგარიში** — the master settings sheet: year, price list, salary register for Mamuka / Khatuna / Archil, and 12 monthly stock-movement blocks.
- **12 month sheets** (იანვარი … დეკემბერი) — identical templates, each holding 30 days × 30 transaction rows. Every day has a date header, ~30 transaction rows, a daily totals row, and a daily cash-reconciliation row. The whole month ends with a monthly summary + salary calculation block.
- **ყველა ნისია** — the master credit (ნისია) ledger; every unpaid balance from the month sheets flows here.
- **აქტიური ნისიები** — currently outstanding credits.
- **მოტანილი ნისიები** — credits that customers have paid back (fully or partially).
- **თვეები - არ წაშალოთ** — a static lookup table mapping month names to numbers.

The heavy lifting is done by cross-sheet formulas: prices live in `ანგარიში`, monthly sheets multiply quantities by those prices, and the ledger sheets aggregate credits across all months. VLOOKUPs resolve outstanding balances when a customer brings cash back against an old debt.

## 2. Core domain model

The app will need these entities:

- **Transaction** (one per customer visit) — date, customer surname, line items, amount paid, notes.
- **Line items** per transaction, grouped by category:
  - Photo prints (ფოტო სურათი) — sizes 10x15, 13x18, 15x21, 18x24, 20x30, passport 3x4
  - Enlargements (გადიდება) — 10x15, 13x18, 15x21, 18x24, 20x30, other
  - Frames (ჩარჩო) — 9x13, 10x15, 13x18, 15x21, 18x24, 20x30, other
  - Lamination (ლამინირება) — 10x15, 13x18, 15x21, 20x30
  - CD, photocopy (ქსეროქსი), album, other
- **Credit (ნისია)** — an unpaid balance linked to a transaction, carrying code, date, surname, original amount, amount paid back so far, remaining.
- **Credit payment** — a cash-back event that reduces one credit's remaining balance.
- **Price list** — one price per product/size, year-scoped, editable.
- **Employee** — currently Mamuka, Khatuna, Archil (the owner; appears as "აჩიკო/არჩილი" inconsistently in the spreadsheet — same person). Mamuka has commission rules.
- **User / role** — a login identity with a role. Two roles: **admin** (Archil) and **employee** (Mamuka, Khatuna). Salary-related screens are admin-only.
- **Stock item** — frames, photo paper, lamination sheets, discs, letter paper, color cartridges, xerox cartridges, stickers, embossed paper.
- **Stock movement** — monthly: opening inventory, purchases, sales, closing inventory per item.
- **Cash withdrawal** — daily line: Mamuka takes X, Archil takes Y, the rest is ნაშთი (leftover).

## 3. Feature list

### 3.1 Daily transaction entry (replaces the month sheet's daily rows)

- One-screen data entry per visit: pick date, type customer surname, tap quantities for each product/size. Amount columns auto-fill from the price list — no manual multiplication.
- Running daily list grouped under a date header, matching the spreadsheet's "1 იან 2026" day block.
- Row-level total auto-calculates (Σ quantity × price), equivalent to column U (photos/enlargements/frames) + column AE (CD/copy/lamination/album/other).
- "Amount received" (`AF`) field per row. If less than the computed total, the difference becomes a credit automatically.
- Free-text notes field per row (`AS` column in the sheet).
- Quick-edit and delete for any row on the day.

### 3.2 Credit (ნისია) management

- Automatic credit creation whenever amount received < total owed. Generates the same style of code as Excel ("Surname -50ლ (date, #id)").
- **Active credits** screen: list of all outstanding nisias with surname, original amount, paid so far, remaining.
- **Record payment** flow: pick an active credit, enter amount brought, optionally pick date. Partial and full payments both supported (mirrors column G/H of `მოტანილი ნისიები`).
- Filter credits by month, by customer surname, and by status (outstanding / partially paid / cleared).
- Search by surname and by credit code.
- Credit history per customer: every original credit and every repayment.
- Visual flag on the day's row when a credit was created (red), when brought back (green) — the spreadsheet does this via conditional formatting.

### 3.3 Price list management

- Editable price table per product category and size (replaces the `ანგარიში` sheet price block).
- Price changes apply going forward without breaking past totals (historical transactions lock to the price in effect at that time).
- Bulk edit + import/export CSV for yearly price refreshes.

### 3.4 Daily cash reconciliation

- At the end of each day: enter how much Mamuka took, how much Archil took; app computes leftover (ნაშთი) = day total − withdrawals. Matches row 39 of each day block (`F39 = AQ35 − B39 − D39`).
- Running day-over-day cash balance.

### 3.5 Monthly summary dashboard

For any month, show the equivalent of row 1268 of each month sheet:

- Total units sold, broken down by every size and product category.
- Total revenue for the month, total credit issued, total credit recovered.
- Cash withdrawals by each employee across the month (current formula: `K1275`, `L1275`, `M1275`).
- End-of-month outstanding credit balance.

### 3.6 Salary calculation

- Mamuka's commission-based salary is computed from the month's activity, using tariffs stored in settings:
  - Photo prints: 5% of unit count (current tariff cell `I1272 = 0.05`)
  - Passport 3x4 (always passport photos): 30% (current `K1272 = 0.3`)
  - Enlargements: 20% (current `M1272 = 0.2`)
- Khatuna: manual monthly salary entry (fixed salary; spreadsheet column F on `ანგარიში`).
- "To be paid" vs "already withdrawn" (so Archil knows what's left to disburse at month end).
- Tariffs editable in settings.
- **Admin-only screen** — only Archil can open the salary view. Mamuka and Khatuna must not see salaries (their own or anyone else's).

### 3.7 Stock / inventory tracking

Replaces the right-hand block of `ანგარიში` (cols J–AF, which is one block per month × 12 months):

- Master list of stock items: frames (7 sizes), photo paper (7 sizes), lamination sheets (4 sizes), CDs, letter paper, color cartridges, xerox cartridges, stickers, embossed paper — same taxonomy as the current sheet.
- Per month per item: opening balance, purchases, sales (auto-pulled from transactions), closing balance.
- Sales should deduct from stock automatically based on transactions — the spreadsheet has to be updated manually, so this is a clear improvement.
- Low-stock alerts when an item drops below a threshold.
- Year-end consumption row (like `J54` "გახარჯულია წლის განმავლობაში").

### 3.8 Yearly view

- Annual roll-up of revenue, units sold by category, credits issued vs recovered, stock purchased vs consumed.
- Month-over-month trend chart (spreadsheet has nothing like this — net-new capability).

### 3.9 Customer directory (implicit upgrade)

The spreadsheet only stores surnames. Small upgrade:

- Keep a deduplicated list of surnames auto-built from transactions.
- Optionally add phone/note per customer (helpful for chasing nisias).
- Clicking a name shows their transaction and credit history.

### 3.10 Search and filter

- Search across all months by surname, by credit code, by date range, by product.
- Filter the day list by "had credit", "fully paid", "partially paid".

### 3.11 Settings

- Studio profile (name, year).
- Employees list (currently Mamuka / Khatuna / Archil; the spreadsheet hard-codes these in headers).
- Salary tariffs for Mamuka's commission.
- Price list (see 3.3).
- Stock item catalog.
- Credit-code format and default currency display.
- User accounts and role assignment (admin / employee).

### 3.12 Access control (admin vs employee)

- **Admin (Archil)** can see everything: all transactions, credits, stock, salaries, tariffs, settings, and all historical years.
- **Employee (Mamuka, Khatuna)** can see and use:
  - Daily transaction entry (3.1)
  - Credit creation and payment recording (3.2)
  - Daily cash reconciliation (3.4) — entering how much each person withdrew is fine
  - Customer/credit search (3.10)
- **Hidden from employees:**
  - Salary screen (3.6) and any salary totals
  - Price list editing (they can see prices on transactions but not change them)
  - Tariffs, user management, settings
  - Stock purchase costs (they can see quantities, not cost figures)
- Simple username + PIN/password login at app open. Role is tied to the user account.

### 3.13 Reliability / usability improvements over Excel

Worth calling out because these are where the spreadsheet is fragile:

- **No accidental formula breakage** — in Excel, deleting a row can corrupt the whole month's totals. The app decouples data from presentation.
- **Multi-device** — currently the owner is tied to the machine the file lives on; the app can work on phone or tablet at the counter.
- **Backups / history** — automatic, vs manual file copies.
- **No per-month sheet duplication** — one place to enter data, views filter by month/year.
- **Proper validation** — e.g. prevent entering a negative quantity, enforce date on each row.
- **Audit trail** — who entered/edited what and when.

### 3.14 Import / export

- **Import** from the existing `Kodak.xlsx` — migrate all years of historical data (all month sheets across all workbook files) plus all active credits. Past data must remain accessible in the app.
- **Export** any month or the full year to Excel or PDF in a layout that looks similar to the current sheet (for Archil's comfort and for printing).
- Printable daily receipt / end-of-day report.

## 4. Suggested priorities (MVP → v2)

**MVP (everything needed to stop using the Excel):**
1. Daily transaction entry with auto-pricing (3.1)
2. Credit creation + "record payment" (3.2)
3. Price list settings (3.3)
4. Daily cash reconciliation (3.4)
5. Monthly summary (3.5)
6. Login + admin/employee access control (3.12)
7. Import from existing Kodak.xlsx, including historical years (3.14 import)

**v1.1:**
8. Salary calculation, admin-only (3.6)
9. Stock tracking with auto-deduction (3.7)
10. Export to Excel / PDF (3.14 export)

**v2 polish:**
11. Yearly view & trends (3.8)
12. Customer directory with phone numbers (3.9)
13. Search & filters (3.10)
14. Audit trail (3.13)

## 5. Decisions confirmed with Archil

- **People:** Mamuka, Khatuna, and Archil are the team. "აჩიკო" and "არჩილი" in the Excel are both Archil — we'll normalize to **Archil** throughout the app.
- **Historical data:** all past years must be retained and browsable in the app, not just the current year.
- **3x4:** always passport photos — Mamuka's 30% passport commission applies to every 3x4 line.
- **Access control:** no need for complex multi-user collaboration, but two roles are required:
  - **Admin** — Archil. Full access including salaries and settings.
  - **Employee** — Mamuka and Khatuna. Can enter transactions and manage credits but must not see salary pages or cost data.
