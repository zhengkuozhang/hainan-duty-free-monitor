"""cdf海南免税商城公开商品目录采集器。"""

from __future__ import annotations

import csv
import json
import os
import time
from dataclasses import asdict, dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable

import requests


API_URL = "https://www.cdfhnmall.com/api/overseas/products/search"
DETAIL_URL = "https://www.cdfhnmall.com/api/overseas/products/v2/{product_id}"
MALL_URL = "https://www.cdfhnmall.com"
CATALOG_URL = f"{MALL_URL}/product-list.html"
PUBLIC_HEADERS = {
    "apiVersion": "2.0",
    "language": "zh-CN",
    "channel": "pc",
    "subsiteId": "10",
    "Accept": "application/json, text/plain, */*",
    "Referer": CATALOG_URL,
    "User-Agent": "Mozilla/5.0 (compatible; CDF-Public-Catalog-Monitor/1.0)",
}


APPKEY_PATH = Path(__file__).resolve().parent / ".catalog-appkey"


def catalog_appkey() -> str:
    value = os.environ.get("CDF_APPKEY", "").strip()
    if not value:
        try:
            value = APPKEY_PATH.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            value = ""
    if not value:
        raise ValueError("请先配置 CDF_APPKEY 环境变量或本机 .catalog-appkey 文件")
    if any(ord(char) < 32 for char in value):
        raise ValueError("商城 Appkey 配置格式无效")
    return value


def _money(value) -> float | None:
    if isinstance(value, dict):
        value = value.get("value")
    if value in (None, ""):
        return None
    try:
        return float(Decimal(str(value).replace(",", "")))
    except (InvalidOperation, ValueError):
        return None


def _labels(value) -> list[str]:
    if not isinstance(value, list):
        return []
    labels = []
    for item in value:
        if isinstance(item, str):
            label = item
        elif isinstance(item, dict):
            label = item.get("name") or item.get("title") or item.get("label") or item.get("text")
        else:
            label = None
        if label and str(label) not in labels:
            labels.append(str(label))
    return labels


@dataclass(frozen=True)
class Product:
    product_id: str
    goods_id: str
    style_id: str
    product_code: str
    name: str
    brand: str
    brand_en: str
    category_id: str
    category_name: str
    category_path: str
    spec: str
    price: float | None
    price_label: str
    contrast_price: float | None
    discount_price: float | None
    estimate_price: float | None
    stock_count: int | None
    is_sellable: bool
    public_sales_count: int | None
    public_sell_count: int | None
    promotion_tags: list[str]
    has_gov_coupon: bool
    image_url: str
    product_url: str
    description: str


def parse_product(item: dict, category_name: str = "", category_path: str = "") -> Product:
    """把官网公开 JSON 映射为稳定的商品模型。"""
    sales_price = item.get("salesPrice") or {}
    tags = _labels(item.get("activityTags"))
    tags += [label for label in _labels(item.get("badges")) if label not in tags]
    stock = item.get("count")
    try:
        stock = int(stock) if stock is not None else None
    except (TypeError, ValueError):
        stock = None
    product_id = str(item.get("productId") or item.get("id") or "")
    path = item.get("productUrl") or (f"/product/{product_id}" if product_id else "")
    url = path if str(path).startswith("http") else f"{MALL_URL}{path}"
    return Product(
        product_id=product_id,
        goods_id=str(item.get("goodsId") or ""),
        style_id=str(item.get("styleId") or ""),
        product_code=str(item.get("productCode") or ""),
        name=str(item.get("name") or "").strip(),
        brand=str(item.get("brand") or "").strip(),
        brand_en=str(item.get("brandEN") or "").strip(),
        category_id=str(item.get("categoryId") or ""),
        category_name=category_name or str(item.get("categoryName") or "").strip(),
        category_path=category_path,
        spec=str(item.get("spec") or "").strip(),
        price=_money(sales_price),
        price_label=str(sales_price.get("name") or "公开价"),
        contrast_price=_money(item.get("contrastPrice")),
        discount_price=_money(item.get("discountPrice")),
        estimate_price=_money(item.get("estimatePrice")),
        stock_count=stock,
        is_sellable=bool(item.get("isSellable")),
        public_sales_count=int(item["salesCount"]) if str(item.get("salesCount", "")).isdigit() else None,
        public_sell_count=int(item["sellCount"]) if str(item.get("sellCount", "")).isdigit() else None,
        promotion_tags=tags,
        has_gov_coupon=bool(item.get("showGovCoupon")),
        image_url=str(item.get("pic") or ""),
        product_url=url,
        description=str(item.get("description") or "").strip(),
    )


