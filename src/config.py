"""Central configuration: paths, data-generation settings and database URL."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote_plus

ROOT = Path(__file__).resolve().parent.parent

try:  # .env is optional
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:  # pragma: no cover
    pass

DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
SQL_DIR = ROOT / "sql"
DOCS_DIR = ROOT / "docs"
CHARTS_DIR = DOCS_DIR / "charts"
EXPORT_DIR = ROOT / "powerbi" / "exports"

# Synthetic data settings
SEED = 42
N_CUSTOMERS = 60_000
N_ORDERS = 120_000
START_DATE = "2023-01-01"
END_DATE = "2025-12-31"


def get_db_url(backend: str | None = None) -> str:
    """Build the SQLAlchemy URL. backend = 'mysql' (default) or 'sqlite'."""
    explicit = os.getenv("DB_URL")
    backend = (backend or os.getenv("DB_BACKEND", "mysql")).lower()
    if backend == "sqlite":
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{DATA_DIR / 'sales.db'}"
    if explicit:
        return explicit
    user = os.getenv("DB_USER", "root")
    password = quote_plus(os.getenv("DB_PASSWORD", ""))
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "3306")
    name = os.getenv("DB_NAME", "sales_analytics")
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4"
