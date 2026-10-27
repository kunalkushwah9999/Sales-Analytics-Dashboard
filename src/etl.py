"""ETL: extract raw CSVs -> clean / transform with Pandas -> load into MySQL via SQLAlchemy."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from . import config
from .db import drop_views, metadata

log = logging.getLogger(__name__)

NA_TOKENS = {"", "n/a", "na", "nan", "null", "none", "-"}
REGIONS = {"north", "south", "east", "west", "central"}
CATEGORY_MAP = {
    "electronics": "Electronics", "furniture": "Furniture", "home & kitchen": "Home & Kitchen",
    "fashion": "Fashion", "sports": "Sports", "beauty": "Beauty", "books": "Books", "toys": "Toys",
}
PAYMENT_MAP = {
    "upi": "UPI", "credit card": "Credit Card", "cc": "Credit Card", "debit card": "Debit Card",
    "cod": "COD", "cash on delivery": "COD", "net banking": "Net Banking", "netbanking": "Net Banking",
    "wallet": "Wallet",
}
STATUS_MAP = {
    "completed": "Completed", "complete": "Completed", "cancelled": "Cancelled",
    "canceled": "Cancelled", "returned": "Returned", "return": "Returned",
}


# ----------------------------------------------------------------------------- helpers

def _clean_str(s: pd.Series) -> pd.Series:
    """Trim whitespace and turn empty / 'N/A' style tokens into proper missing values."""
    s = s.astype("string").str.strip()
    return s.mask(s.str.lower().isin(NA_TOKENS))


def _norm_key(s: pd.Series) -> pd.Series:
    """lower-case, '_' -> ' ', 'and' / '&' unified, single spaces. Used for mapping messy labels."""
    return (
        s.str.lower().str.replace("_", " ", regex=False)
        .str.replace(r"\s*&\s*|\s+and\s+", " & ", regex=True)
        .str.replace(r"\s+", " ", regex=True).str.strip()
    )


def parse_dates(s: pd.Series) -> pd.Series:
    """Parse YYYY-MM-DD first, then DD-MM-YYYY. Anything else becomes NaT."""
    s = _clean_str(s)
    iso = pd.to_datetime(s, format="%Y-%m-%d", errors="coerce")
    dmy = pd.to_datetime(s, format="%d-%m-%Y", errors="coerce")
    return iso.fillna(dmy)


def _drop(df: pd.DataFrame, mask: pd.Series, key: str, stats: dict) -> pd.DataFrame:
    mask = np.asarray(mask, dtype=bool)
    stats[key] = int(mask.sum())
    return df.loc[~mask].copy()


def _plain(df: pd.DataFrame) -> pd.DataFrame:
    """Convert pandas string dtypes to plain Python objects (None for missing) for DB insertion."""
    df = df.copy()
    for col in df.columns:
        if pd.api.types.is_string_dtype(df[col]) and not pd.api.types.is_object_dtype(df[col]):
            df[col] = df[col].astype(object).where(df[col].notna(), None)
    return df


def _date_objects(s: pd.Series) -> pd.Series:
    return s.dt.date.where(s.notna(), None)


# ----------------------------------------------------------------------------- extract

def extract(raw_dir: Path = config.RAW_DIR) -> dict[str, pd.DataFrame]:
    raw_dir = Path(raw_dir)
    frames = {
        name: pd.read_csv(raw_dir / f"{name}_raw.csv", dtype=str, keep_default_na=False)
        for name in ("customers", "products", "orders")
    }
    for name, df in frames.items():
        log.info("Extracted %-9s %8d rows", name, len(df))
    return frames


# ----------------------------------------------------------------------------- transform

def clean_customers(raw: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame({
        "customer_id": _clean_str(raw["customer_id"]).str.upper(),
        "customer_name": _clean_str(raw["customer_name"]).str.title(),
        "email": _clean_str(raw["email"]).str.lower(),
        "region": _clean_str(raw["region"]).str.title(),
        "city": _clean_str(raw["city"]).str.title(),
        "segment": _clean_str(raw["segment"]).str.title(),
        "signup_date": parse_dates(raw["signup_date"]),
    })
    df["region"] = df["region"].where(df["region"].str.lower().isin(REGIONS), "Unknown")
    df["segment"] = df["segment"].fillna("Consumer")
    df = df.dropna(subset=["customer_id"]).drop_duplicates("customer_id", keep="first")
    df["signup_date"] = _date_objects(df["signup_date"])
    return df.reset_index(drop=True)


def clean_products(raw: pd.DataFrame) -> pd.DataFrame:
    df = pd.DataFrame({
        "product_id": _clean_str(raw["product_id"]).str.upper(),
        "product_name": _clean_str(raw["product_name"]),
        "category": _norm_key(_clean_str(raw["category"])).map(CATEGORY_MAP),
        "list_price": pd.to_numeric(raw["list_price"], errors="coerce"),
    })
    df["category"] = df["category"].fillna("Other")
    df = df.dropna(subset=["product_id", "product_name", "list_price"])
    return df.drop_duplicates("product_id", keep="first").reset_index(drop=True)


def clean_orders(raw: pd.DataFrame, customers: pd.DataFrame, products: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Return (clean fact table, data-quality stats)."""
    stats: dict[str, int] = {"raw_rows": int(len(raw))}
    df = pd.DataFrame({
        "order_id": _clean_str(raw["order_id"]).str.upper(),
        "customer_id": _clean_str(raw["customer_id"]).str.upper(),
        "product_id": _clean_str(raw["product_id"]).str.upper(),
        "order_date": parse_dates(raw["order_date"]),
        "quantity": pd.to_numeric(raw["quantity"], errors="coerce"),
        "unit_price": pd.to_numeric(raw["unit_price"], errors="coerce"),
        "discount_pct": pd.to_numeric(raw["discount_pct"], errors="coerce"),
        "payment_method": _clean_str(raw["payment_method"]),
        "order_status": _clean_str(raw["order_status"]),
    })

    # 1) mandatory keys + duplicates
    df = _drop(df, df[["order_id", "customer_id", "product_id"]].isna().any(axis=1), "dropped_missing_keys", stats)
    df = _drop(df, df.duplicated("order_id", keep="first"), "dropped_duplicates", stats)

    # 2) dates: unparseable or outside the business window
    lo, hi = pd.Timestamp(config.START_DATE), pd.Timestamp(config.END_DATE)
    bad_date = df["order_date"].isna() | (df["order_date"] < lo) | (df["order_date"] > hi)
    df = _drop(df, bad_date, "dropped_bad_dates", stats)

    # 3) status normalisation
    df["order_status"] = _norm_key(df["order_status"]).map(STATUS_MAP)
    df = _drop(df, df["order_status"].isna(), "dropped_bad_status", stats)

    # 4) referential integrity
    orphan = ~df["customer_id"].isin(customers["customer_id"]) | ~df["product_id"].isin(products["product_id"])
    df = _drop(df, orphan, "dropped_orphan_keys", stats)

    # 5) quantity: impute missing with 1, drop impossible values
    stats["imputed_quantity"] = int(df["quantity"].isna().sum())
    df["quantity"] = df["quantity"].fillna(1)
    bad_qty = (df["quantity"] <= 0) | (df["quantity"] > 100) | (df["quantity"] != df["quantity"].round())
    df = _drop(df, bad_qty, "dropped_bad_quantity", stats)
    df["quantity"] = df["quantity"].astype(int)

    # 6) unit price: fall back to the product's list price
    list_price = df["product_id"].map(products.set_index("product_id")["list_price"])
    bad_price = df["unit_price"].isna() | (df["unit_price"] <= 0)
    stats["imputed_unit_price"] = int(bad_price.sum())
    df["unit_price"] = df["unit_price"].where(~bad_price, list_price).astype(float)

    # 7) discount: valid range 0-80 %, anything else is a data-entry error -> 0
    bad_disc = df["discount_pct"].isna() | (df["discount_pct"] < 0) | (df["discount_pct"] > 80)
    stats["fixed_discount"] = int(bad_disc.sum())
    df["discount_pct"] = df["discount_pct"].where(~bad_disc, 0.0).astype(float)

    # 8) payment method
    df["payment_method"] = _norm_key(df["payment_method"]).map(PAYMENT_MAP).fillna("Other")

    # 9) derived business columns
    df["gross_amount"] = (df["quantity"] * df["unit_price"]).round(2)
    df["discount_amount"] = (df["gross_amount"] * df["discount_pct"] / 100).round(2)
    df["net_revenue"] = (df["gross_amount"] - df["discount_amount"]).round(2)
    d = df["order_date"]
    df["order_month"] = d.dt.strftime("%Y-%m")
    df["order_year"] = d.dt.year.astype(int)
    df["order_quarter"] = d.dt.quarter.astype(int)
    df["month_idx"] = (d.dt.year * 12 + d.dt.month).astype(int)
    df["order_date"] = _date_objects(d)

    cols = ["order_id", "customer_id", "product_id", "order_date", "order_month", "order_year",
            "order_quarter", "month_idx", "quantity", "unit_price", "discount_pct", "gross_amount",
            "discount_amount", "net_revenue", "payment_method", "order_status"]
    df = df[cols].sort_values(["order_date", "order_id"]).reset_index(drop=True)
    stats["clean_rows"] = int(len(df))
    return df, stats


