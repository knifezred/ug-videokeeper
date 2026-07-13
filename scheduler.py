"""定时调度 + Watchdog 实时监控 + 报告生成"""
import os
import signal
import threading
import schedule
from config import SCAN_INTERVAL, WATCHDOG_ENABLED, MEDIA_LIB_PATHS, log
from sync.executor import run_sync
from watcher import Watcher
from analytics.reporter import generate_scheduled_reports
import state as st

# 报告生成时间固定在本地时区 03:00。容器默认 TZ 常为 UTC，需显式设定，
# 否则部署在 UTC 容器里会变成北京时间 11:00 才生成报告。
os.environ.setdefault("TZ", "Asia/Shanghai")
try:
    import time
    time.tzset()
except (ImportError, AttributeError):
    pass  # Windows 无 time.tzset，schedule 仍按系统本地时区运行

_shutdown = threading.Event()


def run():
    st.migrate_from_json()
    log.info("ug-videokeeper 启动，扫描间隔: %s 秒", SCAN_INTERVAL)

    signal.signal(signal.SIGINT, lambda *_: _shutdown.set())
    signal.signal(signal.SIGTERM, lambda *_: _shutdown.set())

    watcher = None
    if WATCHDOG_ENABLED:
        watcher = Watcher(MEDIA_LIB_PATHS)
        watcher.start()

    try:
        _do_sync(watcher)

        if SCAN_INTERVAL == 0:
            if not WATCHDOG_ENABLED:
                log.info("SCAN_INTERVAL=0 且 watchdog 未开启，退出")
                return
            log.info("纯 Watchdog 模式运行中...")
            _loop(watcher)
        else:
            schedule.every(SCAN_INTERVAL).seconds.do(_do_sync, watcher)
            # 定时生成报告（每天凌晨检查条件）
            schedule.every().day.at("03:00").do(_do_reports)
            _loop(watcher)
    finally:
        if watcher:
            watcher.stop()


def _loop(watcher: Watcher | None):
    """主循环（wait 代替 sleep，收到退出信号立即响应）"""
    while not _shutdown.is_set():
        schedule.run_pending()
        if watcher:
            watcher.process_events()
        _shutdown.wait(1.0)
    log.info("收到退出信号，关闭中...")


def _do_sync(watcher: Watcher | None):
    """执行周期同步（暂停 watchdog 避免冲突）"""
    if watcher:
        watcher.pause()
    try:
        run_sync()
    except Exception as e:
        log.error("同步失败: %s", e, exc_info=True)
    finally:
        if watcher:
            watcher.resume()


def _do_reports():
    """凌晨生成定时报告"""
    try:
        generate_scheduled_reports()
    except Exception as e:
        log.error("报告生成失败: %s", e, exc_info=True)
