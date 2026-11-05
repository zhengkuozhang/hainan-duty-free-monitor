import unittest

from wfj_hainan_stores import parse_detail_image, parse_store_list


LIST_HTML = """
<ul id="storeList">
  <li><a href="/business/store493.html"><h3>万宁王府井国际免税港</h3><p>海南省万宁市礼纪镇莲兴大道1号</p></a></li>
  <li><a href="/business/store842.html"><h3>王府井海垦广场</h3><p>海南省海口市海秀中路71号</p></a></li>
</ul>
"""


class WangfujingParserTest(unittest.TestCase):
    def test_only_keeps_hainan_duty_free_store(self):
        stores = parse_store_list(LIST_HTML)
        self.assertEqual(len(stores), 1)
        self.assertEqual(stores[0].name, "万宁王府井国际免税港")
        self.assertEqual(stores[0].source_id, "wfj")

    def test_extracts_detail_image_without_session_suffix(self):
        html = '<div class="leftimg"><img src="/upload/store.jpg;jsessionid=ABC" alt="万宁王府井国际免税港"></div>'
        self.assertEqual(parse_detail_image(html), "https://www.wfj.com.cn/upload/store.jpg")


if __name__ == "__main__":
    unittest.main()
