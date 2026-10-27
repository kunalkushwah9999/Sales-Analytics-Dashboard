-- =====================================================================
-- Analytical views for the Sales Analytics Dashboard (MySQL 8+; also runs on SQLite 3.25+)
-- Revenue metrics always use completed orders only (order_status = 'Completed').
-- Views are (re)created by src/analysis.py; Power BI reads these views directly.
-- =====================================================================

-- 1. Monthly revenue, orders, customers and average order value
CREATE VIEW vw_monthly_revenue AS
SELECT
    order_month,
    order_year,
    COUNT(*)                                         AS orders,
    COUNT(DISTINCT customer_id)                      AS active_customers,
    ROUND(SUM(net_revenue), 2)                       AS revenue,
    ROUND(SUM(net_revenue) / COUNT(*), 2)            AS avg_order_value
FROM fact_orders
WHERE order_status = 'Completed'
GROUP BY order_month, order_year;

-- 2. Month-over-month, year-over-year growth and 3-month moving average (window functions)
CREATE VIEW vw_revenue_growth AS
SELECT
    order_month,
    revenue,
    LAG(revenue, 1)  OVER (ORDER BY order_month)     AS prev_month_revenue,
    ROUND(100.0 * (revenue - LAG(revenue, 1) OVER (ORDER BY order_month))
          / NULLIF(LAG(revenue, 1) OVER (ORDER BY order_month), 0), 2)   AS mom_growth_pct,
    LAG(revenue, 12) OVER (ORDER BY order_month)     AS same_month_last_year,
    ROUND(100.0 * (revenue - LAG(revenue, 12) OVER (ORDER BY order_month))
          / NULLIF(LAG(revenue, 12) OVER (ORDER BY order_month), 0), 2)  AS yoy_growth_pct,
    ROUND(AVG(revenue) OVER (ORDER BY order_month
          ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2)                  AS moving_avg_3m,
    ROUND(SUM(revenue) OVER (PARTITION BY SUBSTR(order_month, 1, 4)
          ORDER BY order_month), 2)                                      AS ytd_revenue
FROM vw_monthly_revenue;

-- 3. Yearly summary with YoY growth
CREATE VIEW vw_yearly_summary AS
WITH yearly AS (
    SELECT
        order_year,
        COUNT(*)                        AS orders,
        COUNT(DISTINCT customer_id)     AS customers,
        ROUND(SUM(net_revenue), 2)      AS revenue
    FROM fact_orders
    WHERE order_status = 'Completed'
    GROUP BY order_year
)
SELECT
    order_year,
    orders,
    customers,
    revenue,
    ROUND(revenue / orders, 2)                                              AS avg_order_value,
    ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY order_year))
          / NULLIF(LAG(revenue) OVER (ORDER BY order_year), 0), 2)          AS yoy_growth_pct
FROM yearly;

