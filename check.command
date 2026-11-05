#!/bin/zsh
set -e

PROJECT_DIR="${0:A:h}"
cd "$PROJECT_DIR"
export PYTHONPYCACHEPREFIX="/tmp/hainan-duty-free-pycache"

echo "正在检查 Python 语法……"
python3 -m py_compile app.py scheduler.py data_store.py cdf_product_crawler.py sources.py wfj_hainan_stores.py cdf_hainan_stores.py
echo "正在运行自动化测试……"
python3 -m unittest discover -s tests -v
echo "检查完成。"
read "?按回车键关闭……"
