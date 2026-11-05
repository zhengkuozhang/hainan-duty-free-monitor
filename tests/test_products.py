import tempfile
import os
from unittest.mock import patch
import unittest
from pathlib import Path

from cdf_product_crawler import Product, crawl_products, parse_product
from data_store import DataStore


SAMPLE = {
    "productId": 2666966, "goodsId": 2545684, "styleId": 2667196,
    "productCode": "C114293HK", "name": "兰蔻「超修小黑瓶」精华100ml",
    "brand": "兰蔻", "brandEN": "LANCÔME", "categoryId": 228593,
    "spec": "100ml", "salesPrice": {"name": "免税价", "value": "1445.00"},
    "count": 5, "isSellable": True, "salesCount": 100, "sellCount": 0,
    "activityTags": [{"name": "限时优惠"}], "showGovCoupon": False,
    "pic": "https://pic.cdfgsanya.com/example.png", "productUrl": "/product/2666966",
}


class FakeResponse:
    def __init__(self, payload): self.payload = payload
    def raise_for_status(self): return None
    def json(self): return self.payload


class FakeSession:
    def __init__(self): self.calls = []
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse({"items": [SAMPLE], "total": 1})


class CategorySession(FakeSession):
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if "/products/v2/" in url:
            return FakeResponse({"categoryNameLevel1": "护肤", "categoryNameLevel2": "面部护理", "categoryNameLevel3": "精华"})
        return FakeResponse({"items": [SAMPLE], "total": 1})


class ProductCrawlerTest(unittest.TestCase):
    def setUp(self):
        appkey_patch = patch.dict(os.environ, {"CDF_APPKEY": "test-catalog-appkey"})
        appkey_patch.start()
        self.addCleanup(appkey_patch.stop)

    def test_parse_public_product_fields(self):
        product = parse_product(SAMPLE)
        self.assertEqual(product.product_id, "2666966")
        self.assertEqual(product.price, 1445.0)
        self.assertEqual(product.stock_count, 5)
        self.assertEqual(product.promotion_tags, ["限时优惠"])

    def test_limits_and_required_headers(self):
        session = FakeSession()
        products, meta = crawl_products(max_pages=999, page_size=99, delay=0, session=session)
        self.assertEqual(len(products), 1)
        self.assertEqual(meta["pages_fetched"], 1)
        self.assertEqual(session.calls[0][1]["params"]["ps"], 50)
        self.assertEqual(session.calls[0][1]["headers"]["Appkey"], "test-catalog-appkey")

    def test_enriches_category_once_per_leaf_category(self):
        session = CategorySession()
        products, meta = crawl_products(max_pages=1, page_size=20, delay=0, session=session)
        self.assertEqual(products[0].category_name, "精华")
        self.assertEqual(products[0].category_path, "护肤 / 面部护理 / 精华")
        self.assertEqual(meta["category_lookups"], 1)


class ProductDataStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = DataStore(Path(self.temp.name) / "test.db")
        self.db.initialize()
        self.product = parse_product(SAMPLE)

    def tearDown(self): self.temp.cleanup()

    def test_upsert_filters_and_price_history(self):
        self.assertEqual(self.db.upsert_products([self.product]), {"added": 1, "updated": 0, "removed": 0})
        result = self.db.list_products(search="小黑瓶", stock="available")
        self.assertEqual(result["total"], 1)
        changed = Product(**{**self.product.__dict__, "price": 1399.0})
        self.assertEqual(self.db.upsert_products([changed])["updated"], 1)
        self.assertEqual(len(self.db.price_history(self.product.product_id)), 2)
        self.assertEqual(self.db.product_stats()["available"], 1)
        stock_changed = Product(**{**changed.__dict__, "stock_count": 4})
        self.db.upsert_products([stock_changed])
        self.assertEqual(len(self.db.price_history(self.product.product_id)), 3)

    def test_empty_result_never_erases_products(self):
        self.db.upsert_products([self.product])
        with self.assertRaises(ValueError): self.db.upsert_products([])
        self.assertEqual(self.db.list_products()["total"], 1)

    def test_product_runs_are_isolated_from_legacy_store_runs(self):
        self.db.start_run("store")
        product_run = self.db.start_run("product")
        self.assertEqual(self.db.latest_run("product")["id"], product_run)
        self.assertEqual(len(self.db.recent_runs(10, "product")), 1)


if __name__ == "__main__": unittest.main()
