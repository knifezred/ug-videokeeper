"""Watchdog 实时监控 — 监听 NFO 文件变化，变化时立即 NFO→DB 回写"""
import os
import threading
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from config import log, WATCHDOG_DEBOUNCE
from db.connection import connect
from db import queries
from nfo.reader import read_nfo
from sync.strategy import decide
import state as st


class NfoChangeHandler(FileSystemEventHandler):
    """监听 .nfo 文件的修改和创建事件"""

    def __init__(self):
        super().__init__()
        self._pending: dict[str, float] = {}
        self._lock = threading.Lock()

    def on_modified(self, event):
        if not event.is_directory and event.src_path.endswith(".nfo"):
            self._mark_pending(event.src_path)

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith(".nfo"):
            self._mark_pending(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory and event.src_path.endswith(".nfo"):
            self._mark_pending(event.src_path)

    def on_moved(self, event):
        if not event.is_directory and event.dest_path.endswith(".nfo"):
            self._mark_pending(event.dest_path)

    def _mark_pending(self, nfo_path: str):
        with self._lock:
            self._pending[os.path.abspath(nfo_path)] = time.time()

    def get_ready(self) -> list[str]:
        """返回已稳定（超过 DEBOUNCE 秒未变化）的 NFO 路径列表"""
        now = time.time()
        ready = []
        with self._lock:
            stale = []
            for path, t in self._pending.items():
                if now - t >= WATCHDOG_DEBOUNCE:
                    ready.append(path)
                    stale.append(path)
            for path in stale:
                del self._pending[path]
        return ready


class Watcher:
    """Watchdog 监控器"""

    def __init__(self, watch_paths: list[str]):
        self._watch_paths = [p for p in watch_paths if os.path.isdir(p)]
        self._observer: Observer | None = None
        self._handler = NfoChangeHandler()
        self._paused = threading.Event()

    def start(self):
        if not self._watch_paths:
            log.warning("无有效监控目录，Watchdog 未启动")
            return

        self._observer = Observer()
        for p in self._watch_paths:
            self._observer.schedule(self._handler, p, recursive=True)
            log.info("Watchdog 监控: %s", p)
        self._observer.start()
        log.info("Watchdog 已启动（%d 个目录，debounce=%.1fs）",
                 len(self._watch_paths), WATCHDOG_DEBOUNCE)

    def stop(self):
        if self._observer:
            self._observer.stop()
            self._observer.join()
            log.info("Watchdog 已停止")

    def pause(self):
        """暂停事件处理（周期同步期间调用）"""
        self._paused.set()
        log.debug("Watchdog 已暂停")

    def resume(self):
        """恢复事件处理"""
        self._paused.clear()
        log.debug("Watchdog 已恢复")

    def process_events(self):
        """主线程定期调用，处理已稳定的 NFO 变化"""
        if self._paused.is_set():
            return
        ready = self._handler.get_ready()
        if not ready:
            return

        log.info("Watchdog: 发现 %d 个 NFO 变化", len(ready))
        for nfo_path in ready:
            self._sync_one(nfo_path)

    def _sync_one(self, nfo_path: str):
        """对单个 NFO 文件执行 NFO→DB 回写"""
        try:
            nfo = read_nfo(nfo_path)
            if nfo is None:
                log.debug("Watchdog: 解析失败 %s", nfo_path)
                return
            if not nfo.ugreen.category_id:
                log.debug("Watchdog: 无 category_id，跳过 %s", nfo_path)
                return

            conn = connect()
            try:
                db_rec = queries.fetch_video_by_category(conn, nfo.ugreen.category_id)
                if db_rec is None:
                    log.debug("Watchdog: DB 无此记录 category_id=%s，跳过 %s",
                              nfo.ugreen.category_id, os.path.basename(nfo_path))
                    return

                decision = decide(nfo, db_rec)
                if decision.direction == "skip":
                    log.debug("Watchdog: 无变化，跳过 %s", os.path.basename(nfo_path))
                    return

                log.info("Watchdog: [%s] %s → NFO→DB: %s",
                         decision.scene, os.path.basename(nfo_path), decision.message)

                queries.sync_nfo_to_db(conn, nfo)
                conn.commit()

                cache = st.load()
                st.update_cache(nfo.ugreen.category_id,
                                db_rec.ctime, db_rec.utime, nfo_path, cache)
                st.save(cache)
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()
        except Exception as e:
            log.error("Watchdog: 处理失败 %s: %s", nfo_path, e)
