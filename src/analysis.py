"""Create the SQL views, export Power BI-ready CSVs, build the insights report and preview charts."""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from . import config
from .db import drop_views, split_statements, view_names

log = logging.getLogger(__name__)

TABLES = ["dim_date", "dim_customers", "dim_products", "fact_orders"]
SQL_VIEWS_PATH = config.SQL_DIR / "views.sql"


def apply_views(engine: Engine, sql_path: Path = SQL_VIEWS_PATH) -> list[str]:
    drop_views(engine, sql_path)
    with engine.begin() as conn:
        for stmt in split_statements(sql_path.read_text(encoding="utf-8")):
            conn.execute(text(stmt))
    names = view_names(sql_path)
    log.info("Created %d views: %s", len(names), ", ".join(names))
    return names


def run_sql_file(engine: Engine, sql_path: Path) -> dict[int, pd.DataFrame]:
    """Run every statement of a .sql file; returns {query_number: DataFrame}. Used by tests."""
    out = {}
    with engine.connect() as conn:
        for i, stmt in enumerate(split_statements(Path(sql_path).read_text(encoding="utf-8")), 1):
            out[i] = pd.read_sql(text(stmt), conn)
    return out


def export_all(engine: Engine, export_dir: Path = config.EXPORT_DIR) -> list[str]:
    """Write every table and view to CSV so Power BI can also be fed without a MySQL connection."""
    export_dir = Path(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)
    written = []
    with engine.connect() as conn:
        for name in TABLES + view_names():
            df = pd.read_sql(text(f"SELECT * FROM {name}"), conn)
            df.to_csv(export_dir / f"{name}.csv", index=False)
            written.append(f"{name}.csv ({len(df):,} rows)")
    log.info("Exported %d CSV files to %s", len(written), export_dir)
    return written


def _q(engine: Engine, sql: str) -> pd.DataFrame:
    with engine.connect() as conn:
        return pd.read_sql(text(sql), conn)


def fmt_inr(x: float) -> str:
    """Indian-style money: ₹12.34 Cr / ₹5.60 L."""
    if x >= 1e7:
        return f"₹{x / 1e7:,.2f} Cr"
    if x >= 1e5:
        return f"₹{x / 1e5:,.2f} L"
    return f"₹{x:,.0f}"


def compute_insights(engine: Engine) -> dict:
    kpi = _q(engine, """
        SELECT COUNT(*) AS orders, COUNT(DISTINCT customer_id) AS customers,
               SUM(net_revenue) AS revenue, MIN(order_date) AS first_date, MAX(order_date) AS last_date
        FROM fact_orders WHERE order_status = 'Completed'""").iloc[0]
    yearly = _q(engine, "SELECT * FROM vw_yearly_summary ORDER BY order_year")
    cats = _q(engine, "SELECT * FROM vw_category_revenue ORDER BY category_rank")
    regions = _q(engine, "SELECT * FROM vw_region_summary ORDER BY region_rank")
    monthly = _q(engine, "SELECT * FROM vw_monthly_revenue ORDER BY order_month")
    cust = _q(engine, "SELECT COUNT(*) AS n, SUM(is_repeat_customer) AS rep FROM vw_customer_summary").iloc[0]
    top_quintile = _q(engine, """
        SELECT 100.0 * SUM(CASE WHEN revenue_quintile = 1 THEN revenue END) / SUM(revenue) AS share
        FROM vw_customer_summary""").iloc[0]["share"]
    top_products = _q(engine, "SELECT product_name, category, revenue FROM vw_product_performance ORDER BY overall_rank LIMIT 5")

    # Cohort retention at +1 / +3 / +6 months, counting only cohorts old enough to have that data
    ret = _q(engine, "SELECT * FROM vw_cohort_retention")
    last_month = pd.Period(monthly["order_month"].max())
    retention = {}
    for k in (1, 3, 6):
        eligible = ret[(ret["months_since_first"] == k)
                       & (ret["cohort_month"].map(lambda m: pd.Period(m) + k <= last_month))]
        cohorts = ret[(ret["months_since_first"] == 0)
                      & (ret["cohort_month"].map(lambda m: pd.Period(m) + k <= last_month))]
        base = cohorts["cohort_customers"].sum()
        retention[k] = round(100 * eligible["active_customers"].sum() / base, 1) if base else None

    top3 = cats.head(3)
    best = monthly.loc[monthly["revenue"].idxmax()]
    return {
        "kpi": kpi, "yearly": yearly, "cats": cats, "regions": regions, "monthly": monthly,
        "repeat_rate": round(100 * cust["rep"] / cust["n"], 1), "top_quintile_share": round(float(top_quintile), 1),
        "top3_share": round(float(top3["revenue_share_pct"].sum()), 1), "top3_names": list(top3["category"]),
        "best_month": (best["order_month"], float(best["revenue"])), "retention": retention,
        "top_products": top_products,
    }


