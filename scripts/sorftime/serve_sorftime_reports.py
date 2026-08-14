"""Serve Sorftime reports as a small read-only local website."""

from __future__ import annotations

import argparse
import html
import json
import re
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


def markdown_html(text: str) -> str:
    lines: list[str] = []
    in_list = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("# "):
            lines.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            lines.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("### "):
            lines.append(f"<h3>{html.escape(line[4:])}</h3>")
        elif line.startswith("- ") or re.match(r"^\d+\. ", line):
            if not in_list:
                lines.append("<ul>")
                in_list = True
            item = re.sub(r"^(?:- |\d+\. )", "", line)
            item = html.escape(item).replace("&lt;code&gt;", "<code>").replace("&lt;/code&gt;", "</code>")
            lines.append(f"<li>{item}</li>")
        else:
            if in_list:
                lines.append("</ul>")
                in_list = False
            if line:
                safe = html.escape(line)
                safe = re.sub(r"`([^`]+)`", r"<code>\1</code>", safe)
                lines.append(f"<p>{safe}</p>")
    if in_list:
        lines.append("</ul>")
    return "\n".join(lines)


class ReportHandler(BaseHTTPRequestHandler):
    reports_root: Path
    queue_root: Path | None
    details_root: Path | None

    def _send(self, body: str, status: int = 200, content_type: str = "text/html; charset=utf-8") -> None:
        payload = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        path = unquote(urlparse(self.path).path)
        if path == "/" or path == "/reports":
            self._index()
        elif path.startswith("/report/"):
            self._report(path.removeprefix("/report/"))
        elif path.startswith("/file/"):
            self._file(path.removeprefix("/file/"))
        elif path == "/details":
            self._details()
        elif path.startswith("/detail/"):
            self._detail(path.removeprefix("/detail/"))
        elif path == "/queue":
            self._queue()
        else:
            self._send("<h1>404</h1>", 404)

    def _index(self) -> None:
        reports = sorted(self.reports_root.glob("**/optimization_report.md"), reverse=True)
        cards = []
        for report in reports:
            run_dir = report.parent
            summary = run_dir / "parsed" / "optimization_summary.json"
            data = json.loads(summary.read_text(encoding="utf-8")) if summary.exists() else {}
            product = data.get("product", {})
            cards.append(f"<tr><td>{html.escape(str(data.get('asin','')))}</td><td>{html.escape(str(data.get('site','')))}</td><td>{html.escape(str(product.get('title',''))[:120])}</td><td><a href='/report/{self._relative(run_dir)}'>查看报告</a></td></tr>")
        queue_link = "<a href='/queue'>批次队列</a>" if self.queue_root and (self.queue_root / "manifest.json").exists() else ""
        detail_count = self._detail_count()
        details_link = "<a href='/details'>全部商品详情</a>" if detail_count else ""
        nav = " | ".join(link for link in (queue_link, details_link) if link)
        detail_reports = sorted((self.reports_root / "details").glob("detail_*/detail_report.md")) if (self.reports_root / "details").exists() else []
        detail_rows = []
        for report in detail_reports:
            match = re.match(r"detail_([A-Za-z0-9]+)_([A-Za-z]+)", report.parent.name)
            if not match:
                continue
            asin, site = match.groups()
            detail_rows.append(f"<tr><td>{asin}</td><td>{site}</td><td><a href='/file/{self._relative(report)}'>查看详情报告</a></td></tr>")
        detail_table = f"<h2>基础详情报告</h2><p>已生成：{len(detail_rows)} 条</p><table><tr><th>ASIN</th><th>站点</th><th>操作</th></tr>{''.join(detail_rows[:100])}</table><p>列表页：<a href='/details'>查看全部商品详情</a></p>" if detail_rows else ""
        self._page("Sorftime 商品数据中心", f"<p>{nav}</p><p>完整优化报告：{len(cards)} 条；基础商品详情：{detail_count} 条。</p><h2>完整优化报告</h2><table><tr><th>ASIN</th><th>站点</th><th>商品</th><th>操作</th></tr>{''.join(cards)}</table>{detail_table}")

    def _detail_count(self) -> int:
        if not self.details_root:
            return 0
        path = self.details_root / "product_details.jsonl"
        if not path.exists():
            return 0
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

    def _load_details(self) -> list[dict]:
        if not self.details_root:
            return []
        path = self.details_root / "product_details.jsonl"
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return rows

    def _details(self) -> None:
        rows = self._load_details()
        table_rows = []
        for row in rows:
            asin = html.escape(str(row.get("asin", "")))
            site = html.escape(str(row.get("site", "")))
            table_rows.append(
                f"<tr><td>{asin}</td><td>{site}</td><td>{html.escape(str(row.get('brand', '')))}</td>"
                f"<td>{html.escape(str(row.get('title', ''))[:140])}</td>"
                f"<td>{html.escape(str(row.get('price', '')))}</td><td>{html.escape(str(row.get('star_rating', '')))}</td>"
                f"<td>{html.escape(str(row.get('review_count', '')))}</td><td><a href='/detail/{asin}/{site}'>查看详情</a></td></tr>"
            )
        self._page("全部商品基础详情", f"<p><a href='/'>返回首页</a></p><p>商品数量：{len(rows)}</p><table><tr><th>ASIN</th><th>站点</th><th>品牌</th><th>标题</th><th>价格</th><th>评分</th><th>评论数</th><th>操作</th></tr>{''.join(table_rows)}</table>")

    def _detail(self, relative: str) -> None:
        parts = relative.strip("/").split("/")
        if len(parts) != 2:
            self._send("<h1>404</h1>", 404)
            return
        asin, site = parts
        row = next((item for item in self._load_details() if item.get("asin") == asin and item.get("site") == site), None)
        if row is None:
            self._send("<h1>商品详情不存在</h1>", 404)
            return
        entries = "".join(f"<tr><th>{html.escape(str(key))}</th><td>{html.escape(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value))}</td></tr>" for key, value in row.items() if key not in {"raw_path", "parsed_path"})
        self._page(f"{asin} 商品详情", f"<p><a href='/details'>返回商品列表</a></p><table>{entries}</table>")

    def _report(self, relative: str) -> None:
        run_dir = (self.reports_root / relative).resolve()
        if not self._safe_path(run_dir) or not run_dir.is_dir():
            self._send("<h1>404</h1>", 404)
            return
        report = run_dir / "optimization_report.md"
        if not report.exists():
            self._send("<h1>报告不存在</h1>", 404)
            return
        files = [f"<li><a href='/file/{self._relative(p)}'>{html.escape(str(p.relative_to(run_dir)))}</a></li>" for p in sorted(run_dir.rglob("*")) if p.is_file()]
        self._page("商品优化报告", f"<p><a href='/reports'>返回列表</a></p><nav><ul>{''.join(files)}</ul></nav><article>{markdown_html(report.read_text(encoding='utf-8'))}</article>")

    def _file(self, relative: str) -> None:
        target = (self.reports_root / relative).resolve()
        if not self._safe_path(target) or not target.is_file():
            self._send("<h1>404</h1>", 404)
            return
        suffix = target.suffix.lower()
        content_type = "text/plain; charset=utf-8" if suffix in {".md", ".txt", ".csv", ".json"} else "application/octet-stream"
        self._send(target.read_text(encoding="utf-8", errors="replace"), content_type=content_type)

    def _queue(self) -> None:
        if not self.queue_root:
            self._send("<h1>队列未配置</h1>", 404)
            return
        manifest = self.queue_root / "manifest.json"
        if not manifest.exists():
            self._send("<h1>队列不存在</h1>", 404)
            return
        data = json.loads(manifest.read_text(encoding="utf-8"))
        statuses = {}
        state_path = self.queue_root / "state.sqlite"
        if state_path.exists():
            connection = sqlite3.connect(state_path)
            statuses = dict(connection.execute("SELECT batch_id, status FROM queue_items GROUP BY batch_id").fetchall())
            connection.close()
        rows = "".join(f"<tr><td>{b['batch_id']}</td><td>{b['site']}</td><td>{b['item_count']}</td><td>{html.escape(statuses.get(b['batch_id'], b['status']))}</td></tr>" for b in data.get("batches", []))
        self._page("Sorftime 批次队列", f"<p><a href='/reports'>返回报告</a></p><p>总 ASIN：{data.get('total_items')}，批次：{data.get('batch_count')}，批大小：{data.get('batch_size')}</p><table><tr><th>批次</th><th>站点</th><th>数量</th><th>状态</th></tr>{rows}</table>")

    def _page(self, title: str, body: str) -> None:
        self._send(f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>body{{font-family:Arial,sans-serif;max-width:1280px;margin:2rem auto;padding:0 1rem;line-height:1.55;color:#202124}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:.5rem;text-align:left;vertical-align:top}}th{{background:#f4f5f7}}code{{background:#f1f3f4;padding:2px 4px}}article{{max-width:1000px}}a{{color:#1558d6}}</style></head><body>{body}</body></html>")

    def _relative(self, path: Path) -> str:
        return path.resolve().relative_to(self.reports_root.resolve()).as_posix()

    def _safe_path(self, path: Path) -> bool:
        try:
            path.relative_to(self.reports_root.resolve())
            return True
        except ValueError:
            return False

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve Sorftime reports locally")
    parser.add_argument("--reports-dir", type=Path, default=Path("test-data/sorftime/runs"))
    parser.add_argument("--queue-dir", type=Path, default=Path("test-data/sorftime/batch-queue"))
    parser.add_argument("--details-dir", type=Path, default=Path("test-data/sorftime/product-details"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    ReportHandler.reports_root = args.reports_dir.resolve()
    ReportHandler.queue_root = args.queue_dir.resolve()
    ReportHandler.details_root = args.details_dir.resolve()
    server = ThreadingHTTPServer((args.host, args.port), ReportHandler)
    print(f"Sorftime report server: http://{args.host}:{args.port}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
