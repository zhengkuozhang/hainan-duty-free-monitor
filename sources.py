"""多来源采集编排与来源目录。"""

from __future__ import annotations

import time

from cdf_hainan_stores import Store, crawl as crawl_cdf
from wfj_hainan_stores import crawl as crawl_wfj


SOURCE_CATALOG = [
    {"id": "cdf", "name": "中国中免集团官网", "url": "https://www.cdfg.com.cn/StoreInformation.html", "status": "active"},
    {"id": "wfj", "name": "王府井集团官方网站", "url": "https://www.wfj.com.cn/store/index.html", "status": "active"},
    {"id": "htdf", "name": "海旅免税原官网域名", "url": "http://www.htdf.com.cn/", "status": "retired", "note": "域名已变为出售页，禁止采集"},
    {"id": "cnscc", "name": "中服免税原官网域名", "url": "https://www.cnscc.com/", "status": "blocked", "note": "域名当前内容异常，禁止采集"},
]


COLLECTORS = {
    "cdf": lambda: crawl_cdf(max_pages=7, delay=1.5, timeout=15.0, province="海南"),
    "wfj": lambda: crawl_wfj(timeout=15.0),
}


def crawl_all() -> tuple[list[Store], list[dict]]:
    """独立执行各来源；一个来源失败不会阻止其他来源更新。"""
    stores: list[Store] = []
    results: list[dict] = []
    for source_id, collector in COLLECTORS.items():
        started = time.monotonic()
        try:
            source_stores = collector()
            if not source_stores:
                raise RuntimeError("未返回符合条件的门店")
            stores.extend(source_stores)
            results.append(
                {
                    "source_id": source_id,
                    "status": "success",
                    "count": len(source_stores),
                    "duration_ms": round((time.monotonic() - started) * 1000),
                    "error": None,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "source_id": source_id,
                    "status": "failed",
                    "count": 0,
                    "duration_ms": round((time.monotonic() - started) * 1000),
                    "error": str(exc)[:500],
                }
            )
    unique = {store.detail_url: store for store in stores}
    return sorted(unique.values(), key=lambda store: (store.source_id, store.name)), results
