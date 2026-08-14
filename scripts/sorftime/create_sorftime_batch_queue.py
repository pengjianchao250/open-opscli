"""Create a resumable Sorftime queue from the Amazon Listing SQLite export."""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def load_items(database: Path, countries: list[str] | None = None) -> list[dict[str, Any]]:
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    query = """
        SELECT asin, item_sku, item_name, channel_name, site_name,
               sales_team_name, sales_team_user_name, country_iso_code,
               quantity, total_quantity, standard_price, sale_price,
               currency, asin_url
        FROM listings
        WHERE record_type = 'child'
          AND amazon_status = 'Active'
          AND asin IS NOT NULL
    """
    params: list[Any] = []
    if countries:
        placeholders = ",".join("?" for _ in countries)
        query += f" AND country_iso_code IN ({placeholders})"
        params.extend(countries)
    query += " ORDER BY country_iso_code, channel_name, asin"
    rows = [dict(row) for row in connection.execute(query, params)]
    connection.close()
    # A child ASIN should only occur once in the queue for a site.
    deduped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        deduped[(row["asin"], row["country_iso_code"] or "Unknown")] = row
    return list(deduped.values())


def create_queue(database: Path, output_dir: Path, batch_size: int, countries: list[str] | None = None) -> dict[str, Any]:
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    items = load_items(database, countries)
    output_dir.mkdir(parents=True, exist_ok=True)
    batches_dir = output_dir / "batches"
    batches_dir.mkdir(exist_ok=True)
    for old in batches_dir.glob("batch-*.json"):
        old.unlink()
    state_path = output_dir / "state.sqlite"
    if state_path.exists():
        state_path.unlink()
    state = sqlite3.connect(state_path)
    state.execute("""CREATE TABLE queue_items (
        asin TEXT NOT NULL, site TEXT NOT NULL, batch_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
        run_dir TEXT, error TEXT, updated_at TEXT NOT NULL,
        PRIMARY KEY (asin, site)
    )""")
    state.execute("CREATE INDEX idx_queue_status ON queue_items(status)")
    now = datetime.now(timezone.utc).isoformat()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in items:
        site = item.get("country_iso_code") or "Unknown"
        grouped.setdefault(site, []).append(item)
    batch_index = 0
    all_batches: list[dict[str, Any]] = []
    for site, site_items in grouped.items():
        for offset in range(0, len(site_items), batch_size):
            batch_index += 1
            batch_id = f"batch-{batch_index:03d}"
            batch_items = site_items[offset : offset + batch_size]
            batch = {
                "batch_id": batch_id,
                "site": site,
                "status": "pending",
                "item_count": len(batch_items),
                "items": batch_items,
            }
            (batches_dir / f"{batch_id}.json").write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
            all_batches.append({"batch_id": batch_id, "site": site, "status": "pending", "item_count": len(batch_items)})
            state.executemany(
                "INSERT INTO queue_items (asin, site, batch_id, updated_at) VALUES (?, ?, ?, ?)",
                [(item["asin"], site, batch_id, now) for item in batch_items],
            )
    state.commit()
    state.close()

    with (output_dir / "items.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["asin", "site", "batch_id", "item_sku", "item_name", "channel_name", "quantity", "standard_price"])
        writer.writeheader()
        for batch in all_batches:
            data = json.loads((batches_dir / f"{batch['batch_id']}.json").read_text(encoding="utf-8"))
            for item in data["items"]:
                writer.writerow({"asin": item["asin"], "site": data["site"], "batch_id": batch["batch_id"], "item_sku": item.get("item_sku"), "item_name": item.get("item_name"), "channel_name": item.get("channel_name"), "quantity": item.get("quantity"), "standard_price": item.get("standard_price")})
    manifest = {
        "created_at": now,
        "source_database": str(database),
        "batch_size": batch_size,
        "countries": countries or "all",
        "total_items": len(items),
        "batch_count": len(all_batches),
        "sites": {site: sum(batch["item_count"] for batch in all_batches if batch["site"] == site) for site in grouped},
        "batches": all_batches,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"total_items": len(items), "batch_count": len(all_batches), "sites": manifest["sites"], "output_dir": str(output_dir)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a resumable Sorftime ASIN batch queue")
    parser.add_argument("--database", type=Path, default=Path("test-data/sorftime/amazon_listing_1134/amazon_listing_1134_processed/amazon_listing_1134.sqlite"))
    parser.add_argument("--output-dir", type=Path, default=Path("test-data/sorftime/batch-queue"))
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--country", action="append", dest="countries", help="Limit to one or more marketplace codes, e.g. --country US")
    args = parser.parse_args()
    print(json.dumps(create_queue(args.database, args.output_dir, args.batch_size, args.countries), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
