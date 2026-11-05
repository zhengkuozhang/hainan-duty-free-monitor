import unittest

from cdf_hainan_stores import parse_stores


HTML = """
<li id="list_box">
  <div class="item">
    <div class="left"><a href="/detail/1.html"><img src="/uploads/1.jpg"></a></div>
    <div class="right"><a href="/detail/1.html">
      <h3><label>三亚国际免税城</label></h3>
      <p>海南省三亚市海棠湾区海棠北路118号</p><i>（0898）96656</i>
    </a></div>
  </div>
  <div class="item">
    <div class="left"><img src="/uploads/2.jpg"></div>
    <div class="right"><a href="/detail/2.html">
      <h3><label>广州机场免税店</label></h3>
      <p>广东省广州市白云国际机场</p><i>400-0000000</i>
    </a></div>
  </div>
</li>
"""


class ParseStoresTest(unittest.TestCase):
    def test_extracts_and_filters_hainan_store(self):
        stores = parse_stores(HTML)
        self.assertEqual(len(stores), 1)
        self.assertEqual(stores[0].name, "三亚国际免税城")
        self.assertEqual(stores[0].phone, "（0898）96656")
        self.assertEqual(stores[0].detail_url, "https://www.cdfg.com.cn/detail/1.html")
        self.assertEqual(stores[0].image_url, "https://www.cdfg.com.cn/uploads/1.jpg")

    def test_empty_province_returns_all_stores(self):
        self.assertEqual(len(parse_stores(HTML, province="")), 2)


if __name__ == "__main__":
    unittest.main()
