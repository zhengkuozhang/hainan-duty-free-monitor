"""SQLite 持久化层：门店快照与采集任务历史。"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable

from cdf_hainan_stores import Store
from cdf_product_crawler import Product


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class DataStore:
    def __init__(self, path: Path):
        self.path = path

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS stores (
                    detail_url TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    address TEXT NOT NULL,
                    phone TEXT NOT NULL DEFAULT '',
                    image_url TEXT NOT NULL DEFAULT '',
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    source_id TEXT NOT NULL DEFAULT 'cdf',
                    source_name TEXT NOT NULL DEFAULT '中国中免集团官网',
                    source_url TEXT NOT NULL DEFAULT 'https://www.cdfg.com.cn/StoreInformation.html'
                );
                CREATE TABLE IF NOT EXISTS crawl_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL CHECK(status IN ('running','success','failed')),
                    found_count INTEGER NOT NULL DEFAULT 0,
                    added_count INTEGER NOT NULL DEFAULT 0,
                    updated_count INTEGER NOT NULL DEFAULT 0,
                    removed_count INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    source_results TEXT NOT NULL DEFAULT '[]',
                    run_type TEXT NOT NULL DEFAULT 'store'
                );
                CREATE INDEX IF NOT EXISTS idx_runs_started_at ON crawl_runs(started_at DESC);
                CREATE TABLE IF NOT EXISTS change_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id INTEGER,
                    changed_at TEXT NOT NULL,
                    change_type TEXT NOT NULL CHECK(change_type IN ('added','updated','removed')),
                    detail_url TEXT NOT NULL,
                    store_name TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    before_json TEXT,
                    after_json TEXT,
                    FOREIGN KEY(run_id) REFERENCES crawl_runs(id)
                );
                CREATE INDEX IF NOT EXISTS idx_changes_changed_at ON change_events(changed_at DESC);
                CREATE TABLE IF NOT EXISTS products (
                    product_id TEXT PRIMARY KEY,
                    goods_id TEXT NOT NULL DEFAULT '', style_id TEXT NOT NULL DEFAULT '',
                    product_code TEXT NOT NULL DEFAULT '', name TEXT NOT NULL,
                    brand TEXT NOT NULL DEFAULT '', brand_en TEXT NOT NULL DEFAULT '',
                    category_id TEXT NOT NULL DEFAULT '', category_name TEXT NOT NULL DEFAULT '',
                    category_path TEXT NOT NULL DEFAULT '', spec TEXT NOT NULL DEFAULT '',
                    price REAL, price_label TEXT NOT NULL DEFAULT '公开价',
                    contrast_price REAL, discount_price REAL, estimate_price REAL,
                    stock_count INTEGER, is_sellable INTEGER NOT NULL DEFAULT 0,
                    public_sales_count INTEGER, public_sell_count INTEGER,
                    promotion_tags TEXT NOT NULL DEFAULT '[]', has_gov_coupon INTEGER NOT NULL DEFAULT 0,
                    image_url TEXT NOT NULL DEFAULT '', product_url TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '', first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL, last_run_id INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand);
                CREATE INDEX IF NOT EXISTS idx_products_price ON products(price);
                CREATE INDEX IF NOT EXISTS idx_products_seen ON products(last_seen_at DESC);
                CREATE TABLE IF NOT EXISTS price_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, product_id TEXT NOT NULL,
                    run_id INTEGER, captured_at TEXT NOT NULL, price REAL,
                    stock_count INTEGER, is_sellable INTEGER NOT NULL,
                    FOREIGN KEY(product_id) REFERENCES products(product_id),
                    FOREIGN KEY(run_id) REFERENCES crawl_runs(id)
                );
                CREATE INDEX IF NOT EXISTS idx_price_product ON price_history(product_id, id DESC);
                CREATE TABLE IF NOT EXISTS product_change_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, run_id INTEGER,
                    changed_at TEXT NOT NULL, change_type TEXT NOT NULL,
                    product_id TEXT NOT NULL, product_name TEXT NOT NULL,
                    before_json TEXT, after_json TEXT,
                    FOREIGN KEY(run_id) REFERENCES crawl_runs(id)
                );
                CREATE INDEX IF NOT EXISTS idx_product_changes ON product_change_events(id DESC);
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(stores)").fetchall()}
            migrations = {
                "source_id": "ALTER TABLE stores ADD COLUMN source_id TEXT NOT NULL DEFAULT 'cdf'",
                "source_name": "ALTER TABLE stores ADD COLUMN source_name TEXT NOT NULL DEFAULT '中国中免集团官网'",
                "source_url": "ALTER TABLE stores ADD COLUMN source_url TEXT NOT NULL DEFAULT 'https://www.cdfg.com.cn/StoreInformation.html'",
            }
            for name, statement in migrations.items():
                if name not in columns:
                    connection.execute(statement)
            run_columns = {row["name"] for row in connection.execute("PRAGMA table_info(crawl_runs)").fetchall()}
            if "source_results" not in run_columns:
                connection.execute("ALTER TABLE crawl_runs ADD COLUMN source_results TEXT NOT NULL DEFAULT '[]'")
            if "run_type" not in run_columns:
                connection.execute("ALTER TABLE crawl_runs ADD COLUMN run_type TEXT NOT NULL DEFAULT 'store'")
            connection.execute("UPDATE crawl_runs SET run_type='product' WHERE source_results LIKE '%cdf_hainan_mall%'")
            product_columns = {row["name"] for row in connection.execute("PRAGMA table_info(products)").fetchall()}
            if "category_name" not in product_columns:
                connection.execute("ALTER TABLE products ADD COLUMN category_name TEXT NOT NULL DEFAULT ''")
            if "category_path" not in product_columns:
                connection.execute("ALTER TABLE products ADD COLUMN category_path TEXT NOT NULL DEFAULT ''")
            for row in connection.execute("SELECT product_id, category_path FROM products WHERE category_path!=''").fetchall():
                parts = []
                for part in (value.strip() for value in row["category_path"].split("/")):
                    if part and (not parts or parts[-1] != part):
                        parts.append(part)
                normalized = " / ".join(parts)
                if normalized != row["category_path"]:
                    connection.execute("UPDATE products SET category_path=? WHERE product_id=?", (normalized, row["product_id"]))
            # 清理旧版本首次补全分类时产生的“业务变更”假阳性。
            connection.execute(
                """DELETE FROM product_change_events
                WHERE change_type='updated' AND before_json IS NOT NULL AND after_json IS NOT NULL
                  AND COALESCE(json_extract(before_json,'$.category_name'),'')=''
                  AND COALESCE(json_extract(after_json,'$.category_name'),'')!=''
                  AND json_extract(before_json,'$.name')=json_extract(after_json,'$.name')
                  AND json_extract(before_json,'$.brand')=json_extract(after_json,'$.brand')
                  AND COALESCE(json_extract(before_json,'$.price'),-1)=COALESCE(json_extract(after_json,'$.price'),-1)
                  AND COALESCE(json_extract(before_json,'$.stock_count'),-1)=COALESCE(json_extract(after_json,'$.stock_count'),-1)
                  AND COALESCE(json_extract(before_json,'$.is_sellable'),-1)=COALESCE(json_extract(after_json,'$.is_sellable'),-1)"""
            )
            connection.execute(
                """UPDATE crawl_runs SET updated_count=(SELECT COUNT(*) FROM product_change_events e
                WHERE e.run_id=crawl_runs.id AND e.change_type='updated') WHERE run_type='product'"""
            )
            connection.commit()

    def category_map(self) -> dict[str, tuple[str, str]]:
        with closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT category_id, MAX(category_name), MAX(category_path) FROM products "
                "WHERE category_id!='' AND category_name!='' GROUP BY category_id"
            ).fetchall()
        return {row[0]: (row[1], row[2]) for row in rows}

    def image_map(self) -> dict[str, str]:
        with closing(self.connect()) as connection:
            rows = connection.execute("SELECT product_id, image_url FROM products WHERE image_url!=''").fetchall()
        return {row[0]: row[1] for row in rows}

    def upsert_products(self, products: Iterable[Product], run_id: int | None = None) -> dict[str, int]:
        """合并有限页商品快照；未抓取到的旧商品不会被误判为下架。"""
        incoming = {product.product_id: product for product in products}
        timestamp = now_iso()
        if not incoming:
            raise ValueError("不能用空商品结果更新数据库")
        with closing(self.connect()) as connection:
            old_rows = connection.execute("SELECT * FROM products").fetchall()
            old = {row["product_id"]: dict(row) for row in old_rows}
            added_ids = incoming.keys() - old.keys()
            tracked = (
                "name", "brand", "spec", "price", "contrast_price", "discount_price",
                "estimate_price", "stock_count", "is_sellable", "promotion_tags", "has_gov_coupon",
            )
            updated_ids = set()
            snapshot_changed_ids = set()
            for product_id in incoming.keys() & old.keys():
                values = asdict(incoming[product_id])
                values["promotion_tags"] = json.dumps(values["promotion_tags"], ensure_ascii=False)
                values["is_sellable"] = int(values["is_sellable"])
                values["has_gov_coupon"] = int(values["has_gov_coupon"])
                if any(old[product_id][key] != values[key] for key in tracked):
                    updated_ids.add(product_id)
                if any(old[product_id][key] != values[key] for key in ("price", "stock_count", "is_sellable")):
                    snapshot_changed_ids.add(product_id)
            connection.execute("BEGIN IMMEDIATE")
            for product_id, product in incoming.items():
                row = asdict(product)
                row["promotion_tags"] = json.dumps(row["promotion_tags"], ensure_ascii=False)
                row["is_sellable"] = int(row["is_sellable"])
                row["has_gov_coupon"] = int(row["has_gov_coupon"])
                connection.execute(
                    """INSERT INTO products (
                    product_id, goods_id, style_id, product_code, name, brand, brand_en,
                    category_id, category_name, category_path, spec, price, price_label, contrast_price, discount_price,
                    estimate_price, stock_count, is_sellable, public_sales_count, public_sell_count,
                    promotion_tags, has_gov_coupon, image_url, product_url, description,
                    first_seen_at, last_seen_at, last_run_id)
                    VALUES (:product_id,:goods_id,:style_id,:product_code,:name,:brand,:brand_en,
                    :category_id,:category_name,:category_path,:spec,:price,:price_label,:contrast_price,:discount_price,
                    :estimate_price,:stock_count,:is_sellable,:public_sales_count,:public_sell_count,
                    :promotion_tags,:has_gov_coupon,:image_url,:product_url,:description,
                    :first_seen_at,:last_seen_at,:last_run_id)
                    ON CONFLICT(product_id) DO UPDATE SET
                    goods_id=excluded.goods_id, style_id=excluded.style_id, product_code=excluded.product_code,
                    name=excluded.name, brand=excluded.brand, brand_en=excluded.brand_en,
                    category_id=excluded.category_id, category_name=excluded.category_name,
                    category_path=excluded.category_path, spec=excluded.spec, price=excluded.price,
                    price_label=excluded.price_label, contrast_price=excluded.contrast_price,
                    discount_price=excluded.discount_price, estimate_price=excluded.estimate_price,
                    stock_count=excluded.stock_count, is_sellable=excluded.is_sellable,
                    public_sales_count=excluded.public_sales_count, public_sell_count=excluded.public_sell_count,
                    promotion_tags=excluded.promotion_tags, has_gov_coupon=excluded.has_gov_coupon,
                    image_url=excluded.image_url, product_url=excluded.product_url,
                    description=excluded.description, last_seen_at=excluded.last_seen_at,
                    last_run_id=excluded.last_run_id""",
                    {**row, "first_seen_at": old.get(product_id, {}).get("first_seen_at", timestamp),
                     "last_seen_at": timestamp, "last_run_id": run_id},
                )
                if product_id in added_ids or product_id in snapshot_changed_ids:
                    connection.execute(
                        "INSERT INTO price_history (product_id,run_id,captured_at,price,stock_count,is_sellable) VALUES (?,?,?,?,?,?)",
                        (product_id, run_id, timestamp, product.price, product.stock_count, int(product.is_sellable)),
                    )
                if product_id in added_ids or product_id in updated_ids:
                    connection.execute(
                        """INSERT INTO product_change_events
                        (run_id,changed_at,change_type,product_id,product_name,before_json,after_json)
                        VALUES (?,?,?,?,?,?,?)""",
                        (run_id, timestamp, "added" if product_id in added_ids else "updated", product_id,
                         product.name, json.dumps(old.get(product_id), ensure_ascii=False) if product_id in old else None,
                         json.dumps(row, ensure_ascii=False)),
                    )
            connection.commit()
        return {"added": len(added_ids), "updated": len(updated_ids), "removed": 0}

    def list_products(self, search: str = "", brand: str = "", category: str = "", stock: str = "all",
                      sort: str = "updated", page: int = 1, page_size: int = 24) -> dict:
        page, page_size = max(1, int(page)), max(1, min(int(page_size), 100))
        clauses, params = [], []
        if search:
            clauses.append("(name LIKE ? OR brand LIKE ? OR product_code LIKE ?)")
            term = f"%{search[:80]}%"
            params.extend([term, term, term])
        if brand:
            clauses.append("brand = ?")
            params.append(brand[:80])
        if category:
            clauses.append("category_name = ?")
            params.append(category[:80])
        if stock == "available":
            clauses.append("is_sellable = 1 AND COALESCE(stock_count,0) > 0")
        elif stock == "soldout":
            clauses.append("(is_sellable = 0 OR COALESCE(stock_count,0) <= 0)")
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        orders = {"updated": "last_seen_at DESC", "price_asc": "price IS NULL, price ASC",
                  "price_desc": "price IS NULL, price DESC", "stock_desc": "stock_count DESC"}
        order = orders.get(sort, orders["updated"])
        with closing(self.connect()) as connection:
            total = connection.execute(f"SELECT COUNT(*) FROM products{where}", params).fetchone()[0]
            rows = connection.execute(
                f"SELECT * FROM products{where} ORDER BY {order}, product_id LIMIT ? OFFSET ?",
                [*params, page_size, (page - 1) * page_size],
            ).fetchall()
        items = []
        for raw in rows:
            item = dict(raw)
            item["is_sellable"] = bool(item["is_sellable"])
            item["has_gov_coupon"] = bool(item["has_gov_coupon"])
            try:
                item["promotion_tags"] = json.loads(item["promotion_tags"] or "[]")
            except json.JSONDecodeError:
                item["promotion_tags"] = []
            items.append(item)
        return {"items": items, "total": total, "page": page, "page_size": page_size,
                "pages": (total + page_size - 1) // page_size}

    def product_stats(self) -> dict:
        with closing(self.connect()) as connection:
            row = connection.execute("""SELECT COUNT(*) total, COUNT(DISTINCT NULLIF(brand,'')) brands,
                SUM(CASE WHEN is_sellable=1 AND COALESCE(stock_count,0)>0 THEN 1 ELSE 0 END) available,
                SUM(CASE WHEN has_gov_coupon=1 OR promotion_tags!='[]' THEN 1 ELSE 0 END) promoted,
                MIN(price) min_price, MAX(price) max_price, MAX(last_seen_at) updated_at FROM products""").fetchone()
            brands = [r[0] for r in connection.execute(
                "SELECT DISTINCT brand FROM products WHERE brand!='' ORDER BY brand LIMIT 200").fetchall()]
            categories = [r[0] for r in connection.execute(
                "SELECT DISTINCT category_name FROM products WHERE category_name!='' ORDER BY category_name LIMIT 200").fetchall()]
        return {**dict(row), "brands_list": brands, "categories_list": categories}

    def price_history(self, product_id: str, limit: int = 50) -> list[dict]:
        with closing(self.connect()) as connection:
            rows = connection.execute("SELECT captured_at,price,stock_count,is_sellable FROM price_history WHERE product_id=? ORDER BY id DESC LIMIT ?",
                                      (product_id, max(1, min(limit, 200)))).fetchall()
        return [dict(row) for row in rows]

    def recent_product_changes(self, limit: int = 30) -> list[dict]:
        with closing(self.connect()) as connection:
            rows = connection.execute("SELECT id,run_id,changed_at,change_type,product_id,product_name FROM product_change_events ORDER BY id DESC LIMIT ?",
                                      (max(1, min(limit, 100)),)).fetchall()
        return [dict(row) for row in rows]

    def import_json_if_empty(self, json_path: Path) -> None:
        if not json_path.exists() or self.list_stores():
            return
        rows = json.loads(json_path.read_text(encoding="utf-8"))
        stores = [Store(**row) for row in rows]
        self.replace_stores(stores)

    def list_stores(self) -> list[dict]:
        with closing(self.connect()) as connection:
            rows = connection.execute(
                "SELECT name, address, phone, detail_url, image_url, source_id, source_name, source_url, first_seen_at, last_seen_at "
                "FROM stores ORDER BY name"
            ).fetchall()
        return [dict(row) for row in rows]

    def replace_stores(self, stores: Iterable[Store]) -> dict[str, int]:
        source_ids = {store.source_id for store in stores}
        return self.replace_source_stores(stores, source_ids)

    def replace_source_stores(self, stores: Iterable[Store], source_ids: set[str], run_id: int | None = None) -> dict[str, int]:
        """仅替换成功来源的数据，失败来源的旧快照保持不变。"""
        incoming = {store.detail_url: store for store in stores}
        timestamp = now_iso()
        with closing(self.connect()) as connection:
            old_rows = connection.execute(
                "SELECT detail_url, name, address, phone, image_url, source_id, source_name, source_url, first_seen_at FROM stores"
            ).fetchall()
            old = {row["detail_url"]: dict(row) for row in old_rows}
            scoped_old = {url: row for url, row in old.items() if row["source_id"] in source_ids}
            added = len(incoming.keys() - scoped_old.keys())
            removed = len(scoped_old.keys() - incoming.keys())
            updated = 0
            updated_urls: set[str] = set()
            for url in incoming.keys() & old.keys():
                values = asdict(incoming[url])
                if any(old[url][key] != values[key] for key in ("name", "address", "phone", "image_url", "source_id", "source_name", "source_url")):
                    updated += 1
                    updated_urls.add(url)

            connection.execute("BEGIN IMMEDIATE")
            events = []
            for url in incoming.keys() - scoped_old.keys():
                item = asdict(incoming[url])
                events.append((run_id, timestamp, "added", url, item["name"], item["source_id"], None, json.dumps(item, ensure_ascii=False)))
            for url in scoped_old.keys() - incoming.keys():
                item = scoped_old[url]
                events.append((run_id, timestamp, "removed", url, item["name"], item["source_id"], json.dumps(item, ensure_ascii=False), None))
            for url in updated_urls:
                before, after = old[url], asdict(incoming[url])
                events.append((run_id, timestamp, "updated", url, after["name"], after["source_id"], json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False)))
            if events:
                connection.executemany(
                    """INSERT INTO change_events
                    (run_id, changed_at, change_type, detail_url, store_name, source_id, before_json, after_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    events,
                )
            if source_ids:
                placeholders = ",".join("?" for _ in source_ids)
                connection.execute(f"DELETE FROM stores WHERE source_id IN ({placeholders})", tuple(source_ids))
            connection.executemany(
                """
                INSERT INTO stores
                    (detail_url, name, address, phone, image_url, first_seen_at, last_seen_at, source_id, source_name, source_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        store.detail_url,
                        store.name,
                        store.address,
                        store.phone,
                        store.image_url,
                        old.get(store.detail_url, {}).get("first_seen_at", timestamp),
                        timestamp,
                        store.source_id,
                        store.source_name,
                        store.source_url,
                    )
                    for store in incoming.values()
                ],
            )
            connection.commit()
        return {"added": added, "updated": updated, "removed": removed}

    def start_run(self, run_type: str = "store") -> int:
        if run_type not in {"store", "product"}:
            raise ValueError("未知采集任务类型")
        with closing(self.connect()) as connection:
            cursor = connection.execute(
                "INSERT INTO crawl_runs (started_at, status, run_type) VALUES (?, 'running', ?)", (now_iso(), run_type)
            )
            connection.commit()
            return int(cursor.lastrowid)

    def finish_run(self, run_id: int, count: int, changes: dict[str, int], source_results: list[dict] | None = None) -> None:
        with closing(self.connect()) as connection:
            connection.execute(
                """
                UPDATE crawl_runs SET finished_at=?, status='success', found_count=?,
                    added_count=?, updated_count=?, removed_count=?, source_results=? WHERE id=?
                """,
                (
                    now_iso(), count, changes["added"], changes["updated"], changes["removed"],
                    json.dumps(source_results or [], ensure_ascii=False), run_id,
                ),
            )
            connection.commit()

    def fail_run(self, run_id: int, error: str, source_results: list[dict] | None = None) -> None:
        with closing(self.connect()) as connection:
            connection.execute(
                "UPDATE crawl_runs SET finished_at=?, status='failed', error=?, source_results=? WHERE id=?",
                (now_iso(), error[:800], json.dumps(source_results or [], ensure_ascii=False), run_id),
            )
            connection.commit()

    def recent_runs(self, limit: int = 10, run_type: str | None = None) -> list[dict]:
        limit = max(1, min(limit, 50))
        with closing(self.connect()) as connection:
            if run_type:
                rows = connection.execute(
                    "SELECT * FROM crawl_runs WHERE run_type=? ORDER BY id DESC LIMIT ?", (run_type, limit)
                ).fetchall()
            else:
                rows = connection.execute("SELECT * FROM crawl_runs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        results = []
        for row in rows:
            item = dict(row)
            try:
                item["source_results"] = json.loads(item.get("source_results") or "[]")
            except json.JSONDecodeError:
                item["source_results"] = []
            results.append(item)
        return results

    def latest_run(self, run_type: str | None = None) -> dict | None:
        runs = self.recent_runs(1, run_type)
        return runs[0] if runs else None

    def recover_interrupted_runs(self) -> int:
        """服务异常退出后，将遗留的 running 任务标记为失败。"""
        with closing(self.connect()) as connection:
            cursor = connection.execute(
                """
                UPDATE crawl_runs SET status='failed', finished_at=?,
                    error='服务在任务完成前停止，已自动恢复状态'
                WHERE status='running'
                """,
                (now_iso(),),
            )
            connection.commit()
            return cursor.rowcount

    def recent_changes(self, limit: int = 30) -> list[dict]:
        limit = max(1, min(limit, 100))
        with closing(self.connect()) as connection:
            rows = connection.execute(
                """SELECT id, run_id, changed_at, change_type, detail_url, store_name, source_id
                FROM change_events ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def backup_to(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as source, closing(sqlite3.connect(destination)) as target:
            source.backup(target)
        return destination
