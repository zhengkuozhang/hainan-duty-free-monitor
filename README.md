<div align="center">

# 🛍️ cdf 海南免税 · 商品监测系统

**以公开目录为入口，用低频快照记录价格与库存变化。**

面向本地研究的商品采集、检索、历史追踪与数据导出工具。

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![SQLite](https://img.shields.io/badge/Storage-SQLite%20WAL-003B57?logo=sqlite&logoColor=white)
![Frontend](https://img.shields.io/badge/Frontend-Vanilla%20JavaScript-F7DF1E?logo=javascript&logoColor=black)
![Scope](https://img.shields.io/badge/采集范围-公开商品目录-075D46)

[项目简介](#项目简介) · [快速开始](#快速开始) · [采集机制](#采集机制) · [接口说明](#接口说明) · [开发与测试](#开发与测试)

</div>

---

## 项目简介

本项目从 [cdf 海南免税官方商城公开商品目录](https://www.cdfhnmall.com/product-list.html) 获取商品信息，将有限页采集结果合并到 SQLite 中，并记录商品新增、业务字段变更及价格 / 库存快照。

前端提供商品卡片、搜索筛选、分页、采集记录和自动任务设置。项目中还保留了早期的中免与王府井公开门店采集模块，当前 Web 应用以**商品监测**为主要流程。

> 本项目为本地研究工具，并非 cdf 官方产品。页面展示已采集快照，不代表官网全部商品，也不保证与官网当前价格和库存一致。

## 功能亮点

- **公开商品采集**：名称、品牌、规格、分类、公开价格、库存字段、促销标签、图片和官网公开销量字段。
- **商品检索**：按商品名、品牌或商品编码搜索，按品牌、分类及库存筛选。
- **分页与排序**：支持最近更新、价格升降序和库存排序。
- **变更审计**：跟踪商品新增和业务字段更新，保存前后内容及关联任务。
- **价格与库存历史**：新增商品或价格 / 库存 / 可售状态变化时追加历史记录。
- **后台任务**：手动启动采集、查询运行状态、记录失败原因并恢复遗留任务状态。
- **定时采集**：支持 6 / 12 / 24 / 48 / 72 小时间隔，默认开启、每 24 小时一次。
- **导出与备份**：CSV、JSON、带时间戳的 JSON 快照，以及 SQLite 在线备份下载。
- **保留历史数据**：有限页采集未出现的旧商品不会被直接认定为下架。

## 技术实现

```text
浏览器：商品卡片 / 筛选 / 采集记录 / 调度设置
                         │ 同源 HTTP
app.py：本地 HTTP 服务与后台采集线程
    ├── cdf_product_crawler.py：公开商品采集与字段映射
    ├── scheduler.py：定时间隔调度
    └── data_store.py：SQLite WAL、历史、审计与备份
                         │
                  output/ 导出与快照
```

后端使用 Python、Requests、Beautiful Soup 和 SQLite；前端使用原生 HTML / CSS / JavaScript，无需前端构建。

## 快速开始

### 环境要求

- Python **3.10 或更新版本**：源码使用 `X | None` 联合类型及内置泛型。
- 可访问商品来源站点的网络。
- 现代浏览器。
- macOS 可使用 `.command` 脚本；其他系统可通过终端启动。

### 安装依赖

在本项目目录执行，建议使用虚拟环境：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
```

Windows 激活虚拟环境时使用 `.venv\Scripts\activate`。

### 启动服务

```bash
python3 app.py
```

打开 **<http://127.0.0.1:8000>**。

macOS 可在依赖安装完成后双击 `start.command`；若使用虚拟环境，建议在已激活的终端中执行启动命令。脚本使用当前可用的 `python3`，不会自行激活虚拟环境。

按 `Ctrl+C` 停止服务。默认仅监听本机回环地址。

### 配置商城请求头

采集器不在公开源码中保存商城 `Appkey`。运行前请按来源站点的授权与使用规则取得相应值，再配置环境变量：

```bash
export CDF_APPKEY='填写你的商城目录 Appkey'
python3 app.py
```

也可在项目根目录创建 `.catalog-appkey`，仅写入该值，并设置文件权限为 `600`。环境变量优先；该文件已加入 `.gitignore`，不得上传。缺少配置时，页面仍可浏览本地数据，采集任务会返回配置提示。

### 第一次采集

1. 打开页面并点击“立即采集 5 页”。
2. 等待后台任务完成，查看商品卡片和采集记录。
3. 使用品牌、分类、库存和价格排序定位商品。
4. 在“自动任务”区域选择更新间隔并保存。
5. 需要分析或归档时下载 CSV、JSON 或数据库备份。

默认手动请求为 5 页、每页请求 20 件、约 1.2 秒请求间隔，并仅请求有货商品。实际数量取决于官网返回结果，可能包含重复项，不能保证恰好 100 件。

## 采集机制

### 请求范围与频率

- Web 接口将单次页数限制在 `1–20`，请求页大小限制在 `1–50`，延迟限制在 `0.5–5` 秒。
- 底层 `crawl_products()` 的页数硬上限为 `50`；这是内部函数上限，与 Web 接口上限不同。
- 分类名称按叶级分类查询代表商品，缺失图片可通过详情补全；单次详情补全最多 `50` 次。
- 分类和图片会复用数据库缓存，减少重复请求。
- 同一应用进程使用非阻塞锁避免重复启动采集；不支持通过多进程实例共享该锁。

### 数据更新语义

商品使用 `product_id` 去重并合并。由于只抓取目录中的有限页面，未出现的旧商品继续保留，`last_seen_at` 表示最后一次采集到该商品的时间。

空结果会被拒绝，避免清空商品库。网络和解析错误会记录为失败任务。商品库更新、导出文件写入和任务完成标记不是一个跨文件原子事务，因此任务失败后应同时检查数据库状态与导出文件时间。

### 调度边界

设置保存在 `output/settings.json`。服务启动或保存设置后，按当前时间重新计算下一次运行时间；当前实现不会保存原计划时间并补跑关机期间的任务。

**只有服务进程持续运行时，定时采集才会执行。** 电脑关机、休眠或服务停止期间不保证按时采集。

## 启动参数

```bash
python3 app.py --host 127.0.0.1 --port 8000
```

如需避开端口占用：

```bash
python3 app.py --port 8001
```

`start.command` 的健康检查和浏览器地址固定为 `8000`；修改端口时请直接使用命令行，并打开对应地址。

当前应用按本机使用设计。`--host` 可改变监听地址，但项目没有完整账号鉴权体系，不应据此视为已具备公网部署能力。

## 接口说明

### 读取接口

- `GET /api/products`：商品分页，参数为 `q`、`brand`、`category`、`stock`、`sort`、`page`、`page_size`。
- `GET /api/stats`：商品数、品牌数、有货数、促销数及筛选选项。
- `GET /api/history`：最近商品采集任务。
- `GET /api/changes`：最近商品变更摘要。
- `GET /api/price-history?product_id=...`：指定商品价格 / 库存历史。
- `GET /api/health`：服务状态、商品数和最新商品任务。
- `GET /api/source`：当前商品来源与采集范围说明。
- `GET /api/schedule`：自动采集设置及下一次计划时间。

`stock` 支持 `all`、`available`、`soldout`；`sort` 支持 `updated`、`price_asc`、`price_desc`、`stock_desc`。商品分页默认每页 `24` 条，最大 `100` 条。

### 写入接口

`POST /api/refresh` 启动后台任务，成功返回 `202`；当前进程已有任务时返回 `409`。

```json
{
  "max_pages": 5,
  "page_size": 20,
  "delay": 1.2,
  "has_stock": true
}
```

`POST /api/schedule` 保存调度设置：

```json
{
  "enabled": true,
  "interval_hours": 24
}
```

### 下载接口

- `GET /download/csv`：最近一次成功写出的商品 CSV。
- `GET /download/json`：最近一次成功写出的商品 JSON。
- `GET /download/database`：使用 SQLite 在线备份 API 创建并下载数据库副本。

**导出范围区别：** CSV / JSON 来自本次采集结果；数据库包含历次合并保留的商品和历史，数量可能不同。价格历史目前通过 API 提供，页面尚无独立价格曲线入口。

## 目录结构

```text
.
├── README.md
├── app.py                   # 当前商品 Web 应用
├── cdf_product_crawler.py   # 商品采集、分类补全与导出
├── data_store.py            # 商品 / 门店存储、历史与审计
├── scheduler.py             # 后台调度
├── cdf_hainan_stores.py     # 中免公开门店采集器
├── wfj_hainan_stores.py     # 王府井公开门店采集器
├── sources.py              # 早期多来源门店编排
├── requirements.txt
├── start.command
├── check.command
├── web/
│   ├── index.html
│   ├── app.js
│   └── styles.css
├── tests/                   # 解析、存储、调度和来源测试
└── output/                  # 本地运行产物，不应提交
    ├── hainan_duty_free.db
    ├── settings.json
    ├── cdf_hainan_products.csv
    ├── cdf_hainan_products.json
    └── snapshots/
```

## 数据存储与备份

SQLite 使用 WAL 模式和外键约束，主要实体包括：

- `products`、`price_history`、`product_change_events`：商品当前状态、价格 / 库存历史与业务变更。
- `crawl_runs`：商品和门店采集任务，通过 `run_type` 区分。
- `stores`、`change_events`：早期门店快照与审计记录。

建议通过页面“数据库备份”入口取得一致性副本。不要只复制运行中的单个 `.db` 文件而忽略尚未合并的 WAL 数据。

当前没有应用内恢复向导。恢复前先停止服务，保存现有数据库及其伴随文件，再将核验过的备份放到新的工作目录中验证；恢复后需重新启动服务。若要完整迁移，同时保存 `settings.json`、导出和快照目录。

## 开发与测试

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile app.py data_store.py cdf_product_crawler.py scheduler.py sources.py cdf_hainan_stores.py wfj_hainan_stores.py
```

macOS 可运行：

```bash
./check.command
```

脚本会进行 Python 语法检查和测试，使用执行脚本时可用的 `python3`。测试覆盖商品字段映射、采集参数限制、分类补全、商品合并、价格 / 库存历史、门店解析、来源失败隔离和调度配置。

测试通过仅说明对应本地逻辑通过检查，不代表来源接口当前仍可用；真实连通性需单独进行低频、小范围核查。

### 早期门店采集器

中免门店模块保留独立 CLI：

```bash
python3 cdf_hainan_stores.py --max-pages 7 --delay 1.5 --province 海南 --output-dir output
```

`sources.py` 中标记停用或异常的来源不应自行恢复采集。门店流程与当前商品 Web 流程分开，不能把旧门店备份误当作完整商品库备份。

## 常见问题

<details>
<summary><strong>启动提示缺少 requests 或 bs4</strong></summary>

确认使用同一个 Python 环境安装依赖和启动服务。建议激活 `.venv` 后重新执行 `python3 -m pip install -r requirements.txt`。

</details>

<details>
<summary><strong>采集失败，旧数据是否丢失？</strong></summary>

空结果和采集阶段异常不会清空已有商品。若失败发生在商品写入后的导出阶段，数据库可能已更新；请查看任务错误、商品最后采集时间和导出文件时间。

</details>

<details>
<summary><strong>为什么数据库与 CSV 数量不同？</strong></summary>

数据库保留历次合并结果；CSV / JSON 只包含本次有限页采集结果。旧商品未再次出现时不会自动删除。

</details>

## 数据来源与使用边界

当前商品来源为 cdf 海南免税官方商城，应用标注运营主体为中免（海南）数字科技有限公司。代码只访问无需登录的公开商品目录及相关详情，不访问会员、订单、购物车、支付或个人信息接口。

- 库存、价格和促销均为采集时快照。
- “网站公开销量字段”不代表经过审计的实际成交量。
- 公开可访问不等于获得任意再分发许可；使用与发布数据前应核对来源条款。
- 项目不提供访问限制、验证码或登录机制的绕过能力。

**项目许可证：** 当前目录未提供 `LICENSE` 文件，不默认授予开源使用许可。第三方商品信息、图片及商标权利归相应权利人所有。