def write_insights(engine: Engine, path: Path = config.DOCS_DIR / "INSIGHTS.md") -> dict:
    s = compute_insights(engine)
    k, y = s["kpi"], s["yearly"]
    aov = k["revenue"] / k["orders"]
    growth = y["yoy_growth_pct"].dropna().tolist()
    lines = [
        "# Key Business Insights (auto-generated from the pipeline)\n",
        f"Period: **{k['first_date']} → {k['last_date']}** · completed orders only\n",
        "## Headline KPIs\n",
        "| KPI | Value |", "|---|---|",
        f"| Total revenue | {fmt_inr(k['revenue'])} |",
        f"| Completed orders | {int(k['orders']):,} |",
        f"| Unique customers | {int(k['customers']):,} |",
        f"| Average order value | ₹{aov:,.0f} |",
        f"| Repeat-customer rate | {s['repeat_rate']}% |",
        f"| Revenue from top 20% customers | {s['top_quintile_share']}% |",
        f"| Best month | {s['best_month'][0]} ({fmt_inr(s['best_month'][1])}) |",
        "\n## Year-over-year\n", "| Year | Revenue | Orders | AOV | YoY growth |", "|---|---|---|---|---|",
    ]
    for _, r in y.iterrows():
        g = "—" if pd.isna(r["yoy_growth_pct"]) else f"{r['yoy_growth_pct']:+.1f}%"
        lines.append(f"| {int(r['order_year'])} | {fmt_inr(r['revenue'])} | {int(r['orders']):,} | ₹{r['avg_order_value']:,.0f} | {g} |")
    lines += ["\n## Category contribution\n", "| Rank | Category | Revenue | Share | Cumulative |", "|---|---|---|---|---|"]
    for _, r in s["cats"].iterrows():
        lines.append(f"| {int(r['category_rank'])} | {r['category']} | {fmt_inr(r['revenue'])} | {r['revenue_share_pct']}% | {r['cumulative_share_pct']}% |")
    lines += ["\n## Regional sales\n", "| Region | Revenue | Share | AOV |", "|---|---|---|---|"]
    for _, r in s["regions"].iterrows():
        lines.append(f"| {r['region']} | {fmt_inr(r['revenue'])} | {r['revenue_share_pct']}% | ₹{r['avg_order_value']:,.0f} |")
    r1, r3, r6 = (s["retention"].get(i) for i in (1, 3, 6))
    lines += [
        "\n## Cohort retention (customers buying again N months after their first order)\n",
        f"- Month +1: **{r1}%** · Month +3: **{r3}%** · Month +6: **{r6}%**\n",
        "## Top 5 products by revenue\n",
    ]
    for _, r in s["top_products"].iterrows():
        lines.append(f"- {r['product_name']} ({r['category']}) — {fmt_inr(r['revenue'])}")
    lines += [
        "\n## Resume-ready findings (numbers verified against this run)\n",
        f"- Top three categories ({', '.join(s['top3_names'])}) contribute **{s['top3_share']}%** of revenue.",
        f"- Revenue grew {', '.join(f'{g:+.1f}%' for g in growth)} year over year; average order value is ₹{aov:,.0f}.",
        f"- {s['repeat_rate']}% of customers are repeat buyers; the top 20% of customers generate {s['top_quintile_share']}% of revenue.",
        f"- Sales peak around festive months (best month: {s['best_month'][0]}).",
    ]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("Insights written to %s", path)
    return s


def make_charts(engine: Engine, out_dir: Path = config.CHARTS_DIR) -> list[Path]:
    """Static preview charts for the README (the interactive version lives in Power BI)."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:  # pragma: no cover
        log.warning("matplotlib not installed - skipping charts")
        return []
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    g = _q(engine, "SELECT order_month, revenue, moving_avg_3m FROM vw_revenue_growth ORDER BY order_month")
    fig, ax = plt.subplots(figsize=(10, 4))
    x = list(range(len(g)))
    ax.bar(x, g["revenue"] / 1e5, color="#9ecae1", label="Monthly revenue")
    ax.plot(x, g["moving_avg_3m"] / 1e5, color="#08519c", lw=2, label="3-month moving avg")
    ax.set_title("Monthly Revenue (₹ Lakh)")
    ax.set_xticks(x[::3])
    ax.set_xticklabels(list(g["order_month"])[::3], rotation=45, ha="right")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    paths.append(out_dir / "monthly_revenue.png")
    fig.savefig(paths[-1], dpi=130)
    plt.close(fig)

    c = _q(engine, "SELECT category, revenue_share_pct, cumulative_share_pct FROM vw_category_revenue ORDER BY category_rank")
    fig, ax = plt.subplots(figsize=(8, 4))
    colors = ["#08519c"] * 3 + ["#c6dbef"] * (len(c) - 3)
    ax.bar(c["category"], c["revenue_share_pct"], color=colors)
    ax2 = ax.twinx()
    ax2.plot(c["category"], c["cumulative_share_pct"], color="#e6550d", marker="o")
    ax2.set_ylim(0, 105)
    ax.set_title("Category Revenue Share (Pareto) — top 3 highlighted")
    ax.set_ylabel("Share of revenue (%)")
    ax.tick_params(axis="x", rotation=30)
    ax.spines[["top"]].set_visible(False)
    fig.tight_layout()
    paths.append(out_dir / "category_pareto.png")
    fig.savefig(paths[-1], dpi=130)
    plt.close(fig)

    r = _q(engine, "SELECT months_since_first AS m, SUM(active_customers) AS a, SUM(cohort_customers) AS s "
                   "FROM vw_cohort_retention WHERE months_since_first BETWEEN 0 AND 12 GROUP BY months_since_first ORDER BY m")
    s0 = r.loc[r["m"] == 0, "a"].iloc[0]
    fig, ax = plt.subplots(figsize=(7, 3.5))
    ax.plot(r["m"], 100 * r["a"] / s0, marker="o", color="#08519c")
    ax.set_title("Customer Retention After First Purchase (all cohorts, indicative)")
    ax.set_xlabel("Months since first order")
    ax.set_ylabel("% of customers active")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    paths.append(out_dir / "retention_curve.png")
    fig.savefig(paths[-1], dpi=130)
    plt.close(fig)
    return paths
