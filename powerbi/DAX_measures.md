# DAX Measures

Paste each measure into Power BI Desktop → **Modeling → New measure**. Keep them in a table called `_Measures`
(Enter Data → empty table → rename) and use display folders (KPIs, Time Intelligence, Customers, Category).

## Data model first (star schema)

| From (1) | To (*) | Notes |
|---|---|---|
| `dim_date[date_key]` | `fact_orders[order_date]` | Mark `dim_date` as a **Date table** (Table tools → Mark as date table → `date_key`) |
| `dim_customers[customer_id]` | `fact_orders[customer_id]` | single direction |
| `dim_products[product_id]` | `fact_orders[product_id]` | single direction |

Turn **off** *File → Options → Current File → Time intelligence → Auto date/time* so only `dim_date` is used.
Sort `dim_date[month_name]` by `dim_date[month]`.

> All revenue measures filter `order_status = "Completed"`, exactly like the SQL views, so the dashboard
> reconciles with the database.

---

## 1. Core KPIs

```dax
Total Revenue =
CALCULATE ( SUM ( fact_orders[net_revenue] ), fact_orders[order_status] = "Completed" )

Gross Revenue =
CALCULATE ( SUM ( fact_orders[gross_amount] ), fact_orders[order_status] = "Completed" )

Total Discount =
CALCULATE ( SUM ( fact_orders[discount_amount] ), fact_orders[order_status] = "Completed" )

Discount % = DIVIDE ( [Total Discount], [Gross Revenue] )

Total Orders =
CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[order_status] = "Completed" )

Units Sold =
CALCULATE ( SUM ( fact_orders[quantity] ), fact_orders[order_status] = "Completed" )

Active Customers =
CALCULATE ( DISTINCTCOUNT ( fact_orders[customer_id] ), fact_orders[order_status] = "Completed" )

Average Order Value = DIVIDE ( [Total Revenue], [Total Orders] )

Revenue per Customer = DIVIDE ( [Total Revenue], [Active Customers] )

Cancel / Return Rate % =
DIVIDE (
    CALCULATE ( COUNTROWS ( fact_orders ), fact_orders[order_status] <> "Completed" ),
    COUNTROWS ( fact_orders )
)
```

## 2. Time intelligence (year-over-year growth)

```dax
Revenue LY =
CALCULATE ( [Total Revenue], SAMEPERIODLASTYEAR ( dim_date[date_key] ) )

YoY Growth % = DIVIDE ( [Total Revenue] - [Revenue LY], [Revenue LY] )

Revenue YTD = TOTALYTD ( [Total Revenue], dim_date[date_key] )

Revenue PM =
CALCULATE ( [Total Revenue], DATEADD ( dim_date[date_key], -1, MONTH ) )

MoM Growth % = DIVIDE ( [Total Revenue] - [Revenue PM], [Revenue PM] )

Revenue 3M Moving Avg =
VAR _end = MAX ( dim_date[date_key] )
RETURN
    DIVIDE (
        CALCULATE ( [Total Revenue], DATESINPERIOD ( dim_date[date_key], _end, -3, MONTH ) ),
        3
    )

YoY Arrow =
IF ( [YoY Growth %] >= 0, "▲ ", "▼ " ) & FORMAT ( ABS ( [YoY Growth %] ), "0.0%" )
```

Use `YoY Growth %` in a KPI card (callout = `Revenue LY`) and conditional-format the font: green ≥ 0, red < 0.

## 3. Customers and retention

```dax
Repeat Customers =
COUNTROWS ( FILTER ( VALUES ( dim_customers[customer_id] ), [Total Orders] >= 2 ) )

Repeat Customer Rate % = DIVIDE ( [Repeat Customers], [Active Customers] )

New Customers =
VAR _start = MIN ( dim_date[date_key] )
VAR _end   = MAX ( dim_date[date_key] )
RETURN
    COUNTROWS (
        FILTER (
            VALUES ( vw_customer_summary[customer_id] ),
            CALCULATE ( MIN ( vw_customer_summary[first_order_date] ) ) >= _start
                && CALCULATE ( MIN ( vw_customer_summary[first_order_date] ) ) <= _end
        )
    )

-- Cohort matrix (import vw_cohort_retention): rows = cohort_month, columns = months_since_first
Cohort Retention % =
DIVIDE (
    SUM ( vw_cohort_retention[active_customers] ),
    SUM ( vw_cohort_retention[cohort_customers] )
)
```

Format `Cohort Retention %` as 0.0% and apply **Conditional formatting → Background color → Gradient** on the matrix.

## 4. Category contribution (the "top 3 ≈ 60%" insight)

```dax
Category Revenue Share % =
DIVIDE ( [Total Revenue], CALCULATE ( [Total Revenue], ALLSELECTED ( dim_products[category] ) ) )

Category Rank =
RANKX ( ALLSELECTED ( dim_products[category] ), [Total Revenue], , DESC, DENSE )

Top 3 Category Share % =
VAR _top3 = TOPN ( 3, ALLSELECTED ( dim_products[category] ), [Total Revenue], DESC )
RETURN
    DIVIDE (
        CALCULATE ( [Total Revenue], _top3 ),
        CALCULATE ( [Total Revenue], ALLSELECTED ( dim_products[category] ) )
    )

Cumulative Revenue Share % =
VAR _rev  = [Total Revenue]
VAR _cats = ALLSELECTED ( dim_products[category] )
VAR _cum  = SUMX ( FILTER ( _cats, [Total Revenue] >= _rev ), [Total Revenue] )
RETURN
    DIVIDE ( _cum, CALCULATE ( [Total Revenue], _cats ) )
```

Pareto visual: **Line and clustered column chart** → X = `category`, columns = `Total Revenue`,
line = `Cumulative Revenue Share %`.

## 5. Regional

```dax
Region Revenue Share % =
DIVIDE ( [Total Revenue], CALCULATE ( [Total Revenue], ALLSELECTED ( dim_customers[region] ) ) )

Top Region =
VAR _t = TOPN ( 1, ALLSELECTED ( dim_customers[region] ), [Total Revenue], DESC )
RETURN MAXX ( _t, dim_customers[region] )
```

## 6. Dynamic titles (nice touch for interviews)

```dax
Page Title =
"Revenue " & FORMAT ( [Total Revenue] / 10000000, "0.00" ) & " Cr  |  "
    & SELECTEDVALUE ( dim_date[year], "All years" )
    & "  |  " & SELECTEDVALUE ( dim_customers[region], "All regions" )
```

## Sanity checks (reconcile with SQL)

| Power BI (no slicers) | SQL |
|---|---|
| `Total Revenue` | `SELECT SUM(net_revenue) FROM fact_orders WHERE order_status='Completed'` |
| `Total Orders` | `SELECT COUNT(*) ... WHERE order_status='Completed'` |
| `Top 3 Category Share %` | `SELECT SUM(revenue_share_pct) FROM vw_category_revenue WHERE category_rank <= 3` |
