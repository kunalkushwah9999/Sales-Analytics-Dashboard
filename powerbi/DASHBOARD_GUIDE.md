# Building the Power BI Dashboard (≈ 60–90 minutes)

Power BI Desktop is Windows-only. No Windows PC? Use the free **Power BI Service** (app.powerbi.com): upload the CSVs
from `powerbi/exports/` and build the same pages in the browser.

## Step 1 — Connect the data

**Option A: MySQL (best for the interview story)**
1. Home → Get data → **MySQL database** → server `localhost`, database `sales_analytics`.
2. Select: `dim_date`, `dim_customers`, `dim_products`, `fact_orders` and the views
   `vw_cohort_retention`, `vw_customer_summary`, `vw_category_revenue`, `vw_revenue_growth`.
3. Choose **Import** mode. (If the connector is missing, install *MySQL Connector/NET*.)

**Option B: CSV files (no database needed)** — Get data → Text/CSV → every file in `powerbi/exports/`.

Check types in Power Query: `order_date`, `date_key`, `signup_date` = Date; money columns = Fixed decimal number.

## Step 2 — Model

Follow the relationship table in `DAX_measures.md`, mark `dim_date` as the date table, then add all measures.
Hide foreign keys and helper columns from Report view so the field list stays clean.

## Step 3 — Pages and visuals

### Page 1 · Executive Overview
| Visual | Fields |
|---|---|
| 5 KPI cards | Total Revenue · Total Orders · Average Order Value · Active Customers · YoY Growth % |
| Line + column chart | X `dim_date[month_label]`, columns `Total Revenue`, line `Revenue 3M Moving Avg` |
| Clustered column | X `dim_date[month_name]`, values `Total Revenue` and `Revenue LY` (YoY comparison) |
| Donut / bar | `dim_customers[region]` × `Total Revenue` |
| **Slicers** | Year (tile), Region (dropdown), Category (dropdown), Segment (buttons) |

### Page 2 · Product & Category
| Visual | Fields |
|---|---|
| Pareto (line + column) | `category`, `Total Revenue`, `Cumulative Revenue Share %` |
| Card | `Top 3 Category Share %` (the "≈ 60%" insight) |
| Bar chart (Top N filter = 10) | `product_name` × `Total Revenue` |
| Treemap | `category` → `product_name` |
| Table | product, units sold, revenue, `Category Rank` with data bars |

### Page 3 · Customers & Regions
| Visual | Fields |
|---|---|
| Matrix heat-map | Rows `vw_cohort_retention[cohort_month]`, columns `months_since_first`, values `Cohort Retention %` |
| Cards | `Repeat Customer Rate %`, `Revenue per Customer` |
| Filled map or bar | region × revenue, tooltip with `Region Revenue Share %` and AOV |
| Column chart | revenue by `vw_customer_summary[revenue_quintile]` (customer concentration) |

### Optional Page 4 · Data quality
Small table from `data/etl_report.json` (rows dropped / imputed per rule) — shows interviewers you care about trust in data.

## Step 4 — Polish (what makes it look professional)

- Theme: View → Themes → *Executive* or import a custom JSON; palette `#08519c`, `#3182bd`, `#9ecae1`, accent `#e6550d`.
- Same card height, 16 px gutters, titles left-aligned, **no 3D, no pie with > 5 slices**.
- Use **bookmarks + page navigation buttons**; add a *Reset filters* bookmark.
- Tooltip pages for the trend chart; conditional formatting (green ▲ / red ▼) on YoY.
- Sync slicers across pages (View → Sync slicers).
- Alt text on every visual (accessibility is a good talking point).

## Step 5 — Deliver

1. Save as `powerbi/Sales_Analytics_Dashboard.pbix`.
2. Take screenshots of each page → `docs/screenshots/` and reference them in the README.
3. Optional: publish to Power BI Service and add a screenshot of the published report
   (do **not** use *Publish to web* with company data).

## Reconciliation checklist (do this before the interview)

- [ ] `Total Revenue` card equals the SQL `SUM(net_revenue)` for completed orders
- [ ] Row count of `fact_orders` in Power BI equals `etl_report.json → loaded_rows.fact_orders`
- [ ] `Top 3 Category Share %` ≈ `docs/INSIGHTS.md` (≈ 60%)
- [ ] Filtering Year = 2025 changes every page consistently