def crawl_products(
    max_pages: int = 5,
    page_size: int = 24,
    delay: float = 1.2,
    has_stock: bool = True,
    session=None,
    on_page: Callable[[int, int], None] | None = None,
    category_cache: dict[str, tuple[str, str]] | None = None,
    image_cache: dict[str, str] | None = None,
    enrich_categories: bool = True,
) -> tuple[list[Product], dict]:
    """低频抓取公开目录；max_pages/page_size 是强制安全上限。"""
    max_pages = max(1, min(int(max_pages), 50))
    page_size = max(1, min(int(page_size), 50))
    delay = max(0.0, min(float(delay), 10.0))
    headers = {**PUBLIC_HEADERS, "Appkey": catalog_appkey()}
    client = session or requests.Session()
    products: dict[str, Product] = {}
    catalog_total = 0
    pages_fetched = 0
    returned_per_page: list[int] = []
    for page in range(1, max_pages + 1):
        response = client.get(
            API_URL,
            params={"c": 1, "hs": str(has_stock).lower(), "pn": page, "ps": page_size, "s": 0},
            headers=headers,
            timeout=(8, 25),
        )
        response.raise_for_status()
        payload = response.json()
        body = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        items = body.get("items") or []
        if not isinstance(items, list):
            raise ValueError("官网返回的商品列表格式已变化")
        catalog_total = int(body.get("total") or catalog_total or 0)
        pages_fetched += 1
        returned_per_page.append(len(items))
        for item in items:
            product = parse_product(item)
            if product.product_id and product.name:
                products[product.product_id] = product
        if on_page:
            on_page(page, len(products))
        # 官网当前会把实际每页数量限制为 20，不能用“少于请求 page_size”判断末页。
        if not items or (catalog_total and page * len(items) >= catalog_total):
            break
        if page < max_pages and delay:
            time.sleep(delay)
    if not products:
        raise ValueError("官网未返回有效商品，已保留原有数据")
    cache = category_cache or {}
    cached_images = image_cache or {}
    lookups = 0
    if enrich_categories:
        representatives: dict[str, Product] = {}
        for product in products.values():
            if product.category_id and product.category_id not in cache:
                representatives.setdefault(product.category_id, product)
        detail_targets = {product.product_id: product for product in representatives.values()}
        for product in products.values():
            if not product.image_url and not cached_images.get(product.product_id):
                detail_targets[product.product_id] = product
        # 分类名称按叶级分类查询一次；缺失主图按商品补全。总量设置硬上限。
        for product in list(detail_targets.values())[:50]:
            response = client.get(
                DETAIL_URL.format(product_id=product.product_id),
                headers={**headers, "Referer": product.product_url},
                timeout=(8, 25),
            )
            response.raise_for_status()
            detail = response.json()
            raw_names = [str(detail.get(f"categoryNameLevel{level}") or "").strip() for level in (1, 2, 3)]
            names = []
            for name in raw_names:
                if name and (not names or names[-1] != name):
                    names.append(name)
            if names:
                cache[product.category_id] = (names[-1], " / ".join(names))
            pics = detail.get("pics") or detail.get("largePics") or []
            if pics and isinstance(pics, list):
                cached_images[product.product_id] = str(pics[0])
            lookups += 1
            if delay and lookups < len(detail_targets):
                time.sleep(min(delay, 1.0))
        products = {
            product_id: replace(product, category_name=cache.get(product.category_id, ("", ""))[0],
                                category_path=cache.get(product.category_id, ("", ""))[1],
                                image_url=product.image_url or cached_images.get(product_id, ""))
            for product_id, product in products.items()
        }
    return list(products.values()), {
        "catalog_total": catalog_total,
        "pages_fetched": pages_fetched,
        "requested_page_size": page_size,
        "returned_per_page": returned_per_page,
        "category_lookups": lookups,
        "has_stock": has_stock,
    }


def write_json(products: list[Product], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(p) for p in products], ensure_ascii=False, indent=2), encoding="utf-8")


def write_csv(products: list[Product], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for product in products:
        row = asdict(product)
        row["promotion_tags"] = " / ".join(product.promotion_tags)
        rows.append(row)
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
