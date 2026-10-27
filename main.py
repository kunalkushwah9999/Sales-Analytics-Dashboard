"""One-command runner:  python main.py  [--backend sqlite] [--regen]

Steps: generate raw data (if missing) -> ETL into the database -> create SQL views
       -> export Power BI CSVs -> write docs/INSIGHTS.md and preview charts.
"""
from __future__ import annotations

import argparse
import logging
import time

from src import analysis, config, db, etl, generate_data


def main() -> None:
    p = argparse.ArgumentParser(description="Sales Analytics Dashboard pipeline")
    p.add_argument("--backend", choices=["mysql", "sqlite"], default=None,
                   help="database backend (default: DB_BACKEND from .env, else mysql)")
    p.add_argument("--regen", action="store_true", help="regenerate the raw CSV files")
    p.add_argument("--no-export", action="store_true", help="skip CSV export / charts")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s", datefmt="%H:%M:%S")
    log = logging.getLogger("main")
    t0 = time.time()

    if args.regen or not (config.RAW_DIR / "orders_raw.csv").exists():
        log.info("[1/4] Generating raw data ...")
        generate_data.generate()
    else:
        log.info("[1/4] Raw data found - skipping generation (use --regen to rebuild)")

    engine = db.get_engine(args.backend)
    log.info("[2/4] Running ETL ...")
    report = etl.run_etl(engine)

    log.info("[3/4] Creating SQL views ...")
    analysis.apply_views(engine)

    log.info("[4/4] Insights, exports and charts ...")
    insights = analysis.write_insights(engine)
    if not args.no_export:
        analysis.export_all(engine)
        analysis.make_charts(engine)

    k = insights["kpi"]
    print("\n" + "=" * 60)
    print(f"Loaded rows        : {report['loaded_rows']}")
    print(f"Revenue            : {analysis.fmt_inr(k['revenue'])}  ({int(k['orders']):,} completed orders)")
    print(f"Top 3 categories   : {', '.join(insights['top3_names'])} -> {insights['top3_share']}% of revenue")
    print(f"Repeat customers   : {insights['repeat_rate']}%")
    print(f"Done in {time.time() - t0:.1f}s  |  see docs/INSIGHTS.md and powerbi/exports/")
    print("=" * 60)


if __name__ == "__main__":
    main()
