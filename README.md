# Carrot juice restock tracker — Saint-Hyacinthe

Tracks when Walmart and IGA in Saint-Hyacinthe restock carrot juice, brand by brand.
A GitHub Action checks every 3 hours and publishes the results to GitHub Pages.

| Store | How stock is read |
|---|---|
| Walmart Supercentre #3137, 5950 rue Martineau | Set as default pickup store, then the product-page stock data: status plus the quantity Walmart will sell online from that store |
| IGA extra Sogesco, 3000 boul. Laframboise | Set as selected store, then each product page's "not available at the selected store" notice |
| IGA Laurier Ouest, 5445 rue Laurier Ouest | Same as above |
| IGA Saint-Charles, 2260 rue Saint-Charles | No online ordering, so IGA publishes no stock. Shown on the page, not tracked |

**Restock** = a product goes from out of stock to in stock between two checks.
**Top-up** (Walmart only) = the quantity jumps by 3 or more without selling out first.

## Use it

- **Hosted:** the GitHub Pages URL for this repo (Settings → Pages).
- **On this PC:** double-click `run_local.bat` to run a check and open the page, or
  `run_local.bat view` to just open it.
- **Check now on GitHub:** Actions → *Check carrot juice stock* → *Run workflow*.

## Files

- `config.json` — stores, search terms, brand names, check interval.
- `tracker/` — the checker (`python -m tracker`, or `--only walmart` / `--only iga`).
- `docs/index.html` — the page. `docs/data/state.json` holds current status and every change;
  `state.js` is the same data, so the page also works when opened from disk.
- `.github/workflows/check-stock.yml` — the 3-hour schedule.

## Adding a product or store

New carrot juice products are picked up automatically from each store's search.
To add a store, add it to `config.json`: for Walmart you need the store number and postal
code; for IGA, the store's `Id` from
`https://commerce.iga.net/api/fr/Store/get?bannerMaxWidth=100&bannerMaxHeight=100&Longitude=-72.957&Latitude=45.630&max=10`.

## If it stops working

Each store card on the page shows whether its last check worked. Common causes:

- **Walmart changed its site build.** The checker re-reads its query ids from walmart.ca
  automatically and saves them to `tracker/walmart_ops.json`.
- **Blocked by bot protection.** The checks are deliberately slow (one every few seconds,
  every 3 hours). If GitHub's servers get blocked but your PC does not, run the check
  from your PC with Task Scheduler instead (see `run_local.bat`) and push the data.
- **IGA moved its online grocery.** IGA's new site is iga.ca; this uses the store-selection
  and product pages still served at commerce.iga.net.
