"""定时调度 + Watchdog 实时监控"""
import signal
import threading
import schedule
from config import SCAN_INTERVAL, WATCHDOG_ENABLED, MEDIA_LIB_PATHS, log
from sync.executor import run_sync
from watcher import Watcher

_shutdown = threading.Event()


def run():
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
