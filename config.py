"""环境变量配置加载"""
import os
import logging

# ---- 数值解析容错 ----
def _to_int(val, default):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _to_float(val, default):
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ---- 数据库 ----
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = _to_int(os.getenv("DB_PORT"), 5433)
DB_NAME = os.getenv("DB_NAME", "video")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

# ---- 媒体库 ----
# 路径分隔符用 os.pathsep（Linux 为 ':'，Windows 为 ';'），避免 Windows 盘符被切断
MEDIA_LIB_PATHS = [
    p.strip()
    for p in os.getenv("MEDIA_LIB_PATHS", "").split(os.pathsep)
    if p.strip()
]

# ---- 同步 ----
SCAN_INTERVAL = _to_int(os.getenv("SCAN_INTERVAL"), 3600)
SYNC_MODE = os.getenv("SYNC_MODE", "bidirectional")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() in ("1", "true", "yes")
TARGET_PATH = (os.getenv("TARGET_PATH", "") or "").strip()
if TARGET_PATH in ("", "/"):
    TARGET_PATH = ""  # 空值表示不限路径

# ---- 报告 Web 服务 ----
# 默认仅本机回环，需局域网访问时设 REPORT_BIND_HOST=0.0.0.0
REPORT_BIND_HOST = os.getenv("REPORT_BIND_HOST", "127.0.0.1")

# ---- Watchdog ----
WATCHDOG_ENABLED = os.getenv("WATCHDOG_ENABLED", "true").lower() in ("1", "true", "yes")
WATCHDOG_DEBOUNCE = _to_float(os.getenv("WATCHDOG_DEBOUNCE"), 3.0)  # 文件稳定等待秒数

# ---- 日志 ----
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ug-videokeeper")
