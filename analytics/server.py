"""观影报告 Web 服务 — 基于 http.server 提供报告浏览"""
import json
import os
import http.server
import urllib.parse
from config import log, REPORT_BIND_HOST

_REPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "reports"
)
_PORT = 8088


class ReportHandler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        # 首页 / 报告导航
        if path in ("/", "/index.html"):
            self._serve_index()
            return

        # 静态文件：data/reports/ 下的 html
        full_path = os.path.normpath(os.path.join(_REPORTS_DIR, path.lstrip("/")))
        if (full_path == _REPORTS_DIR or full_path.startswith(_REPORTS_DIR + os.sep)) and os.path.isfile(full_path):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            with open(full_path, "rb") as f:
                self.wfile.write(f.read())
            return

        self.send_error(404, "报告不存在")

    def _serve_index(self):
        """显示报告列表页面"""
        years = []
        if os.path.isdir(_REPORTS_DIR):
            for d in sorted(os.listdir(_REPORTS_DIR), reverse=True):
                if d.isdigit() and len(d) == 4:
                    years.append(d)

        html_parts = []
        for y in years:
            year_dir = os.path.join(_REPORTS_DIR, y)
            reports = []
            for f in sorted(os.listdir(year_dir)):
                if f.endswith(".html"):
                    label = _report_label(f, int(y))
                    reports.append(f'<a href="/{y}/{f}" class="rl">{label}</a>')
            if reports:
                html_parts.append(
                    f'<div class="yr"><h2>{y}年</h2>'
                    + "".join(reports)
                    + "</div>"
                )

        content = "\n".join(html_parts) if html_parts else "<p style='color:#888'>暂无报告，等待定时任务生成</p>"

        html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ug-videokeeper 观影报告</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,sans-serif;background:#f5f5f5;color:#333;padding:20px}}
.wrap{{max-width:640px;margin:0 auto}}
h1{{font-size:20px;font-weight:500;margin-bottom:20px}}
.yr{{background:#fff;border-radius:12px;padding:16px;margin-bottom:12px}}
.yr h2{{font-size:14px;font-weight:500;margin-bottom:8px;color:#888}}
.rl{{display:inline-block;padding:6px 14px;margin:3px;background:#eef;border-radius:8px;text-decoration:none;font-size:13px;color:#2563eb}}
.rl:hover{{background:#dde}}
</style></head><body>
<div class="wrap">
<h1>📺 ug-videokeeper 观影报告</h1>
{content}
</div></body></html>"""

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))


def _report_label(filename: str, year: int) -> str:
    name = filename.replace(".html", "")
    if name == "annual":
        return f"📊 {year}年度总览"
    if name.startswith("W"):
        return f"📊 第{name[1:]}周"
    if name.isdigit():
        return f"📊 {year}年{int(name)}月"
    return f"📊 {name}"


def start_server(port: int = None):
    """启动 Web 服务（阻塞）"""
    port = port or _PORT
    server = http.server.HTTPServer((REPORT_BIND_HOST, port), ReportHandler)
    log.info("观影报告 Web 服务已启动: http://%s:%d/ (绑定地址可由 REPORT_BIND_HOST 配置)",
             REPORT_BIND_HOST, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
