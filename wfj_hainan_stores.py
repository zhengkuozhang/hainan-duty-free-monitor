"""抓取王府井集团官网公开的海南免税门店。"""

from __future__ import annotations

import logging
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from cdf_hainan_stores import Store, clean_text


BASE_URL = "https://www.wfj.com.cn"
LIST_URL = f"{BASE_URL}/store/index.html"
USER_AGENT = "Mozilla/5.0 (compatible; HainanDutyFreeResearchBot/0.2; local-research)"


def parse_store_list(html: str) -> list[Store]:
    soup = BeautifulSoup(html, "html.parser")
    stores: list[Store] = []
    for item in soup.select("#storeList > li"):
        name_node = item.select_one("h3")
        address_node = item.select_one("p")
        link_node = item.select_one("a[href]")
        if not name_node or not address_node or not link_node:
            continue
        name = clean_text(name_node.get_text(" ", strip=True))
        address = clean_text(address_node.get_text(" ", strip=True))
        if "海南" not in address or "免税" not in name:
            continue
        detail_url = urljoin(BASE_URL, link_node.get("href", ""))
        stores.append(
            Store(
                name=name,
                address=address,
                phone="",
                detail_url=detail_url,
                image_url="",
                source_id="wfj",
                source_name="王府井集团官方网站",
                source_url=LIST_URL,
            )
        )
    return stores


def parse_detail_image(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    image = soup.select_one(".store_banner a[data-img], .leftimg img[src], img[alt*='免税港']")
    if not image:
        return ""
    raw = image.get("data-img") or image.get("src") or ""
    return urljoin(BASE_URL, raw.split(";jsessionid=")[0])


def crawl(timeout: float = 15.0) -> list[Store]:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9"})
    logging.info("正在抓取王府井官网门店导览")
    response = session.get(LIST_URL, timeout=timeout)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    stores = parse_store_list(response.text)
    enriched: list[Store] = []
    for store in stores:
        detail = session.get(store.detail_url, timeout=timeout)
        detail.raise_for_status()
        detail.encoding = detail.apparent_encoding or "utf-8"
        enriched.append(
            Store(
                **{**store.__dict__, "image_url": parse_detail_image(detail.text)}
            )
        )
    return enriched