def build_dim_date(start: str = config.START_DATE, end: str = config.END_DATE) -> pd.DataFrame:
    d = pd.DataFrame({"d": pd.date_range(start, end, freq="D")})
    out = pd.DataFrame({
        "date_key": d["d"].dt.date,
        "year": d["d"].dt.year,
        "quarter": d["d"].dt.quarter,
        "month": d["d"].dt.month,
        "month_name": d["d"].dt.strftime("%b"),
        "month_label": d["d"].dt.strftime("%Y-%m"),
        "month_idx": d["d"].dt.year * 12 + d["d"].dt.month,
        "day_of_week": d["d"].dt.strftime("%a"),
        "is_weekend": (d["d"].dt.dayofweek >= 5).astype(int),
    })
    return out


# ----------------------------------------------------------------------------- load

def load(engine: Engine, tables: dict[str, pd.DataFrame]) -> dict[str, int]:
    """Drop + recreate the star schema, then bulk-insert. Views are dropped first (they depend on tables)."""
    drop_views(engine)
    metadata.drop_all(engine)
    metadata.create_all(engine)
    with engine.begin() as conn:
        for name in ("dim_date", "dim_customers", "dim_products", "fact_orders"):
            t0 = time.time()
            _plain(tables[name]).to_sql(name, conn, if_exists="append", index=False, chunksize=5000)
            log.info("Loaded %-14s %8d rows in %.1fs", name, len(tables[name]), time.time() - t0)
    with engine.connect() as conn:
        return {n: int(conn.execute(text(f"SELECT COUNT(*) FROM {n}")).scalar()) for n in tables}


def run_etl(engine: Engine, raw_dir: Path = config.RAW_DIR, report_path: Path | None = None) -> dict:
    raw = extract(raw_dir)
    customers = clean_customers(raw["customers"])
    products = clean_products(raw["products"])
    orders, stats = clean_orders(raw["orders"], customers, products)
    stats["dropped_total"] = stats["raw_rows"] - stats["clean_rows"]
    log.info("Data-quality report: %s", json.dumps(stats))

    counts = load(engine, {
        "dim_date": build_dim_date(), "dim_customers": customers,
        "dim_products": products, "fact_orders": orders,
    })
    report = {"quality": stats, "loaded_rows": counts}
    if report_path is None:
        report_path = config.DATA_DIR / "etl_report.json"
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
