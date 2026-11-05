#!/usr/bin/env python3
"""抓取中免集团官网公开的海南门店信息。"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.cdfg.com.cn"
LIST_URL = f"{BASE_URL}/StoreInformation.html"
USER_AGENT = (
    "Mozilla/5.0 (compatible; HainanDutyFreeResearchBot/0.1; "
    "+https://www.cdfg.com.cn/StoreInformation.html)"
)


@dataclass(frozen=True)
class Store:
    name: str
    address: str
    phone: str
    detail_url: str
    image_url: str
    source_id: str = "cdf"
    source_name: str = "中国中免集团官网"
    source_url: str = LIST_URL


def clean_text(value: str) -> str:
    return " ".join(value.replace("<br/>", " ").split())


def parse_stores(html: str, province: str = "海南") -> list[Store]:
    """解析门店列表 HTML，只返回地址中包含指定省份的门店。"""
    soup = BeautifulSoup(html, "html.parser")
    stores: list[Store] = []

    for item in soup.select("#list_box .item"):
        name_node = item.select_one(".right label")
        address_node = item.select_one(".right > a > p")
        phone_node = item.select_one(".right > a > i")
        detail_node = item.select_one(".right > a[href]")
        image_node = item.select_one(".left img[src]")

        if not name_node or not address_node or not detail_node:
            logging.warning("跳过字段不完整的门店条目")
            continue

        address = clean_text(address_node.get_text(" ", strip=True))
        if province and province not in address:
            continue

        stores.append(
            Store(
                name=clean_text(name_node.get_text(" ", strip=True)),
                address=address,
                phone=clean_text(phone_node.get_text(" ", strip=True))
                if phone_node
                else "",
                detail_url=urljoin(BASE_URL, detail_node.get("href", "")),
                image_url=urljoin(BASE_URL, image_node.get("src", ""))
                if image_node
                else "",
            )
        )

    return stores


def fetch_page(session: requests.Session, page: int, timeout: float) -> str:
    response = session.get(
        LIST_URL,
        params={"classify": "", "title": "", "city": "", "page": page},
        timeout=timeout,
    )
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return response.text


def crawl(
    max_pages: int = 7,
    delay: float = 1.5,
    timeout: float = 15.0,
    province: str = "海南",
) -> list[Store]:
    """低频抓取列表页，并按详情链接去重。"""
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"})

    found: dict[str, Store] = {}
    seen_page_urls: set[tuple[str, ...]] = set()

    for page in range(1, max_pages + 1):
        logging.info("正在抓取第 %s/%s 页", page, max_pages)
        html = fetch_page(session, page, timeout)
        all_on_page = parse_stores(html, province="")
        page_urls = tuple(store.detail_url for store in all_on_page)

        if not page_urls:
            logging.info("第 %s 页没有门店，停止抓取", page)
            break
        if page_urls in seen_page_urls:
            logging.info("第 %s 页与之前页面重复，停止抓取", page)
            break
        seen_page_urls.add(page_urls)

        for store in all_on_page:
            if not province or province in store.address:
                found[store.detail_url] = store

        if page < max_pages:
            time.sleep(delay + random.uniform(0, min(delay * 0.2, 0.5)))

    return sorted(found.values(), key=lambda store: store.name)


def write_json(stores: Iterable[Store], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(store) for store in stores], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_csv(stores: Iterable[Store], path: Path) -> None:
    rows = [asdict(store) for store in stores]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(Store.__annotations__))
        writer.writeheader()
        writer.writerows(rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="抓取中免集团官网公开的海南门店信息")
    parser.add_argument("--max-pages", type=int, default=7, help="最多抓取页数（默认：7）")
    parser.add_argument("--delay", type=float, default=1.5, help="请求间隔秒数（默认：1.5）")
    parser.add_argument("--timeout", type=float, default=15.0, help="单次请求超时（默认：15）")
    parser.add_argument("--province", default="海南", help="地址筛选词（默认：海南）")
    parser.add_argument("--output-dir", type=Path, default=Path("output"), help="输出目录")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.max_pages < 1 or args.delay < 0 or args.timeout <= 0:
        print("参数错误：max-pages >= 1、delay >= 0、timeout > 0", file=sys.stderr)
        return 2

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        stores = crawl(args.max_pages, args.delay, args.timeout, args.province)
    except requests.RequestException as exc:
        logging.error("请求失败：%s", exc)
        return 1

    json_path = args.output_dir / "cdf_hainan_stores.json"
    csv_path = args.output_dir / "cdf_hainan_stores.csv"
    write_json(stores, json_path)
    write_csv(stores, csv_path)
    print(f"完成：找到 {len(stores)} 家门店")
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
