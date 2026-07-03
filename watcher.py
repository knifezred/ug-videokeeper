"""Watchdog 实时监控 — NFO 变化时立即 NFO→DB，仅处理 cache 中已有记录"""
import os
import threading
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from config import log, WATCHDOG_DEBOUNCE
from db.connection import connect
from db import queries
from nfo.reader import read_nfo
import state as st


class NfoChangeHandler(FileSystemEventHandler):

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
            abspath = os.path.abspath(nfo_path)
            if abspath not in self._pending:
                log.debug("Watchdog 检测到 NFO 变化: %s", abspath)
            self._pending[abspath] = time.time()

    def get_ready(self) -> list[str]:
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
        self._paused.set()
        log.debug("Watchdog 已暂停")

    def resume(self):
        self._paused.clear()
        log.debug("Watchdog 已恢复")

    def process_events(self):
        if self._paused.is_set():
            return
        ready = self._handler.get_ready()
        if not ready:
            return

        log.info("Watchdog: 发现 %d 个 NFO 变化", len(ready))
        for nfo_path in ready:
            self._sync_one(nfo_path)

    def _sync_one(self, nfo_path: str):
        """NFO 被编辑 → NFO→DB，仅处理 cache 中已有的 category_id"""
        try:
            nfo = read_nfo(nfo_path)
            if nfo is None:
                log.warning("Watchdog: 解析失败 %s", nfo_path)
                return
            cat = nfo.ugreen.category_id
            if not cat:
                log.warning("Watchdog: 无 category_id，跳过 %s", nfo_path)
                return

            cache = st.load()
            if cat not in cache:
                log.info("Watchdog: category_id=%s 不在缓存中，跳过 (需先运行一次定时同步建立缓存)", cat)
                return

            conn = connect()
            try:
                db_rec = queries.fetch_video_by_category(conn, cat)
                if db_rec is None:
                    log.warning("Watchdog: DB 无此记录 category_id=%s", cat)
                    return

                log.info("Watchdog: NFO→DB %s cat=%s name=%s",
                         os.path.basename(nfo_path), cat, db_rec.name)
                queries.sync_nfo_to_db(conn, nfo)
                conn.commit()

                # sync_nfo_to_db 内部通过 _resolve_category_id 更新了 category_id
                resolved_cat = nfo.ugreen.category_id
                new_utime = nfo.ugreen.utime
                # 用 resolved_cat 重新查 DB 最新时间戳写入缓存
                fresh = queries.fetch_video_by_category(conn, resolved_cat)
                if fresh:
                    st.update_cache(resolved_cat, fresh.ctime, new_utime, cache,
                                    db_vid=fresh.ug_video_info_id)
                else:
                    st.update_cache(resolved_cat, 0, new_utime, cache)
                st.save(cache)
                log.info("Watchdog: 完成 %s (cat=%s cache utime=%d)",
                         os.path.basename(nfo_path), resolved_cat, new_utime)
            except Exception:
                conn.rollback()
                log.error("Watchdog: DB 操作失败 %s", nfo_path, exc_info=True)
                raise
            finally:
                conn.close()
        except Exception as e:
            log.error("Watchdog: 处理失败 %s: %s", nfo_path, e)
