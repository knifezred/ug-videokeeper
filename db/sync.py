"""数据库写入 — .ugreen.json → DB 恢复 + 扩展数据写入"""
import os
import uuid
import psycopg2.extras
from typing import Optional
from config import log
from nfo import ugreen
from models import PlayHistory, Favorite, Collection, USER_EDITABLE_FIELDS
from utils import compute_file_hash


# ---- 共享更新辅助 ----

def _update_user_editable(conn, ug, cat: str):
    """用 .ugreen.json 中的用户可编辑字段更新 DB 对应行。
    供 sync_nfo_to_db 和 _restore_tv_from_ugreen 共用。
    """
    cols = list(USER_EDITABLE_FIELDS)
    set_clause = ", ".join(f"{c} = %s" for c in cols)
    params = [getattr(ug, c) for c in cols] + [cat]
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE ug_video_info SET {set_clause} WHERE category_id = %s",
            params,
        )


# ---- .ugreen.json → DB 恢复 ----

def sync_nfo_to_db(conn, nfo: "NfoRecord") -> int:
    """.ugreen.json → DB：恢复保护字段 + 播放记录/收藏/合集。
    供 executor 和 watcher 共用。NFO 字段不再写入 DB。
    """
    ug = ugreen.read_ugreen(nfo.video_dir)
    if ug is None:
        log.warning("sync_nfo_to_db: 无 .ugreen.json, 跳过 cat=%s", nfo.category_id)
        return 0

    cat = nfo.category_id or ug.category_id or ""
    if not cat:
        log.warning("sync_nfo_to_db: 无 category_id, 跳过")
        return 0

    # 目录移动 → 修正图片路径（新目录下搜索海报）
    from utils import fix_paths_for_video_dir
    fix_paths_for_video_dir(ug, nfo.video_dir)

    # 仅还原用户在 NAS UI 可编辑的字段（USER_EDITABLE_FIELDS）；
    # 其余字段仅写入 .ugreen.json 备份，恢复时不回写，避免旧备份覆盖 DB 新刮削值
    _update_user_editable(conn, ug, cat)
    log.debug("sync_nfo_to_db: UPDATE 用户可编辑字段 cat=%s", cat)

    # 扩展数据回写
    if ug.play_history:
        log.debug("sync_nfo_to_db: 写入 %d 条播放记录 cat=%s", len(ug.play_history), cat)
        upsert_play_history(conn, ug.play_history,
                            nfo.video_dir, os.path.basename(nfo.nfo_path), cat)
    if ug.favorites:
        log.debug("sync_nfo_to_db: 写入 %d 条收藏 cat=%s", len(ug.favorites), cat)
        upsert_favorites(conn, cat, ug.favorites)
    if ug.collection and ug.collection.name:
        log.debug("sync_nfo_to_db: 写入合集 %s cat=%s", ug.collection.name, cat)
        upsert_collection_for_video(conn, cat, ug.collection)
    # 演员仅备份到 .ugreen.json，不还原到 DB
    return ug.ug_video_info_id


# 演员仅备份到 .ugreen.json，不做还原到 DB 的其他处理
# （备份写入见 nfo/writer.py _build_ugreen_record）


# ---- 播放记录 ----