-- 4. Category revenue share + cumulative (Pareto) share
CREATE VIEW vw_category_revenue AS
WITH cat AS (
    SELECT p.category, SUM(o.net_revenue) AS revenue, COUNT(*) AS orders
    FROM fact_orders o
    JOIN dim_products p ON p.product_id = o.product_id
    WHERE o.order_status = 'Completed'
    GROUP BY p.category
)
SELECT
    category,
    orders,
    ROUND(revenue, 2)                                                       AS revenue,
    ROUND(100.0 * revenue / SUM(revenue) OVER (), 2)                        AS revenue_share_pct,
    ROUND(100.0 * SUM(revenue) OVER (ORDER BY revenue DESC
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
          / SUM(revenue) OVER (), 2)                                        AS cumulative_share_pct,
    RANK() OVER (ORDER BY revenue DESC)                                     AS category_rank
FROM cat;

-- 5. Product performance with overall and within-category ranking
CREATE VIEW vw_product_performance AS
SELECT
    p.product_id,
    p.product_name,
    p.category,
    SUM(o.quantity)                                              AS units_sold,
    ROUND(SUM(o.net_revenue), 2)                                 AS revenue,
    RANK() OVER (ORDER BY SUM(o.net_revenue) DESC)               AS overall_rank,
    RANK() OVER (PARTITION BY p.category
                 ORDER BY SUM(o.net_revenue) DESC)               AS rank_in_category
FROM fact_orders o
JOIN dim_products p ON p.product_id = o.product_id
WHERE o.order_status = 'Completed'
GROUP BY p.product_id, p.product_name, p.category;

-- 6. Customer summary: lifetime value, repeat flag and revenue quintile (NTILE)
CREATE VIEW vw_customer_summary AS
SELECT
    c.customer_id,
    c.region,
    c.segment,
    COUNT(*)                                          AS orders,
    ROUND(SUM(o.net_revenue), 2)                      AS revenue,
    MIN(o.order_date)                                 AS first_order_date,
    MAX(o.order_date)                                 AS last_order_date,
    CASE WHEN COUNT(*) >= 2 THEN 1 ELSE 0 END        AS is_repeat_customer,
    NTILE(5) OVER (ORDER BY SUM(o.net_revenue) DESC)  AS revenue_quintile
FROM fact_orders o
JOIN dim_customers c ON c.customer_id = o.customer_id
WHERE o.order_status = 'Completed'
GROUP BY c.customer_id, c.region, c.segment;

-- 7. First-purchase cohort of every customer
CREATE VIEW vw_customer_cohorts AS
SELECT
    customer_id,
    MIN(order_month) AS cohort_month,
    MIN(month_idx)   AS cohort_idx
FROM fact_orders
WHERE order_status = 'Completed'
GROUP BY customer_id;

-- 8. Cohort retention: % of a cohort that purchased again N months after its first purchase
CREATE VIEW vw_cohort_retention AS
WITH cohort_size AS (
    SELECT cohort_month, COUNT(*) AS cohort_customers
    FROM vw_customer_cohorts
    GROUP BY cohort_month
)
SELECT
    c.cohort_month,
    o.month_idx - c.cohort_idx                                   AS months_since_first,
    COUNT(DISTINCT o.customer_id)                                AS active_customers,
    s.cohort_customers,
    ROUND(100.0 * COUNT(DISTINCT o.customer_id) / s.cohort_customers, 2) AS retention_pct
FROM fact_orders o
JOIN vw_customer_cohorts c ON c.customer_id = o.customer_id
JOIN cohort_size s         ON s.cohort_month = c.cohort_month
WHERE o.order_status = 'Completed'
GROUP BY c.cohort_month, o.month_idx - c.cohort_idx, s.cohort_customers;

-- 9. Regional monthly sales trend
CREATE VIEW vw_regional_monthly AS
SELECT
    o.order_month,
    c.region,
    COUNT(*)                       AS orders,
    ROUND(SUM(o.net_revenue), 2)   AS revenue
FROM fact_orders o
JOIN dim_customers c ON c.customer_id = o.customer_id
WHERE o.order_status = 'Completed'
GROUP BY o.order_month, c.region;

-- 10. Region summary with revenue share and rank
CREATE VIEW vw_region_summary AS
WITH reg AS (
    SELECT
        c.region,
        COUNT(*)                     AS orders,
        COUNT(DISTINCT c.customer_id) AS customers,
        SUM(o.net_revenue)           AS revenue
    FROM fact_orders o
    JOIN dim_customers c ON c.customer_id = o.customer_id
    WHERE o.order_status = 'Completed'
    GROUP BY c.region
)
SELECT
    region,
    orders,
    customers,
    ROUND(revenue, 2)                                  AS revenue,
    ROUND(revenue / orders, 2)                         AS avg_order_value,
    ROUND(100.0 * revenue / SUM(revenue) OVER (), 2)   AS revenue_share_pct,
    RANK() OVER (ORDER BY revenue DESC)                AS region_rank
FROM reg;
