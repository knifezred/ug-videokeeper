"""环境变量配置加载"""
import os
import logging

# ---- 数据库 ----
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "5433"))
DB_NAME = os.getenv("DB_NAME", "video")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")

# ---- 媒体库 ----
MEDIA_LIB_PATHS = [
    p.strip()
    for p in os.getenv("MEDIA_LIB_PATHS", "").split(":")
    if p.strip()
]

# ---- 同步 ----
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "3600"))
SYNC_MODE = os.getenv("SYNC_MODE", "bidirectional")
DRY_RUN = os.getenv("DRY_RUN", "false").lower() in ("1", "true", "yes")

# ---- Watchdog ----
WATCHDOG_ENABLED = os.getenv("WATCHDOG_ENABLED", "true").lower() in ("1", "true", "yes")
WATCHDOG_DEBOUNCE = float(os.getenv("WATCHDOG_DEBOUNCE", "3.0"))  # 文件稳定等待秒数

# ---- 日志 ----
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("ug-videokeeper")
