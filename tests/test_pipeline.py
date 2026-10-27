"""Integration test: tiny dataset -> ETL -> SQL views -> every analysis query runs (SQLite)."""
import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from src import analysis, config, etl, generate_data


@pytest.fixture(scope="module")
def engine(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("pipeline")
    generate_data.generate(n_customers=3000, n_orders=8000, out_dir=tmp / "raw")
    eng = create_engine(f"sqlite:///{tmp / 'test.db'}")
    etl.run_etl(eng, raw_dir=tmp / "raw", report_path=tmp / "report.json")
    analysis.apply_views(eng)
    return eng


def _scalar(engine, sql):
    with engine.connect() as c:
        return c.execute(text(sql)).scalar()


def test_fact_table_is_clean(engine):
    assert _scalar(engine, "SELECT COUNT(*) FROM fact_orders") > 7000
    assert _scalar(engine, "SELECT COUNT(*) - COUNT(DISTINCT order_id) FROM fact_orders") == 0
    assert _scalar(engine, "SELECT COUNT(*) FROM fact_orders WHERE net_revenue <= 0 OR quantity <= 0") == 0
    assert _scalar(engine, "SELECT COUNT(*) FROM fact_orders f LEFT JOIN dim_customers c "
                           "ON c.customer_id = f.customer_id WHERE c.customer_id IS NULL") == 0


def test_views_reconcile_with_fact(engine):
    fact = _scalar(engine, "SELECT SUM(net_revenue) FROM fact_orders WHERE order_status = 'Completed'")
    for view in ("vw_monthly_revenue", "vw_yearly_summary", "vw_category_revenue", "vw_region_summary"):
        assert _scalar(engine, f"SELECT SUM(revenue) FROM {view}") == pytest.approx(fact, rel=1e-4), view


def test_category_shares_sum_to_100(engine):
    assert _scalar(engine, "SELECT SUM(revenue_share_pct) FROM vw_category_revenue") == pytest.approx(100, abs=0.1)
    assert _scalar(engine, "SELECT MAX(cumulative_share_pct) FROM vw_category_revenue") == pytest.approx(100, abs=0.1)


def test_every_analysis_query_runs(engine):
    results = analysis.run_sql_file(engine, config.SQL_DIR / "analysis_queries.sql")
    assert len(results) == 10
    assert all(isinstance(df, pd.DataFrame) and len(df) > 0 for df in results.values())


def test_insights_report_builds(engine, tmp_path):
    s = analysis.write_insights(engine, tmp_path / "INSIGHTS.md")
    assert (tmp_path / "INSIGHTS.md").read_text(encoding="utf-8").startswith("# Key Business Insights")
    assert 0 < s["top3_share"] <= 100
