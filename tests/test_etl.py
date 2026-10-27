"""Unit tests for the cleaning rules (tiny hand-made dirty frames)."""
import datetime as dt

import pandas as pd

from src import etl
from src.db import split_statements


def _customers():
    raw = pd.DataFrame({
        "customer_id": ["c1", "C1", "C2", "C3"],
        "customer_name": [" aarav sharma", "aarav sharma", "Riya Gupta", "x y"],
        "email": ["A@X.com", "A@X.com", "", "n/a"],
        "region": [" north ", "NORTH", "wEsT", "mars"],
        "city": ["delhi", "delhi", "pune", "pune"],
        "segment": ["consumer", "consumer", "", "Corporate"],
        "signup_date": ["2023-01-05", "2023-01-05", "05-02-2023", "garbage"],
    })
    return etl.clean_customers(raw)


def _products():
    raw = pd.DataFrame({
        "product_id": ["p1", "P2", "P3"],
        "product_name": ["Phone", "Mixer", "Sofa"],
        "category": ["electronics ", "Home and Kitchen", "HOME & KITCHEN"],
        "list_price": ["100", "500", "abc"],
    })
    return etl.clean_products(raw)


def test_parse_dates_handles_both_formats_and_garbage():
    out = etl.parse_dates(pd.Series(["2024-03-05", "05-03-2024", "N/A", "", "31-31-2024"]))
    assert out.iloc[0] == out.iloc[1] == pd.Timestamp("2024-03-05")
    assert out.iloc[2:].isna().all()


def test_clean_customers_dedups_and_standardises():
    c = _customers()
    assert list(c["customer_id"]) == ["C1", "C2", "C3"]
    assert list(c["region"]) == ["North", "West", "Unknown"]
    assert c.loc[0, "customer_name"] == "Aarav Sharma"
    assert c.loc[1, "signup_date"] == dt.date(2023, 2, 5)
    assert c.loc[1, "segment"] == "Consumer"  # missing -> default
    assert pd.isna(c.loc[1, "email"]) and pd.isna(c.loc[2, "email"])


def test_clean_products_normalises_categories_and_drops_bad_price():
    p = _products()
    assert list(p["product_id"]) == ["P1", "P2"]  # P3 has a non-numeric price
    assert list(p["category"]) == ["Electronics", "Home & Kitchen"]


def test_clean_orders_rules_and_math():
    cols = ["order_id", "customer_id", "product_id", "order_date", "quantity",
            "unit_price", "discount_pct", "payment_method", "order_status"]
    rows = [
        ["ORD1", "C1", "P1", "2024-03-05", "2", "100", "10", "upi", "completed"],      # good
        ["ORD1", "C1", "P1", "2024-03-05", "2", "100", "10", "upi", "completed"],      # duplicate
        ["ORD2", "C1", "P2", "05-03-2024", "", "", "150", "Cash on Delivery", "Canceled"],  # fixable
        ["ORD3", "C1", "P1", "2024-03-06", "-1", "100", "0", "upi", "completed"],      # bad qty
        ["ORD4", "C9", "P1", "2024-03-06", "1", "100", "0", "upi", "completed"],       # orphan customer
        ["ORD5", "C1", "P1", "N/A", "1", "100", "0", "upi", "completed"],              # bad date
        ["ORD6", "", "P1", "2024-03-06", "1", "100", "0", "upi", "completed"],         # missing key
    ]
    raw = pd.DataFrame(rows, columns=cols)
    clean, stats = etl.clean_orders(raw, _customers(), _products())

    assert stats["raw_rows"] == 7 and stats["clean_rows"] == 2
    assert stats["dropped_duplicates"] == 1
    assert stats["dropped_missing_keys"] == 1
    assert stats["dropped_bad_dates"] == 1
    assert stats["dropped_orphan_keys"] == 1
    assert stats["dropped_bad_quantity"] == 1
    assert stats["imputed_quantity"] == 1 and stats["imputed_unit_price"] == 1 and stats["fixed_discount"] == 1

    a, b = clean.iloc[0], clean.iloc[1]
    assert (a["gross_amount"], a["discount_amount"], a["net_revenue"]) == (200.0, 20.0, 180.0)
    assert a["order_status"] == "Completed" and a["payment_method"] == "UPI"
    assert a["order_month"] == "2024-03" and a["month_idx"] == 2024 * 12 + 3
    # fixable row: qty -> 1, price -> list price 500, discount 150 -> 0
    assert (b["quantity"], b["unit_price"], b["discount_pct"], b["net_revenue"]) == (1, 500.0, 0.0, 500.0)
    assert b["order_status"] == "Cancelled" and b["payment_method"] == "COD"
    assert b["order_date"] == dt.date(2024, 3, 5)


def test_split_statements_ignores_comments():
    sql = "-- header\nSELECT 1;\n-- another\nSELECT 2;\n"
    assert split_statements(sql) == ["SELECT 1", "SELECT 2"]