def upsert_play_history(conn, items: list[PlayHistory],
                        video_dir: str, nfo_filename: str,
                        category_id: str = ""):
    """三级匹配定位 file_info：hash_fingerprint → file_name+folder → folder+prefix。
    若 folder_path 直接查不到，用 category_id 兜底。
    每条播放记录独立匹配，匹配到则写入对应 file_id，否则跳过。
    """
    if not items:
        return

    nfo_prefix = os.path.splitext(nfo_filename)[0].lower() if nfo_filename else ""

    # 先按 folder_path 查
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT f.file_id, f.category_id, f.file_name, f.folder_path,
                      f.hash_fingerprint,
                      COALESCE(v.ug_video_info_id, 0) AS vid
               FROM file_info f
               LEFT JOIN ug_video_info v ON f.category_id = v.category_id
               WHERE f.folder_path = %s""",
            (video_dir,),
        )
        candidates = cur.fetchall()

    # folder_path 匹配不到 → 用 category_id 兜底
    if not candidates and category_id:
        log.warning("upsert_play_history: folder=%s 查不到 file_info，改用 category_id=%s 兜底",
                     video_dir, category_id)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT f.file_id, f.category_id, f.file_name, f.folder_path,
                          f.hash_fingerprint,
                          COALESCE(v.ug_video_info_id, 0) AS vid
                   FROM file_info f
                   LEFT JOIN ug_video_info v ON f.category_id = v.category_id
                   WHERE f.category_id = %s""",
                (category_id,),
            )
            candidates = cur.fetchall()

    if not candidates:
        log.warning("upsert_play_history: folder=%s 未匹配到 file_info", video_dir)
        return

    matched = []
    for ph in items:
        row = _match_file_info(ph, candidates, nfo_prefix)
        if row:
            matched.append((ph, row["file_id"], row["category_id"], row["vid"]))
        else:
            log.warning("upsert_play_history: ph uid=%s hash=%s → 未匹配",
                        ph.uid, ph.hash_fingerprint[:8] if ph.hash_fingerprint else "")

    if not matched:
        return

    # 按完整唯一约束键 (uid, category_id, file_id) 去重，只保留最新一条
    # （完整历史仍保留在 .ugreen.json 中）
    seen: dict[tuple, tuple] = {}
    for ph, fid, cat, vid in matched:
        key = (ph.uid, cat, fid)
        if key not in seen or ph.last_access_time > seen[key][0].last_access_time:
            seen[key] = (ph, fid, cat, vid)
    matched = list(seen.values())

    # 用 ON CONFLICT 让数据库自身保证唯一性：
    # 彻底消除「先 SELECT 查存在再分支 INSERT/UPDATE」的竞态与类型错配，
    # 同时兼容重复调用、历史数据已存在等所有场景。
    # 冲突时仅在 JSON 记录确实比 DB 更新（last_access_time 更大）才覆盖，
    # 否则保留 DB 已有的最新播放记录——绝不拿旧备份覆盖新进度。
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO play_history
               (uid, category_id, ug_video_info_id, file_id,
                media_lib_set_id, progress, current_play_time,
                last_access_time, watch_status, create_time, iso_ts)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (uid, category_id, file_id)
               DO UPDATE SET
                 ug_video_info_id = EXCLUDED.ug_video_info_id,
                 file_id          = EXCLUDED.file_id,
                 media_lib_set_id = EXCLUDED.media_lib_set_id,
                 progress         = EXCLUDED.progress,
                 current_play_time = EXCLUDED.current_play_time,
                 last_access_time = EXCLUDED.last_access_time,
                 watch_status    = EXCLUDED.watch_status,
                 create_time     = EXCLUDED.create_time,
                 iso_ts           = EXCLUDED.iso_ts
               WHERE EXCLUDED.last_access_time > play_history.last_access_time""",
            [(ph.uid, cat, vid, fid, ph.media_lib_set_id, ph.progress,
              ph.current_play_time, ph.last_access_time, ph.watch_status,
              ph.create_time, ph.iso_ts) for ph, fid, cat, vid in matched],
        )
    log.debug("upsert_play_history: 写入 %d/%d 条", len(matched), len(items))


def _match_file_info(ph: PlayHistory, candidates: list[dict], nfo_prefix: str) -> dict | None:
    """二级匹配：hash_fingerprint (含 strm 自算) → folder+prefix 兜底"""
    if ph.hash_fingerprint:
        for c in candidates:
            if c["hash_fingerprint"] and c["hash_fingerprint"] == ph.hash_fingerprint:
                log.debug("  ph uid=%s 命中 hash_fingerprint → file_id=%d",
                          ph.uid, c["file_id"])
                return c
        for c in candidates:
            if not c["hash_fingerprint"] and c["file_name"].endswith(".strm"):
                strm_path = os.path.join(c["folder_path"], c["file_name"])
                if os.path.isfile(strm_path):
                    try:
                        cur_hash = compute_file_hash(strm_path)
                    except OSError as e:
                        log.warning("strm hash 计算失败 %s: %s", strm_path, e)
                        continue
                    if cur_hash == ph.hash_fingerprint:
                        log.debug("  ph uid=%s 命中 strm hash → file_id=%d",
                                  ph.uid, c["file_id"])
                        return c

    if nfo_prefix:
        for c in candidates:
            if c["file_name"].lower().startswith(nfo_prefix):
                log.debug("  ph uid=%s 命中 folder+prefix → file_id=%d",
                          ph.uid, c["file_id"])
                return c

    return None


# ---- 收藏 ----

def upsert_favorites(conn, category_id: str, items: list[Favorite]):
    """按 (uid, once_id) 唯一约束，ON CONFLICT 批量写入，消除读改写反模式"""
    if not items:
        return
    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO favorites (uid, once_id, favorites_type, create_time)
               VALUES %s
               ON CONFLICT (uid, once_id)
               DO UPDATE SET
                 favorites_type = EXCLUDED.favorites_type,
                 create_time = EXCLUDED.create_time""",
            [(fav.uid, category_id, fav.favorites_type, fav.create_time)
             for fav in items],
        )
    log.debug("upsert_favorites: 写入 %d 条 cat=%s", len(items), category_id)


