"""Watchdog 实时监控 — NFO 变化时立即 NFO→DB，仅处理 cache 中已有记录"""
import os
import threading
import time
import sqlite3
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from config import log, WATCHDOG_DEBOUNCE
from db.connection import connect
from db import queries, sync as db_sync
from models import NfoRecord, VideoMeta
from nfo.reader import read_nfo
from nfo import ugreen
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
            # 旧路径也登记，确保原位置的缓存/数据被重新评估
            if event.src_path.endswith(".nfo"):
                self._mark_pending(event.src_path)

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

        log.info("Watchdog: 发现 %d 个 NFO 变化，开始处理...", len(ready))
        for nfo_path in ready:
            self._sync_one(nfo_path)
        log.info("Watchdog: %d 个 NFO 变更处理完成", len(ready))

    def _sync_one(self, nfo_path: str):
        """.nfo 变化 → JSON diff → DB 恢复，仅处理 cache 中已有的 category_id"""
        try:
            video_dir = os.path.dirname(nfo_path)

            # 从 .ugreen.json 获取 category_id 和扩展数据
            ug = ugreen.read_ugreen(video_dir)
            if ug is None:
                log.debug("Watchdog: 无 .ugreen.json，跳过 %s (需先运行一次定时同步)", nfo_path)
                return
            cat = ug.category_id
            if not cat:
                log.warning("Watchdog: .ugreen.json 无 category_id，跳过 %s", nfo_path)
                return

            # SQLite 单条查询，替代全量 load
            try:
                _sqlite_conn = st.open_db()
                try:
                    row = _sqlite_conn.execute(
                        "SELECT 1 FROM sync_cache WHERE category_id = ?", (cat,)
                    ).fetchone()
                finally:
                    _sqlite_conn.close()
            except (sqlite3.DatabaseError, OSError) as e:
                log.warning("Watchdog: 缓存查询失败 %s: %s", nfo_path, e)
                return
            if not row:
                log.info("Watchdog: category_id=%s 不在缓存中，跳过 (需先运行一次定时同步建立缓存)", cat)
                return

            # 读取 NFO 官方字段（仅当事件源是 .nfo 时）
            nfo = read_nfo(nfo_path) if nfo_path.endswith(".nfo") else None
            if nfo is None:
                # NFO 可能损坏，但 .ugreen.json 还在 → 创建最小骨架用于同步
                nfo = NfoRecord(nfo_path=nfo_path, video_dir=video_dir,
                                official=VideoMeta())

            # NFO 字段 → .ugreen.json 逐字段合并（仅 4 个保护字段，基于 nfo_snapshot diff）
            _nfo_field_map = {
                "title": ("name", str),
                "plot": ("introduction", str),
                "rating": ("score", float),
                "releasedate": ("release_date", None),  # 特殊转换
            }
            old_snapshot = ug.nfo_snapshot or {}
            new_snapshot = {}
            changed_count = 0

            for nfo_key, (ug_field, converter) in _nfo_field_map.items():
                raw = getattr(nfo.official, nfo_key, None)
                new_snapshot[nfo_key] = str(raw) if raw is not None else ""

                old_val = old_snapshot.get(nfo_key, "")
                if str(raw) == old_val:
                    continue  # NFO 中该字段未变化，保留 ugreen 值

                # NFO 中该字段有变化 → 合并到 ugreen
                if nfo_key == "releasedate":
                    from utils import date_str_to_int
                    v = date_str_to_int(raw) if raw else 0
                    if v:
                        setattr(ug, ug_field, v)
                        changed_count += 1
                elif raw:
                    setattr(ug, ug_field, converter(raw) if converter else raw)
                    changed_count += 1

            # 更新 NFO 快照并写回
            ug.nfo_snapshot = new_snapshot
            ugreen.write_ugreen(video_dir, ug)
            log.debug("Watchdog: NFO diff 完成, %d/4 字段更新, cat=%s", changed_count, cat)

            conn = connect()
            try:
                db_rec = queries.fetch_video_by_category(conn, cat)
                if db_rec is None:
                    log.warning("Watchdog: DB 无此记录 category_id=%s", cat)
                    return

                log.debug("Watchdog: JSON→DB %s cat=%s name=%s",
                         os.path.basename(nfo_path), cat, db_rec.name if db_rec else "")

                # 写入 DB：仅 14 个保护字段来自 .ugreen.json，NFO 字段不写 DB
                db_sync.sync_nfo_to_db(conn, nfo)

                # 用户编辑 NFO → 用文件 mtime 作为 utime；NFO 已删除则跳过 mtime 相关写入
                if os.path.exists(nfo_path):
                    nfo_mtime = int(os.path.getmtime(nfo_path))
                    with conn.cursor() as cur:
                        cur.execute(
                            "UPDATE ug_video_info SET utime = %s WHERE category_id = %s",
                            (nfo_mtime, cat),
                        )
                    conn.commit()

                    resolved_cat = cat
                    fresh = queries.fetch_video_by_category(conn, resolved_cat)
                    try:
                        _sc = st.open_db()
                        st.upsert_one(
                            _sc, resolved_cat,
                            fresh.ctime if fresh else 0, nfo_mtime,
                            db_vid=fresh.ug_video_info_id if fresh else 0,
                            max_mtime=nfo_mtime,
                        )
                        _sc.commit()
                    except (sqlite3.DatabaseError, OSError) as e:
                        log.warning("Watchdog: 缓存更新失败 %s: %s", nfo_path, e)
                    finally:
                        _sc.close()
                    log.debug("Watchdog: 完成 %s (cat=%s utime=%d)",
                             os.path.basename(nfo_path), resolved_cat, nfo_mtime)
                else:
                    log.debug("Watchdog: NFO 已删除，跳过 mtime 更新与缓存写入 %s",
                             nfo_path)
            except Exception:
                conn.rollback()
                log.error("Watchdog: DB 操作失败 %s", nfo_path, exc_info=True)
                raise
            finally:
                conn.close()
        except Exception as e:
            log.error("Watchdog: 处理失败 %s: %s", nfo_path, e)
