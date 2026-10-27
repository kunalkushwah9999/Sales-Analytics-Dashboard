"""Generate a realistic, deliberately DIRTY e-commerce dataset (CSV) for the ETL to clean.

Output (data/raw): customers_raw.csv, products_raw.csv, orders_raw.csv
Dirt injected: duplicate rows, mixed date formats, missing values, negative quantities,
inconsistent casing/whitespace, invalid discounts, orphan keys.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from . import config

log = logging.getLogger(__name__)

# target = intended share of REVENUE; price = (min, max) list price in INR.
# Order shares are calibrated from these targets in make_orders(), so the top-3 categories
# (Electronics, Home & Kitchen, Furniture) land at roughly 60% of revenue.
CATEGORIES = {
    "Electronics": dict(
        target=0.27, price=(2000, 40000), qty_p=[0.93, 0.07, 0, 0, 0],
        names=["Smartphone", "Laptop", "Bluetooth Headphones", "Smart Watch", "Tablet",
               "Wireless Speaker", "Power Bank", "Gaming Console"],
    ),
    "Furniture": dict(
        target=0.15, price=(3500, 35000), qty_p=[0.95, 0.05, 0, 0, 0],
        names=["Office Chair", "Study Desk", "Bookshelf", "Sofa Set", "Queen Bed",
               "Dining Table", "Wardrobe", "TV Unit"],
    ),
    "Home & Kitchen": dict(
        target=0.18, price=(500, 12000), qty_p=[0.55, 0.25, 0.1, 0.06, 0.04],
        names=["Mixer Grinder", "Air Fryer", "Pressure Cooker", "Dinner Set", "Vacuum Cleaner",
               "Water Purifier", "Induction Cooktop", "Bedsheet Set"],
    ),
    "Fashion": dict(
        target=0.14, price=(400, 6000), qty_p=[0.5, 0.25, 0.12, 0.08, 0.05],
        names=["Denim Jeans", "Cotton Shirt", "Running Shoes", "Kurta Set", "Leather Wallet",
               "Handbag", "Winter Jacket", "Sunglasses"],
    ),
    "Sports": dict(
        target=0.11, price=(500, 9000), qty_p=[0.6, 0.22, 0.1, 0.05, 0.03],
        names=["Cricket Bat", "Yoga Mat", "Dumbbell Set", "Badminton Racket", "Football",
               "Cycling Helmet", "Treadmill Belt", "Resistance Bands"],
    ),
    "Beauty": dict(
        target=0.06, price=(150, 2500), qty_p=[0.45, 0.28, 0.14, 0.08, 0.05],
        names=["Face Serum", "Sunscreen SPF50", "Perfume", "Hair Dryer", "Lipstick Set",
               "Moisturizer", "Trimmer", "Shampoo Combo"],
    ),
    "Books": dict(
        target=0.03, price=(120, 900), qty_p=[0.5, 0.28, 0.12, 0.06, 0.04],
        names=["Data Science Handbook", "Python Crash Course", "Fiction Bestseller", "Self-Help Classic",
               "SQL Mastery", "UPSC Guide", "Kids Story Set", "Biography Collection"],
    ),
    "Toys": dict(
        target=0.06, price=(200, 2500), qty_p=[0.55, 0.25, 0.1, 0.06, 0.04],
        names=["Lego Style Blocks", "RC Car", "Board Game", "Puzzle 1000pc", "Doll House",
               "Art Kit", "Science Kit", "Soft Toy"],
    ),
}

REGIONS = {
    "North": ["Delhi", "Chandigarh", "Lucknow", "Jaipur", "Amritsar"],
    "South": ["Bengaluru", "Chennai", "Hyderabad", "Kochi", "Coimbatore"],
    "East": ["Kolkata", "Bhubaneswar", "Patna", "Guwahati", "Ranchi"],
    "West": ["Mumbai", "Pune", "Ahmedabad", "Surat", "Nagpur"],
    "Central": ["Indore", "Bhopal", "Raipur", "Jabalpur", "Gwalior"],
}
REGION_P = [0.24, 0.26, 0.14, 0.26, 0.10]

FIRST = ["Aarav", "Vivaan", "Aditya", "Riya", "Ananya", "Isha", "Rohan", "Kabir", "Neha", "Priya",
         "Arjun", "Saanvi", "Karan", "Meera", "Rahul", "Pooja", "Siddharth", "Diya", "Manish", "Kavya"]
LAST = ["Sharma", "Verma", "Gupta", "Patel", "Singh", "Kumar", "Reddy", "Nair", "Joshi", "Mehta",
        "Iyer", "Khan", "Das", "Yadav", "Kushwah", "Jain", "Mishra", "Chopra", "Bose", "Rao"]

PAYMENTS = ["UPI", "Credit Card", "Debit Card", "COD", "Net Banking", "Wallet"]
PAYMENT_P = [0.38, 0.22, 0.15, 0.13, 0.07, 0.05]
PAYMENT_DIRTY = {
    "UPI": ["upi", "UPI "], "Credit Card": ["credit card", "CC", "credit_card"],
    "Debit Card": ["debit card", "DEBIT CARD"], "COD": ["cod", "Cash on Delivery"],
    "Net Banking": ["netbanking", "net banking"], "Wallet": ["wallet", "WALLET "],
}
SEASONALITY = {1: .95, 2: .90, 3: 1.0, 4: 1.0, 5: 1.05, 6: .95,
               7: .90, 8: 1.0, 9: 1.05, 10: 1.35, 11: 1.30, 12: 1.15}


def _dirty_case(rng: np.random.Generator, values: pd.Series, p: float) -> pd.Series:
    """Randomly upper/lower/pad a share `p` of the strings."""
    out = values.copy()
    idx = np.where(rng.random(len(out)) < p)[0]
    for i in idx:
        v = out.iat[i]
        out.iat[i] = rng.choice([v.upper(), v.lower(), f" {v} ", f"{v}  "])
    return out


def make_customers(rng: np.random.Generator, n: int) -> pd.DataFrame:
    region = rng.choice(list(REGIONS), size=n, p=REGION_P)
    city = [rng.choice(REGIONS[r]) for r in region]
    first, last = rng.choice(FIRST, n), rng.choice(LAST, n)
    start, end = pd.Timestamp(config.START_DATE), pd.Timestamp(config.END_DATE)
    span = (end - start).days - 90
    days = (span * rng.beta(1.0, 2.2, n)).astype(int)  # most customers join early
    days[rng.random(n) < 0.10] = 0  # 10% are an existing customer base on day one
    signup = start + pd.to_timedelta(days, unit="D")
    df = pd.DataFrame({
        "customer_id": [f"C{i:05d}" for i in range(1, n + 1)],
        "customer_name": [f"{f} {l}" for f, l in zip(first, last)],
        "email": [f"{f}.{l}{i}@example.com".lower() for i, (f, l) in enumerate(zip(first, last), 1)],
        "region": region,
        "city": city,
        "segment": rng.choice(["Consumer", "Corporate", "Small Business"], n, p=[0.6, 0.25, 0.15]),
        "signup_date": signup.strftime("%Y-%m-%d"),
    })
    df["region"] = _dirty_case(rng, df["region"], 0.08)
    df["city"] = _dirty_case(rng, df["city"], 0.05)
    dmy = rng.random(n) < 0.04
    df.loc[dmy, "signup_date"] = signup[dmy].strftime("%d-%m-%Y")
    df.loc[rng.random(n) < 0.03, "email"] = ""
    return pd.concat([df, df.sample(40, random_state=config.SEED)], ignore_index=True)


def make_products(rng: np.random.Generator) -> pd.DataFrame:
    rows, pid = [], 1
    for cat, spec in CATEGORIES.items():
        lo, hi = spec["price"]
        u = (np.arange(len(spec["names"])) + 0.5) / len(spec["names"])
        prices = lo * (hi / lo) ** rng.permutation(u)  # evenly spread log-prices, random assignment
        for name, price in zip(spec["names"], prices):
            rows.append((f"P{pid:03d}", name, cat, round(float(price), 2)))
            pid += 1
    df = pd.DataFrame(rows, columns=["product_id", "product_name", "category", "list_price"])
    variants = {
        "Electronics": ["electronics ", "ELECTRONICS"], "Home & Kitchen": ["Home and Kitchen", "home & kitchen"],
        "Fashion": [" fashion"], "Sports": ["SPORTS"], "Beauty": ["beauty "],
    }
    for i in rng.choice(len(df), 12, replace=False):
        cat = df.at[i, "category"]
        if cat in variants:
            df.at[i, "category"] = rng.choice(variants[cat])
    return df


def make_orders(rng: np.random.Generator, n: int, signup: np.ndarray, products: pd.DataFrame) -> pd.DataFrame:
    n_customers = len(signup)
    months = pd.date_range(config.START_DATE, config.END_DATE, freq="MS")
    weight = np.linspace(1.0, 1.7, len(months)) * np.array([SEASONALITY[m.month] for m in months])
    mi = rng.choice(len(months), size=n, p=weight / weight.sum())
    day = (rng.random(n) * months.days_in_month.to_numpy()[mi]).astype(int)
    order_date = (months.to_numpy()[mi] + pd.to_timedelta(day, unit="D").to_numpy()).astype("datetime64[ns]")

    # Customers can only buy after they signed up; heavy-tailed activity => a minority buys often.
    by_signup = np.argsort(signup, kind="stable")
    sorted_signup = signup[by_signup].astype("datetime64[ns]")
    cum = np.cumsum(rng.gamma(0.6, size=n_customers))
    eligible = np.maximum(np.searchsorted(sorted_signup, order_date, side="right"), 1)
    pos = np.searchsorted(cum, rng.random(n) * cum[eligible - 1], side="right")
    cust_idx = by_signup[np.minimum(pos, eligible - 1)]

    # Category -> product -> quantity. Category order-shares are calibrated so each category
    # reaches its TARGET revenue share.
    cats = list(CATEGORIES)
    prices = products["list_price"].to_numpy()
    n_per = len(products) // len(cats)
    zipf = 1 / np.arange(1, n_per + 1) ** 0.7
    zipf /= zipf.sum()
    unit_rev = np.array([
        (zipf * prices[k * n_per:(k + 1) * n_per]).sum() * (np.arange(1, 6) * CATEGORIES[c]["qty_p"]).sum()
        for k, c in enumerate(cats)
    ])
    order_p = np.array([CATEGORIES[c]["target"] for c in cats]) / unit_rev
    order_p /= order_p.sum()

    cat_idx = rng.choice(len(cats), size=n, p=order_p)
    prod_idx = np.empty(n, dtype=int)
    qty = np.empty(n, dtype=int)
    prod_ids = products["product_id"].to_numpy()
    for k, cat in enumerate(cats):
        rows = np.where(cat_idx == k)[0]
        prod_idx[rows] = rng.choice(np.arange(k * n_per, (k + 1) * n_per), size=len(rows), p=zipf)
        qty[rows] = rng.choice([1, 2, 3, 4, 5], size=len(rows), p=CATEGORIES[cat]["qty_p"])

    pay = rng.choice(PAYMENTS, n, p=PAYMENT_P)
    df = pd.DataFrame({
        "customer_id": [f"C{i + 1:05d}" for i in cust_idx],
        "product_id": prod_ids[prod_idx],
        "order_date": pd.to_datetime(order_date).strftime("%Y-%m-%d"),
        "quantity": qty.astype(str),
        "unit_price": prices[prod_idx].round(2).astype(str),
        "discount_pct": rng.choice([0, 5, 10, 15, 20, 25], n, p=[.45, .15, .15, .12, .08, .05]).astype(str),
        "payment_method": pay,
        "order_status": rng.choice(["Completed", "Cancelled", "Returned"], n, p=[0.88, 0.07, 0.05]),
    })
    df = df.sort_values("order_date", kind="stable").reset_index(drop=True)
    df.insert(0, "order_id", [f"ORD{i:07d}" for i in range(1, n + 1)])
    return _inject_dirt(rng, df)


def _inject_dirt(rng: np.random.Generator, df: pd.DataFrame) -> pd.DataFrame:
    n = len(df)
    df = df.astype(object).copy()
    # mixed / invalid date formats
    dmy = rng.random(n) < 0.06
    df.loc[dmy, "order_date"] = pd.to_datetime(df.loc[dmy, "order_date"]).dt.strftime("%d-%m-%Y")
    df.loc[rng.random(n) < 0.003, "order_date"] = rng.choice(["N/A", "", "31-31-2024"])
    # quantity problems
    r = rng.random(n)
    df.loc[r < 0.004, "quantity"] = "-1"
    df.loc[(r >= 0.004) & (r < 0.007), "quantity"] = "0"
    df.loc[(r >= 0.007) & (r < 0.012), "quantity"] = ""
    # price / discount problems
    df.loc[rng.random(n) < 0.006, "unit_price"] = ""
    df.loc[rng.random(n) < 0.010, "discount_pct"] = ""
    df.loc[rng.random(n) < 0.002, "discount_pct"] = "150"
    # messy categoricals
    for canon, variants in PAYMENT_DIRTY.items():
        m = (df["payment_method"] == canon) & (rng.random(n) < 0.12)
        df.loc[m, "payment_method"] = rng.choice(variants, m.sum())
    m = rng.random(n) < 0.05
    df.loc[m, "order_status"] = [rng.choice([s.lower(), s.upper(), s + " "]) for s in df.loc[m, "order_status"]]
    m = df["order_status"].str.strip().str.lower() == "cancelled"
    df.loc[m & (rng.random(n) < 0.15), "order_status"] = "Canceled"
    # broken keys
    df.loc[rng.random(n) < 0.004, "customer_id"] = ""
    m = rng.random(n) < 0.01
    df.loc[m, "product_id"] = [f" {p.lower()} " for p in df.loc[m, "product_id"]]
    df.loc[rng.random(n) < 0.001, "customer_id"] = "C99999"  # orphan customer
    # duplicates (~1.5%) then shuffle
    dups = df.sample(frac=0.015, random_state=config.SEED)
    return pd.concat([df, dups]).sample(frac=1, random_state=config.SEED).reset_index(drop=True)


def generate(n_customers: int = config.N_CUSTOMERS, n_orders: int = config.N_ORDERS,
             seed: int = config.SEED, out_dir: Path = config.RAW_DIR) -> dict[str, int]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # independent RNG streams so changing one table never changes the others
    rng_c, rng_p, rng_o = (np.random.default_rng(seed + i) for i in range(3))
    customers = make_customers(rng_c, n_customers)
    # signup dates (some rows are dd-mm-yyyy) -> reliable datetime64 array, one entry per customer
    uniq = customers.drop_duplicates("customer_id")["signup_date"]
    iso = pd.to_datetime(uniq, format="%Y-%m-%d", errors="coerce")
    signup = iso.fillna(pd.to_datetime(uniq, format="%d-%m-%Y", errors="coerce")).to_numpy()
    products = make_products(rng_p)
    orders = make_orders(rng_o, n_orders, signup, products)

    customers.to_csv(out_dir / "customers_raw.csv", index=False)
    products.to_csv(out_dir / "products_raw.csv", index=False)
    orders.to_csv(out_dir / "orders_raw.csv", index=False)
    counts = {"customers": len(customers), "products": len(products), "orders": len(orders)}
    log.info("Generated raw files in %s: %s", out_dir, counts)
    return counts


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    generate()