# ---- 合集 ----

def upsert_collection_for_video(conn, category_id: str, col: "Collection"):
    """确保合集存在（按 collection_id > name 匹配），写入全部字段，关联到视频"""
    if not col.name:
        return

    col_id = _find_or_create_collection(conn, col)
    if col_id:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ug_video_info SET collection_id = %s WHERE category_id = %s",
                (col_id, category_id)
            )


def _find_or_create_collection(conn, col: "Collection") -> Optional[str]:
    """按 collection_id 精确匹配，其次按 name 匹配；存在则 UPDATE，不存在则 INSERT"""
    with conn.cursor() as cur:
        if col.collection_id:
            cur.execute(
                "SELECT collection_id FROM ug_collection WHERE collection_id = %s",
                (col.collection_id,),
            )
            row = cur.fetchone()
            if row:
                _update_collection(conn, col)
                return row[0]

        cur.execute(
            "SELECT collection_id FROM ug_collection WHERE name = %s LIMIT 1",
            (col.name,),
        )
        row = cur.fetchone()
        if row:
            _update_collection(conn, col)
            return row[0]

    col_id = col.collection_id or f"ug_col_{uuid.uuid4().hex[:8]}"
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO ug_collection
               (name, collection_id, tmdb_id, pinyin_first, pinyin_full,
                poster_path, backdrop_path, language, introduction,
                is_manual_create, media_lib_set_id, year, score,
                category_id_list, ctime, utime, src_type, jp_name, cloud_id)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                       %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (col.name, col_id, str(col.tmdb_id), col.pinyin_first, col.pinyin_full,
             col.poster_path, col.backdrop_path, col.language, col.introduction,
             col.is_manual_create, col.media_lib_set_id, col.year, col.score,
             col.category_id_list, col.ctime, col.utime, col.src_type, col.jp_name,
             col.cloud_id),
        )
    return col_id


def _update_collection(conn, col: "Collection"):
    """更新已存在合集的全部字段"""
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE ug_collection SET
                 name = %s, tmdb_id = %s, pinyin_first = %s, pinyin_full = %s,
                 poster_path = %s, backdrop_path = %s, language = %s,
                 introduction = %s, is_manual_create = %s,
                 media_lib_set_id = %s, year = %s, score = %s,
                 category_id_list = %s, ctime = %s, utime = %s,
                 src_type = %s, jp_name = %s, cloud_id = %s
               WHERE collection_id = %s""",
            (col.name, str(col.tmdb_id), col.pinyin_first, col.pinyin_full,
             col.poster_path, col.backdrop_path, col.language, col.introduction,
             col.is_manual_create, col.media_lib_set_id, col.year, col.score,
             col.category_id_list, col.ctime, col.utime, col.src_type, col.jp_name,
             col.cloud_id, col.collection_id),
        )

