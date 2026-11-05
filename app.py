#!/usr/bin/env python3
"""cdf海南免税商品监测系统：本地、低频、仅采集公开目录。"""
from __future__ import annotations
import argparse, json, logging, threading
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from cdf_product_crawler import CATALOG_URL, crawl_products, write_csv, write_json
from data_store import DataStore
from scheduler import CrawlScheduler

ROOT = Path(__file__).resolve().parent
WEB_DIR, OUTPUT_DIR = ROOT / "web", ROOT / "output"
JSON_PATH, CSV_PATH = OUTPUT_DIR / "cdf_hainan_products.json", OUTPUT_DIR / "cdf_hainan_products.csv"
DB_PATH, SETTINGS_PATH = OUTPUT_DIR / "hainan_duty_free.db", OUTPUT_DIR / "settings.json"
SNAPSHOT_DIR, BACKUP_PATH = OUTPUT_DIR / "snapshots", OUTPUT_DIR / "hainan_duty_free_backup.db"
database = DataStore(DB_PATH)
refresh_lock = threading.Lock()
scheduler: CrawlScheduler | None = None

def run_refresh(run_id: int, options: dict | None = None) -> None:
    options, started, results = options or {}, datetime.now().astimezone(), []
    try:
        products, meta = crawl_products(max_pages=options.get("max_pages", 5), page_size=options.get("page_size", 20), delay=options.get("delay", 1.2), has_stock=options.get("has_stock", True), category_cache=database.category_map(), image_cache=database.image_map())
        changes = database.upsert_products(products, run_id)
        write_json(products, JSON_PATH); write_csv(products, CSV_PATH)
        write_json(products, SNAPSHOT_DIR / datetime.now().astimezone().strftime("products_%Y%m%d_%H%M%S_%f.json"))
        results.append({"source_id":"cdf_hainan_mall","source_name":"cdf海南免税官方商城","status":"success","count":len(products),"duration_ms":int((datetime.now().astimezone()-started).total_seconds()*1000),**meta})
        database.finish_run(run_id, len(products), changes, results)
    except Exception as exc:
        logging.exception("商品采集失败")
        results.append({"source_id":"cdf_hainan_mall","source_name":"cdf海南免税官方商城","status":"failed","error":str(exc)[:500]})
        database.fail_run(run_id, str(exc), results)
    finally:
        refresh_lock.release()

def start_refresh_job(options: dict | None = None) -> int | None:
    if not refresh_lock.acquire(blocking=False): return None
    try:
        run_id = database.start_run("product")
        threading.Thread(target=run_refresh, args=(run_id, options), daemon=True, name=f"product-crawl-{run_id}").start()
        return run_id
    except Exception:
        refresh_lock.release(); raise

class AppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs): super().__init__(*args, directory=str(WEB_DIR), **kwargs)
    def log_message(self, fmt: str, *args) -> None: logging.info("%s - %s", self.client_address[0], fmt % args)
    def end_headers(self) -> None:
        self.send_header("X-Frame-Options","DENY"); self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Permissions-Policy","camera=(), microphone=(), geolocation=()")
        self.send_header("Content-Security-Policy","default-src 'self'; img-src 'self' https://pic.cdfgsanya.com data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        super().end_headers()
    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body=json.dumps(payload,ensure_ascii=False).encode(); self.send_response(status)
        self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Content-Length",str(len(body)))
        self.send_header("Cache-Control","no-store"); self.send_header("X-Content-Type-Options","nosniff"); self.end_headers(); self.wfile.write(body)
    def read_json(self) -> dict:
        length=int(self.headers.get("Content-Length","0"))
        if length<0 or length>4096: raise ValueError("请求内容过大")
        value=json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value,dict): raise ValueError("请求格式错误")
        return value
    def do_GET(self) -> None:  # noqa: N802
        parsed=urlparse(self.path); path=parsed.path; query=parse_qs(parsed.query)
        one=lambda key,default="":query.get(key,[default])[0]
        if path=="/api/products":
            try: self.send_json(database.list_products(one("q"),one("brand"),one("category"),one("stock","all"),one("sort","updated"),int(one("page","1")),int(one("page_size","24"))))
            except ValueError as exc: self.send_json({"error":str(exc)},HTTPStatus.BAD_REQUEST)
            return
        if path=="/api/stats": self.send_json(database.product_stats()); return
        if path=="/api/history": self.send_json({"runs":database.recent_runs(12,"product")}); return
        if path=="/api/changes": self.send_json({"changes":database.recent_product_changes(30)}); return
        if path=="/api/price-history": self.send_json({"history":database.price_history(one("product_id"))}); return
        if path=="/api/health":
            stats=database.product_stats(); self.send_json({"ok":True,"product_count":stats["total"],"latest_run":database.latest_run("product")}); return
        if path=="/api/source": self.send_json({"name":"cdf海南免税官方商城","url":CATALOG_URL,"operator":"中免（海南）数字科技有限公司","scope":"仅采集无需登录即可访问的公开商品目录，不访问会员、订单、支付或个人信息接口。"}); return
        if path=="/api/schedule": self.send_json(scheduler.status() if scheduler else {"enabled":False,"interval_hours":24,"next_run_at":None}); return
        downloads={"/download/csv":(CSV_PATH,"cdf_hainan_products.csv","text/csv; charset=utf-8"),"/download/json":(JSON_PATH,"cdf_hainan_products.json","application/json; charset=utf-8")}
        if path in downloads: self._send_download(*downloads[path]); return
        if path=="/download/database": database.backup_to(BACKUP_PATH); self._send_download(BACKUP_PATH,"cdf_hainan_monitor.db","application/vnd.sqlite3"); return
        if path=="/": self.path="/index.html"
        super().do_GET()
    def _send_download(self,path:Path,filename:str,content_type:str)->None:
        if not path.exists(): self.send_error(HTTPStatus.NOT_FOUND,"请先完成一次采集"); return
        body=path.read_bytes(); self.send_response(HTTPStatus.OK); self.send_header("Content-Type",content_type)
        self.send_header("Content-Disposition",f'attachment; filename="{filename}"'); self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_POST(self) -> None:  # noqa: N802
        path=urlparse(self.path).path
        try:
            payload=self.read_json()
            if path=="/api/schedule": self.send_json(scheduler.save(payload) if scheduler else {}); return
            if path=="/api/refresh":
                raw_stock=payload.get("has_stock",True)
                if not isinstance(raw_stock,bool): raise ValueError("has_stock 必须是布尔值")
                options={"max_pages":max(1,min(int(payload.get("max_pages",5)),20)),"page_size":max(1,min(int(payload.get("page_size",20)),50)),"delay":max(.5,min(float(payload.get("delay",1.2)),5.0)),"has_stock":raw_stock}
                run_id=start_refresh_job(options)
                if run_id is None: self.send_json({"ok":False,"error":"已有采集任务正在运行"},HTTPStatus.CONFLICT)
                else: self.send_json({"ok":True,"run_id":run_id,"status":"running"},HTTPStatus.ACCEPTED)
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except (ValueError,TypeError,json.JSONDecodeError) as exc: self.send_json({"ok":False,"error":str(exc)},HTTPStatus.BAD_REQUEST)

def main() -> None:
    global scheduler
    parser=argparse.ArgumentParser(description="启动 cdf海南免税商品监测系统"); parser.add_argument("--host",default="127.0.0.1"); parser.add_argument("--port",type=int,default=8000); args=parser.parse_args()
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    database.initialize(); database.recover_interrupted_runs(); scheduler=CrawlScheduler(SETTINGS_PATH,lambda:start_refresh_job() is not None); scheduler.start()
    server=ThreadingHTTPServer((args.host,args.port),AppHandler); print(f"cdf海南免税商品监测系统已启动：http://{args.host}:{args.port}")
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: scheduler.stop(); server.server_close()

if __name__=="__main__": main()
