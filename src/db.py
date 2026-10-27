"""Database layer: engine creation and the star-schema table definitions (SQLAlchemy Core)."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from sqlalchemy import (
    Column,
    Date,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    create_engine,
    text,
)
from sqlalchemy.engine import Engine, make_url

from . import config

log = logging.getLogger(__name__)
metadata = MetaData()

dim_date = Table(
    "dim_date",
    metadata,
    Column("date_key", Date, primary_key=True),
    Column("year", Integer, nullable=False),
    Column("quarter", Integer, nullable=False),
    Column("month", Integer, nullable=False),
    Column("month_name", String(10), nullable=False),
    Column("month_label", String(7), nullable=False),
    Column("month_idx", Integer, nullable=False),
    Column("day_of_week", String(10), nullable=False),
    Column("is_weekend", Integer, nullable=False),
)

dim_customers = Table(
    "dim_customers",
    metadata,
    Column("customer_id", String(12), primary_key=True),
    Column("customer_name", String(100)),
    Column("email", String(120)),
    Column("region", String(20), nullable=False),
    Column("city", String(50)),
    Column("segment", String(20)),
    Column("signup_date", Date),
)

dim_products = Table(
    "dim_products",
    metadata,
    Column("product_id", String(12), primary_key=True),
    Column("product_name", String(100), nullable=False),
    Column("category", String(40), nullable=False),
    Column("list_price", Numeric(12, 2), nullable=False),
)

fact_orders = Table(
    "fact_orders",
    metadata,
    Column("order_id", String(16), primary_key=True),
    Column("customer_id", String(12), ForeignKey("dim_customers.customer_id"), nullable=False),
    Column("product_id", String(12), ForeignKey("dim_products.product_id"), nullable=False),
    Column("order_date", Date, nullable=False),
    Column("order_month", String(7), nullable=False),
    Column("order_year", Integer, nullable=False),
    Column("order_quarter", Integer, nullable=False),
    Column("month_idx", Integer, nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("unit_price", Numeric(12, 2), nullable=False),
    Column("discount_pct", Numeric(5, 2), nullable=False),
    Column("gross_amount", Numeric(14, 2), nullable=False),
    Column("discount_amount", Numeric(14, 2), nullable=False),
    Column("net_revenue", Numeric(14, 2), nullable=False),
    Column("payment_method", String(20)),
    Column("order_status", String(15), nullable=False),
    Index("ix_fact_order_date", "order_date"),
    Index("ix_fact_customer", "customer_id"),
    Index("ix_fact_product", "product_id"),
    Index("ix_fact_month", "order_month"),
    Index("ix_fact_status", "order_status"),
)


def ensure_mysql_database(url: str) -> None:
    """CREATE DATABASE IF NOT EXISTS for MySQL so users do not have to do it by hand."""
    parsed = make_url(url)
    if not parsed.drivername.startswith("mysql") or not parsed.database:
        return
    server_engine = create_engine(parsed.set(database=None))
    with server_engine.begin() as conn:
        conn.execute(
            text(f"CREATE DATABASE IF NOT EXISTS `{parsed.database}` CHARACTER SET utf8mb4")
        )
    server_engine.dispose()


def get_engine(backend: str | None = None, url: str | None = None) -> Engine:
    url = url or config.get_db_url(backend)
    if url.startswith("mysql"):
        ensure_mysql_database(url)
    engine = create_engine(url, pool_pre_ping=True)
    log.info("Using database: %s", make_url(url).render_as_string(hide_password=True))
    return engine


# ---------- helpers for the .sql files ----------

def split_statements(sql_text: str) -> list[str]:
    """Split a .sql file into statements (drops whole-line '--' comments)."""
    lines = [ln for ln in sql_text.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def view_names(sql_path: Path | None = None) -> list[str]:
    sql_path = sql_path or config.SQL_DIR / "views.sql"
    return re.findall(r"CREATE\s+VIEW\s+(\w+)", sql_path.read_text(encoding="utf-8"), re.I)


def drop_views(engine: Engine, sql_path: Path | None = None) -> None:
    with engine.begin() as conn:
        for name in reversed(view_names(sql_path)):
            conn.execute(text(f"DROP VIEW IF EXISTS {name}"))
