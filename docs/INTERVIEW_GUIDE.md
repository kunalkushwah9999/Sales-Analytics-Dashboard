# Interview Guide — Sales Analytics Dashboard

Numbers below come from the committed run (`python main.py`, seed 42). Re-check `docs/INSIGHTS.md` if you regenerate data.

## 0. Be upfront about the data (this builds trust)

The dataset is **synthetic**: `src/generate_data.py` simulates 3 years of Indian e-commerce orders and deliberately injects
real-world mess (duplicates, mixed date formats, missing prices, negative quantities, orphan keys).
Say it in one sentence: *"I generated a realistic dataset with injected quality issues so I could build and test the whole
pipeline end to end; the pipeline is dataset-agnostic and I can point it at Olist or Superstore with a small column mapping."*
Never present the revenue figures as a real company's results.

## 1. 60-second pitch

> "I built an end-to-end sales analytics project. A Python pipeline using Pandas and SQLAlchemy cleans and loads about
> 1.2 lakh raw order records into a MySQL star schema. I wrote SQL views using joins, CTEs and window functions for monthly
> revenue, retention and product ranking, and connected Power BI on top with DAX measures for YoY growth, average order
> value and regional trends. The analysis showed that the top three categories drive about 60% of revenue, that growth was
> ~23% then ~16% year over year, and that the top 20% of customers generate ~63% of revenue."

## 2. Architecture (draw this on the whiteboard)

```
generate_data.py → raw CSVs (dirty) → etl.py (Pandas: clean/transform) → MySQL star schema
                                                                   │
                       sql/views.sql (joins, CTEs, window functions) ┘
                                                                   │
                         Power BI (model + DAX + slicers) ← views / CSV exports
```
Star schema: `fact_orders` (118,214 rows) + `dim_customers` (60,000) + `dim_products` (64) + `dim_date` (1,096).

## 3. ETL questions

**What data-quality problems did you fix?** (from `etl_report.json`, 121,800 raw → 118,214 clean rows)
- 1,792 duplicate orders removed (kept first by `order_id`)
- 463 rows without a customer/product/order key dropped; 105 orphan keys (customer not in dimension) dropped
- 377 unparseable dates dropped; mixed `YYYY-MM-DD` / `DD-MM-YYYY` formats parsed
- 849 impossible quantities (≤ 0) dropped; 565 missing quantities imputed as 1
- 750 missing prices filled from the product list price; 1,365 invalid discounts (missing or > 80%) set to 0
- Casing/whitespace/synonyms standardised ("Cash on Delivery" → COD, "Home and Kitchen" → Home & Kitchen)

**Why drop some rows and impute others?** Keys and dates can't be guessed without inventing facts → drop.
Price has an authoritative source (product master) → impute. Quantity default of 1 is the most common value; I logged the count.

**How is the load idempotent?** Views dropped → tables dropped and recreated → bulk insert in 5,000-row chunks inside one
transaction. Re-running gives the same result.

**How would it scale to 100M rows?** Chunked reads, `LOAD DATA INFILE`/bulk loaders, partitioning by month, incremental loads
using `order_date > last_loaded`, orchestration with Airflow.

## 4. SQL questions

| Question | Where to show it |
|---|---|
| Window functions you used? | `LAG` (MoM/YoY), `AVG … ROWS BETWEEN` (moving avg), `RANK`/`PARTITION BY` (product rank), `NTILE(5)` (customer quintiles), `SUM() OVER ()` (share of total) |
| Why views? | One definition of "revenue" (completed orders) reused by Power BI and analysts |
| CTE vs subquery? | Readability; `vw_cohort_retention` uses a CTE for cohort size |
| How did you compute retention? | First-order month per customer → join back to orders → `months_since_first = month_idx − cohort_idx` → distinct active customers ÷ cohort size |
| Why a `month_idx` column? | `year*12+month` makes month arithmetic portable and index-friendly (no date functions) |
| WHERE vs HAVING? | `WHERE` filters rows before grouping (status), `HAVING` filters groups (e.g. ≥ 3 orders) |
| Index choices? | `order_date`, `customer_id`, `product_id`, `order_month`, `order_status` — the join / filter columns |

Practice by explaining `sql/analysis_queries.sql` Q2, Q6 and Q7 out loud.

## 5. Power BI / DAX questions

- **Star schema, why?** Small dimensions filter one big fact table → fast, simple DAX, correct totals.
- **Filter context vs row context; what does `CALCULATE` do?** It modifies filter context. Revenue measures use
  `CALCULATE(SUM(...), order_status = "Completed")`. Context transition: a measure inside `FILTER(VALUES(customer), [Total Orders] >= 2)`.
- **How is YoY computed?** `SAMEPERIODLASTYEAR` over a marked date table; divide with `DIVIDE` to avoid divide-by-zero.
- **Measure vs calculated column?** Measures evaluate at query time with filters; columns are stored per row. Revenue is a measure.
- **`ALL` vs `ALLSELECTED`?** `ALLSELECTED` respects slicers, so category share changes when the user filters Year.
- **Import vs DirectQuery?** Import: fast, snapshot; DirectQuery: live but slower, limited DAX. I used Import.
- **Performance tips:** remove unused columns, star schema, avoid bi-directional filters, disable auto date/time.

## 6. Business-insight questions (numbers to remember)

| Insight | Value |
|---|---|
| Total revenue (completed) | ₹40.45 Cr · 104,285 orders · AOV ₹3,879 |
| Growth | 2023 ₹11.08 Cr → 2024 ₹13.61 Cr (**+22.8%**) → 2025 ₹15.77 Cr (**+15.9%**) |
| Top 3 categories | Electronics 27.0% + Home & Kitchen 17.7% + Furniture 15.2% = **59.9%** |
| Customers | 63.9% repeat buyers; top 20% of customers = 63.1% of revenue |
| Seasonality | Peak in Oct (festive season) — best month 2025-10, ₹1.79 Cr |
| Retention | ~11% of a cohort buys again in month +1 |

**"So what? What would you recommend?"**
1. Protect and grow the three anchor categories (stock availability, bundles), but fix concentration risk by lifting Fashion/Sports.
2. Prepare inventory and marketing 4–6 weeks before October.
3. Target the 11% month-1 retention with post-purchase campaigns, and nurture the top-quintile customers.

## 7. "What would you improve?"

- Replace simulated data with a public dataset (Olist, Superstore) and compare results.
- Add Airflow/cron scheduling, data-quality tests (Great Expectations), incremental loads.
- Add forecasting (Prophet/ARIMA), RFM segmentation and a churn model.
- Row-level security in Power BI for regional managers.

## 8. Swapping in a real dataset (30 minutes)

1. Put the CSVs in `data/raw/` as `customers_raw.csv`, `products_raw.csv`, `orders_raw.csv` (or edit `extract()`).
2. Map your column names in `clean_customers`, `clean_products`, `clean_orders` (`src/etl.py`).
3. Update `CATEGORY_MAP` / `PAYMENT_MAP` / `STATUS_MAP` and `START_DATE` / `END_DATE` in `src/config.py`.
4. `python main.py` — views, exports, insights and charts regenerate automatically.
