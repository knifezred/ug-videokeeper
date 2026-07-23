"""观影报告 Web 服务 — 基于 http.server 提供报告浏览和配置管理"""
import json
import os
import http.server
import urllib.parse
from config import (log, REPORT_BIND_HOST, DB_HOST, DB_PORT, DB_NAME,
                    DB_USER, SCAN_INTERVAL, SYNC_MODE, DRY_RUN, TARGET_PATH,
                    WATCHDOG_ENABLED, WATCHDOG_DEBOUNCE, LOG_LEVEL,
                    MEDIA_LIB_PATHS)

_REPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "reports"
)
_ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
_TEMPLATE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "templates"
)
_PORT = 8088


def _load_template(name: str, **markers) -> str:
    """从 data/templates/ 加载 HTML 模板并替换标记"""
    path = os.path.join(_TEMPLATE_DIR, name)
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    for key, val in markers.items():
        html = html.replace(f"__{key.upper()}__", str(val))
    return html


def _build_select_opts(options: list[tuple[str, str]], current: str) -> str:
    """构建 <select> 的完整 <option> HTML，自动处理 selected"""
    parts = []
    for val, label in options:
        sel = ' selected' if str(val) == str(current) else ''
        parts.append(f'<option value="{val}"{sel}>{label}</option>')
    return "".join(parts)


def _load_config() -> dict:
    """收集当前配置值"""
    return {
        # 数据库（只读）
        "db_host": DB_HOST,
        "db_port": DB_PORT,
        "db_name": DB_NAME,
        "db_user": DB_USER,
        "db_password": "******",
        # 媒体库
        "media_lib_paths": os.pathsep.join(MEDIA_LIB_PATHS),
        # 同步
        "scan_interval": SCAN_INTERVAL,
        "sync_mode": SYNC_MODE,
        "dry_run": DRY_RUN,
        "target_path": TARGET_PATH,
        # Watchdog
        "watchdog_enabled": WATCHDOG_ENABLED,
        "watchdog_debounce": WATCHDOG_DEBOUNCE,
        # 日志
        "log_level": LOG_LEVEL,
        # 服务
        "report_bind_host": REPORT_BIND_HOST,
    }


def _save_env(key: str, value: str) -> bool:
    """写入单条环境变量到 .env 文件"""
    try:
        lines = []
        replaced = False
        if os.path.isfile(_ENV_PATH):
            with open(_ENV_PATH, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped.startswith(f"{key}="):
                        lines.append(f"{key}={value}\n")
                        replaced = True
                    else:
                        lines.append(line)
        if not replaced:
            lines.append(f"{key}={value}\n")
        with open(_ENV_PATH, "w", encoding="utf-8") as f:
            f.writelines(lines)
        return True
    except OSError as e:
        log.error("保存 .env 失败: %s", e)
        return False


class ReportHandler(http.server.SimpleHTTPRequestHandler):

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            self._serve_index()
            return

        if path == "/config":
            self._serve_config(msg="")
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

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/config":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8")
            params = urllib.parse.parse_qs(body)
            self._save_config(params)
            return

        self.send_error(404)

    def _save_config(self, params: dict):
        """保存配置表单"""
        edits = []
        # 可编辑字段映射
        editable = {
            "scan_interval": "SCAN_INTERVAL",
            "sync_mode": "SYNC_MODE",
            "dry_run": "DRY_RUN",
            "target_path": "TARGET_PATH",
            "log_level": "LOG_LEVEL",
            "watchdog_enabled": "WATCHDOG_ENABLED",
            "watchdog_debounce": "WATCHDOG_DEBOUNCE",
        }
        ok = True
        for form_key, env_key in editable.items():
            vals = params.get(form_key)
            if vals:
                val = vals[0].strip()
                if not val:
                    continue  # 空值不保存（保留现有值）
                if not _save_env(env_key, val):
                    ok = False
                else:
                    edits.append(form_key)
        msg = "配置已保存（重启后生效）" if ok else "部分配置保存失败"
        # 注：运行时修改 log_level 立即生效
        if "log_level" in edits:
            import logging
            new_level = params.get("log_level", [""])[0].strip().upper()
            logging.getLogger().setLevel(new_level)
            msg += " （日志等级已立即生效）"
        self._serve_config(msg)

    def _serve_config(self, msg: str):
        cfg = _load_config()
        html = _build_config_html(cfg, msg)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

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
        html = _load_template("index.html", CONTENT=content)

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


def _build_config_html(cfg: dict, msg: str) -> str:
    """构建配置页面 HTML（通过模板）"""
    msg_html = f'<div class="msg">{msg}</div>' if msg else ""
    return _load_template("config.html",
        MSG=msg_html,
        DB_HOST_PORT=f"{cfg['db_host']}:{cfg['db_port']}",
        DB_NAME=cfg['db_name'],
        DB_USER=cfg['db_user'],
        MEDIA_LIB_PATHS=cfg['media_lib_paths'],
        TARGET_PATH=cfg['target_path'],
        SCAN_INTERVAL=cfg['scan_interval'],
        SYNC_MODE_OPTIONS=_build_select_opts([
            ("bidirectional", "双向"),
            ("nfo_to_db", "仅 NFO→DB"),
            ("db_to_json", "仅 DB→JSON"),
        ], cfg['sync_mode']),
        DRY_RUN_OPTIONS=_build_select_opts([
            ("false", "关闭"),
            ("true", "开启（不实际写入）"),
        ], str(cfg['dry_run']).lower()),
        WATCHDOG_OPTIONS=_build_select_opts([
            ("true", "启用"),
            ("false", "禁用"),
        ], str(cfg['watchdog_enabled']).lower()),
        WATCHDOG_DEBOUNCE=cfg['watchdog_debounce'],
        LOG_LEVEL_OPTIONS=_build_select_opts([
            ("DEBUG", "DEBUG"),
            ("INFO", "INFO"),
            ("WARNING", "WARNING"),
            ("ERROR", "ERROR"),
        ], cfg['log_level']),
    )


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
