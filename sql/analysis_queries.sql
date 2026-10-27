-- =====================================================================
-- Ad-hoc analysis queries (great for interview walk-throughs). MySQL 8+.
-- Run after the pipeline has loaded the data and created the views.
-- =====================================================================

-- Q1. Revenue by category and year (JOIN + conditional aggregation)
SELECT
    p.category,
    ROUND(SUM(CASE WHEN o.order_year = 2023 THEN o.net_revenue END), 0) AS rev_2023,
    ROUND(SUM(CASE WHEN o.order_year = 2024 THEN o.net_revenue END), 0) AS rev_2024,
    ROUND(SUM(CASE WHEN o.order_year = 2025 THEN o.net_revenue END), 0) AS rev_2025
FROM fact_orders o
JOIN dim_products p ON p.product_id = o.product_id
WHERE o.order_status = 'Completed'
GROUP BY p.category
ORDER BY rev_2025 DESC;

-- Q2. Top 3 products in every category (ROW_NUMBER + PARTITION BY)
SELECT category, product_name, revenue, rank_in_category
FROM vw_product_performance
WHERE rank_in_category <= 3
ORDER BY category, rank_in_category;

-- Q3. Running (cumulative) revenue by month
SELECT
    order_month,
    revenue,
    ROUND(SUM(revenue) OVER (ORDER BY order_month), 2) AS cumulative_revenue
FROM vw_monthly_revenue
ORDER BY order_month;

-- Q4. Best and worst months by MoM growth
SELECT order_month, revenue, mom_growth_pct
FROM vw_revenue_growth
WHERE mom_growth_pct IS NOT NULL
ORDER BY mom_growth_pct DESC
LIMIT 5;

-- Q5. Customer retention: repeat-customer rate overall
SELECT
    COUNT(*)                                                   AS customers,
    SUM(is_repeat_customer)                                    AS repeat_customers,
    ROUND(100.0 * SUM(is_repeat_customer) / COUNT(*), 2)       AS repeat_rate_pct
FROM vw_customer_summary;

-- Q6. How concentrated is revenue? Share of revenue from the top quintile of customers
SELECT
    revenue_quintile,
    COUNT(*)                                                   AS customers,
    ROUND(SUM(revenue), 0)                                     AS revenue,
    ROUND(100.0 * SUM(revenue) / SUM(SUM(revenue)) OVER (), 2) AS revenue_share_pct
FROM vw_customer_summary
GROUP BY revenue_quintile
ORDER BY revenue_quintile;

-- Q7. Average months between a customer's 1st and 2nd purchase (CTE + ROW_NUMBER self-join)
WITH ranked AS (
    SELECT
        customer_id,
        month_idx,
        ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY order_date, order_id) AS rn
    FROM fact_orders
    WHERE order_status = 'Completed'
)
SELECT ROUND(AVG(b.month_idx - a.month_idx), 2) AS avg_months_to_second_order
FROM ranked a
JOIN ranked b ON b.customer_id = a.customer_id AND a.rn = 1 AND b.rn = 2;

-- Q8. Region x category revenue matrix
SELECT
    c.region,
    p.category,
    ROUND(SUM(o.net_revenue), 0) AS revenue
FROM fact_orders o
JOIN dim_customers c ON c.customer_id = o.customer_id
JOIN dim_products  p ON p.product_id  = o.product_id
WHERE o.order_status = 'Completed'
GROUP BY c.region, p.category
ORDER BY c.region, revenue DESC;

-- Q9. Cancellation and return rate by category
SELECT
    p.category,
    COUNT(*)                                                                AS orders,
    ROUND(100.0 * SUM(CASE WHEN o.order_status = 'Cancelled' THEN 1 ELSE 0 END) / COUNT(*), 2) AS cancel_rate_pct,
    ROUND(100.0 * SUM(CASE WHEN o.order_status = 'Returned'  THEN 1 ELSE 0 END) / COUNT(*), 2) AS return_rate_pct
FROM fact_orders o
JOIN dim_products p ON p.product_id = o.product_id
GROUP BY p.category
ORDER BY cancel_rate_pct DESC;

-- Q10. Payment method mix and average order value
SELECT
    payment_method,
    COUNT(*)                                         AS orders,
    ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS order_share_pct,
    ROUND(AVG(net_revenue), 2)                       AS avg_order_value
FROM fact_orders
WHERE order_status = 'Completed'
GROUP BY payment_method
ORDER BY orders DESC;
