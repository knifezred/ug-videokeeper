"""数据库写入 — .ugreen.json → DB 恢复 + 扩展数据写入"""
import os
import uuid
import psycopg2.extras
from typing import Optional
from config import log
from nfo import ugreen
from models import Actor, PlayHistory, Favorite, Collection
from utils import compute_file_hash


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

    # category_id 变化 → 目录可能移动 → 修正图片路径
    if cat != ug.category_id:
        from utils import fix_paths_for_video_dir
        fix_paths_for_video_dir(ug, nfo.video_dir, cat_changed=True)

    with conn.cursor() as cur:
        cur.execute("""
            UPDATE ug_video_info SET
                name = %s, introduction = %s, score = %s,
                release_date = %s, country_list = %s, style_list = %s,
                poster_path = %s, backdrop_path = %s, logo_path = %s,
                ctime = %s, utime = %s
            WHERE category_id = %s""",
            (ug.name, ug.introduction, ug.score,
             ug.release_date, ug.country_list, ug.style_list,
             ug.poster_path, ug.backdrop_path, ug.logo_path,
             ug.ctime, ug.utime, cat),
        )
        log.debug("sync_nfo_to_db: UPDATE 保护字段 cat=%s", cat)

    # 扩展数据回写
    if ug.play_history:
        log.debug("sync_nfo_to_db: 写入 %d 条播放记录 cat=%s", len(ug.play_history), cat)
        upsert_play_history(conn, ug.play_history,
                            nfo.video_dir, os.path.basename(nfo.nfo_path))
    if ug.favorites:
        log.debug("sync_nfo_to_db: 写入 %d 条收藏 cat=%s", len(ug.favorites), cat)
        upsert_favorites(conn, cat, ug.favorites)
    if ug.collection and ug.collection.name:
        log.debug("sync_nfo_to_db: 写入合集 %s cat=%s", ug.collection.name, cat)
        upsert_collection_for_video(conn, cat, ug.collection)
    return ug.ug_video_info_id


# ---- 演员 ----

def upsert_actors(conn, category_id: str, actors: list[Actor],
                  media_lib_set_id: int = 0):
    """删除旧演员关联，写入新的"""
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM ug_video_actor_relation WHERE category_id = %s",
            (category_id,),
        )
    if not actors:
        log.debug("upsert_actors: 无演员, cat=%s", category_id)
        return

    once_ids = _ensure_actors_batch(conn, actors)
    values = [(category_id, a.role or "", oid, seq, media_lib_set_id)
              for seq, (a, oid) in enumerate(zip(actors, once_ids))]

    with conn.cursor() as cur:
        psycopg2.extras.execute_values(
            cur,
            """INSERT INTO ug_video_actor_relation
               (category_id, role, actor_once_id, actor_sequence, media_lib_set_id)
               VALUES %s""",
            values,
        )
    log.debug("upsert_actors: 写入 %d 个演员关联 cat=%s", len(values), category_id)


