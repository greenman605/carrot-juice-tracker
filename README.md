# Carrot juice restock tracker — Saint-Hyacinthe

Tracks when Walmart and IGA in Saint-Hyacinthe restock carrot juice, brand by brand.
A scheduled task on a home PC checks every 3 hours and pushes the results here;
GitHub Pages serves the page: https://greenman605.github.io/carrot-juice-tracker/

Why not GitHub Actions? Walmart and IGA both block cloud servers (Walmart answers
HTTP 429, IGA HTTP 403 from GitHub's runners), while the same requests work from a home
connection.

| Store | How stock is read |
|---|---|
| Walmart Supercentre #3137, 5950 rue Martineau | Set as default pickup store, then the product-page stock data: status plus the quantity Walmart will sell online from that store |
| IGA extra Sogesco, 3000 boul. Laframboise | Set as selected store, then each product page's "not available at the selected store" notice |
| IGA Laurier Ouest, 5445 rue Laurier Ouest | Same as above |
| IGA Saint-Charles, 2260 rue Saint-Charles | No online ordering, so IGA publishes no stock. Shown on the page, not tracked |

**Restock** = a product goes from out of stock to in stock between two checks.
**Top-up** (Walmart only) = the quantity jumps by 3 or more without selling out first.

## Use it

- **Hosted:** https://greenman605.github.io/carrot-juice-tracker/
- **Check now:** double-click `run_local.bat` (checks, pushes to GitHub, opens the page), or
  `run_local.bat view` to just open the local copy.
- **Schedule:** `schedule_task.ps1` registers the Windows task *Carrot juice tracker*
  (every 3 hours while you're logged in; a missed check runs when the PC wakes).
  Remove it with `schedule_task.ps1 -Remove`. Output: `logs\tracker.log`.

## Files

- `config.json` — stores, search terms, brand names, check interval.
- `tracker/` — the checker (`python -m tracker`, plus `--only walmart|iga`, `--publish`
  to pull/commit/push, `--log FILE`).
- `docs/index.html` — the page. `docs/data/state.json` holds current status and every change;
  `state.js` is the same data, so the page also works when opened from disk.
- `schedule_task.ps1` — installs the 3-hour Windows scheduled task.

## Adding a product or store

New carrot juice products are picked up automatically from each store's search.
To add a store, add it to `config.json`: for Walmart you need the store number and postal
code; for IGA, the store's `Id` from
`https://commerce.iga.net/api/fr/Store/get?bannerMaxWidth=100&bannerMaxHeight=100&Longitude=-72.957&Latitude=45.630&max=10`.

## If it stops working

Each store card on the page shows whether its last check worked. Common causes:

- **Walmart changed its site build.** The checker re-reads its query ids from walmart.ca
  automatically and saves them to `tracker/walmart_ops.json`.
- **Blocked by bot protection.** The checks are deliberately slow (one request every few
  seconds, every 3 hours). If the home connection ever gets blocked too, wait a day before
  retrying rather than checking more often.
- **Page not updating.** Look at `logs\tracker.log`; a failed push is retried on the next run.
- **IGA moved its online grocery.** IGA's new site is iga.ca; this uses the store-selection
  and product pages still served at commerce.iga.net.
