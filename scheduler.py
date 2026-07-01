"""定时调度 + Watchdog 实时监控"""
import time
import schedule
from config import SCAN_INTERVAL, WATCHDOG_ENABLED, MEDIA_LIB_PATHS, log
from sync.executor import run_sync
from watcher import Watcher


def run():
    log.info("ug-videokeeper 启动，扫描间隔: %s 秒", SCAN_INTERVAL)

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
            _loop(watcher)
    finally:
        if watcher:
            watcher.stop()


def _loop(watcher: Watcher | None):
    """主循环"""
    while True:
        schedule.run_pending()
        if watcher:
            watcher.process_events()
        time.sleep(1)


def _do_sync(watcher: Watcher | None):
    """执行周期同步（暂停 watchdog 避免冲突）"""
    if watcher:
        watcher.pause()
    try:
        run_sync()
    except Exception as e:
        log.error("同步失败: %s", e)
    finally:
        if watcher:
            watcher.resume()