def _ensure_actors_batch(conn, actors: list[Actor]) -> list[str]:
    """批量查找或创建 ug_actor，返回 actor_once_id 列表（顺序与输入一致）"""
    if not actors:
        return []

    tmdb_ids = [a.tmdbid for a in actors if a.tmdbid]
    names = [a.name for a in actors]

    tmdb_map: dict[int, str] = {}
    if tmdb_ids:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tmdb_id, actor_once_id FROM ug_actor WHERE tmdb_id = ANY(%s)",
                (tmdb_ids,),
            )
            for row in cur.fetchall():
                tmdb_map[row[0]] = row[1]

    name_map: dict[str, str] = {}
    if names:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT name, actor_once_id FROM ug_actor WHERE name = ANY(%s)",
                (names,),
            )
            for row in cur.fetchall():
                name_map[row[0]] = row[1]

    results: list[str] = []
    to_insert: list[tuple] = []

    for a in actors:
        if a.tmdbid and a.tmdbid in tmdb_map:
            results.append(tmdb_map[a.tmdbid])
        elif a.name in name_map:
            results.append(name_map[a.name])
        else:
            once_id = f"ug_actor_{uuid.uuid4().hex[:8]}"
            results.append(once_id)
            to_insert.append((0, once_id, a.name, a.tmdbid or 0, 2))

    if to_insert:
        log.debug("_ensure_actors_batch: 创建 %d 个新演员", len(to_insert))
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO ug_actor (actor_id, actor_once_id, name, tmdb_id, actor_data_source)
                   VALUES %s""",
                to_insert,
            )

    return results


# ---- 播放记录 ----

def upsert_play_history(conn, items: list[PlayHistory],
                        video_dir: str, nfo_filename: str):
    """三级匹配定位 file_info：hash_fingerprint → file_name+folder → folder+prefix。
    每条播放记录独立匹配，匹配到则写入对应 file_id，否则跳过。
    """
    if not items:
        return

    nfo_prefix = os.path.splitext(nfo_filename)[0].lower() if nfo_filename else ""

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

    # 按 (uid, file_id) 去重，只保留最新一条（数据库只需要最新的播放进度）
    # 完整历史保留在 .ugreen.json 中
    seen: dict[tuple, tuple] = {}
    for ph, fid, cat, vid in matched:
        key = (ph.uid, fid)
        if key not in seen or ph.last_access_time > seen[key][0].last_access_time:
            seen[key] = (ph, fid, cat, vid)
    matched = list(seen.values())

    by_cat: dict[str, list] = {}
    for ph, fid, cat, vid in matched:
        by_cat.setdefault(cat, []).append((ph, fid, vid))

    with conn.cursor() as cur:
        for cat, group in by_cat.items():
            uids = [ph.uid for ph, _, _ in group]
            cur.execute(
                "SELECT uid FROM play_history WHERE category_id = %s AND uid = ANY(%s)",
                (cat, uids),
            )
            existing = {r[0] for r in cur.fetchall()}

            for ph, fid, vid in group:
                if ph.uid in existing:
                    cur.execute(
                        """UPDATE play_history
                           SET ug_video_info_id = %s, file_id = %s,
                               media_lib_set_id = %s, progress = %s,
                               current_play_time = %s, last_access_time = %s,
                               watch_status = %s, create_time = %s,
                               iso_ts = %s
                           WHERE category_id = %s AND uid = %s""",
                        (vid, fid, ph.media_lib_set_id, ph.progress,
                         ph.current_play_time, ph.last_access_time,
                         ph.watch_status, ph.create_time, ph.iso_ts,
                         cat, ph.uid),
                    )
                else:
                    cur.execute(
                        """INSERT INTO play_history
                           (uid, category_id, ug_video_info_id, file_id,
                            media_lib_set_id, progress, current_play_time,
                            last_access_time, watch_status, create_time,
                            iso_ts)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s,
                                   %s, %s)""",
                        (ph.uid, cat, vid, fid, ph.media_lib_set_id, ph.progress,
                         ph.current_play_time, ph.last_access_time,
                         ph.watch_status, ph.create_time, ph.iso_ts),
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
    """按 uid + once_id 批量匹配"""
    if not items:
        return
    uids = [fav.uid for fav in items]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT uid FROM favorites WHERE once_id = %s AND uid = ANY(%s)",
            (category_id, uids),
        )
        existing = {row[0] for row in cur.fetchall()}

    updates = [fav for fav in items if fav.uid in existing]
    inserts = [fav for fav in items if fav.uid not in existing]

    log.debug("upsert_favorites: cat=%s updates=%d inserts=%d",
              category_id, len(updates), len(inserts))

    if updates:
        with conn.cursor() as cur:
            cur.executemany(
                """UPDATE favorites SET favorites_type = %(ft)s, create_time = %(ct)s
                   WHERE once_id = %(once)s AND uid = %(uid)s""",
                [{"ft": fav.favorites_type, "ct": fav.create_time,
                  "once": category_id, "uid": fav.uid}
                 for fav in updates],
            )

    if inserts:
        with conn.cursor() as cur:
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO favorites (uid, once_id, favorites_type, create_time)
                   VALUES %s""",
                [(fav.uid, category_id, fav.favorites_type, fav.create_time)
                 for fav in inserts],
            )


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

