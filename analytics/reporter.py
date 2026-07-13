"""观影报告生成器 — 扫描 .ugreen.json 聚合数据 → 输出 HTML"""
import json
import os
import html
import shutil
from collections import defaultdict, Counter
from datetime import datetime
from config import log, MEDIA_LIB_PATHS, TARGET_PATH

UGREEN_FILE = ".ugreen.json"
_REPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "reports"
)


def _scan_events(start_ts: int, end_ts: int) -> list[dict]:
    events = []
    scan_dirs = [p for p in (TARGET_PATH,) if p] or MEDIA_LIB_PATHS
    if not scan_dirs:
        scan_dirs = [p for p in MEDIA_LIB_PATHS if os.path.isdir(p)]
    scanned = 0
    for root in scan_dirs:
        for dirpath, _dirnames, filenames in os.walk(root):
            if UGREEN_FILE not in filenames:
                continue
            json_path = os.path.join(dirpath, UGREEN_FILE)
            try:
                with open(json_path, "rb") as f:
                    data = json.loads(f.read().decode("utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            scanned += 1
            cat_id = data.get("category_id", "") or ""
            name = data.get("name", "")
            style_list = data.get("style_list", [])
            poster = data.get("poster_path", "") or ""
            movie_year = data.get("year", 0) or 0
            country_list = data.get("country_list", []) or []
            for ph in data.get("play_history", []):
                ts = ph.get("last_access_time", 0)
                if start_ts <= ts < end_ts:
                    try:
                        _progress = float(ph.get("progress", 0))
                    except (ValueError, TypeError):
                        _progress = 0.0
                    try:
                        _play_time = int(ph.get("current_play_time", 0))
                    except (ValueError, TypeError):
                        _play_time = 0
                    events.append({
                        "uid": ph.get("uid", 0),
                        "video_name": name,
                        "style_list": list(style_list) if isinstance(style_list, list) else [],
                        "progress": _progress,
                        "play_time": _play_time,
                        "last_access": ts,
                        "poster_path": poster,
                        "movie_year": movie_year,
                        "country_list": list(country_list) if isinstance(country_list, list) else [],
                        "category_id": cat_id,
                    })
    log.info("报告扫描完成: %d 个 .ugreen.json, %d 条播放事件", scanned, len(events))
    return events


def _aggregate(events, year, month=None, week=None, db_conn=None):
    if not events:
        return {"empty": True, "year": year, "month": month, "week": week}
    unique_videos = set()
    total_play_seconds = 0
    completed = 0
    for e in events:
        unique_videos.add(e["video_name"])
        total_play_seconds += e["play_time"]
        if e["progress"] >= 0.9:
            completed += 1
    monthly_hours = defaultdict(float)
    monthly_movies = defaultdict(set)
    for e in events:
        m = datetime.fromtimestamp(e["last_access"]).month
        monthly_hours[m] += e["play_time"] / 3600
        monthly_movies[m].add(e["video_name"])
    weekday_hours = [0.0] * 7
    for e in events:
        wd = datetime.fromtimestamp(e["last_access"]).weekday()
        weekday_hours[wd] += e["play_time"] / 3600
    genre_count = defaultdict(int)
    for e in events:
        for g in e["style_list"]:
            genre_count[g] += 1
    top_genres = sorted(genre_count.items(), key=lambda x: -x[1])[:10]
    user_data = defaultdict(lambda: {"movies": set(), "hours": 0, "plays": 0})
    for e in events:
        ud = user_data[e["uid"]]
        ud["movies"].add(e["video_name"])
        ud["hours"] += e["play_time"] / 3600
        ud["plays"] += 1
    video_plays = defaultdict(int)
    poster_map = {}
    for e in events:
        video_plays[e["video_name"]] += 1
        if e["poster_path"] and e["video_name"] not in poster_map:
            poster_map[e["video_name"]] = e["poster_path"]
    top10list = sorted(video_plays.items(), key=lambda x: -x[1])[:10]
    play_days = sorted(set(
        datetime.fromtimestamp(e["last_access"]).date() for e in events
    ))
    longest_streak = 0
    cs = 1
    for i in range(1, len(play_days)):
        if (play_days[i] - play_days[i-1]).days == 1:
            cs += 1
            longest_streak = max(longest_streak, cs)
        else:
            cs = 1
    play_days_count = len(play_days)
    # 单日最大观影时长（真实值，用于"最长单日观影"）
    day_hours = defaultdict(float)
    for e in events:
        d = datetime.fromtimestamp(e["last_access"]).date()
        day_hours[d] += e["play_time"] / 3600
    max_day_hours = round(max(day_hours.values()), 1) if day_hours else 0

    # 完成度分布
    comp_tiers = [0, 0, 0, 0, 0]
    for e in events:
        p = e["progress"]
        if p >= 0.9: comp_tiers[4] += 1
        elif p >= 0.75: comp_tiers[3] += 1
        elif p >= 0.5: comp_tiers[2] += 1
        elif p >= 0.25: comp_tiers[1] += 1
        else: comp_tiers[0] += 1

    # 时段分布
    tod = [0, 0, 0, 0]
    tod_lbl = ["凌晨","上午","下午","晚上"]
    for e in events:
        h = datetime.fromtimestamp(e["last_access"]).hour
        if h < 6: tod[0] += 1
        elif h < 12: tod[1] += 1
        elif h < 18: tod[2] += 1
        else: tod[3] += 1

    # 年代分布
    decades = defaultdict(int)
    for e in events:
        y = e["movie_year"]
        if y > 1900:
            decades[(y // 10) * 10] += 1

    # 重看统计
    rewatched = sum(1 for c in video_plays.values() if c > 1)
    avg_plays = round(len(events) / len(unique_videos), 1) if unique_videos else 0

    # 首尾电影
    sorted_events = sorted(events, key=lambda e: e["last_access"])
    first_movie = sorted_events[0]["video_name"] if sorted_events else ""
    last_movie = sorted_events[-1]["video_name"] if sorted_events else ""

    # 国家分布
    country_count = Counter()
    for e in events:
        for c in e["country_list"]:
            country_count[c] += 1
    top_countries = country_count.most_common(5)

    # 演员聚合（可选，需提供 DB 连接）
    actor_count = Counter()
    if db_conn and events:
        from db.queries import fetch_actors
        seen_cats = set()
        for e in events:
            cid = e.get("category_id", "")
            if cid and cid not in seen_cats:
                seen_cats.add(cid)
                try:
                    actors = fetch_actors(db_conn, cid)
                    for a in actors:
                        actor_count[a.get("name", "")] += 1
                except Exception:
                    pass
    top_actors = actor_count.most_common(10)

    return {
        "empty": False, "year": year, "month": month, "week": week,
        "total_movies": len(unique_videos),
        "total_hours": round(total_play_seconds / 3600, 1),
        "total_plays": len(events),
        "completion_rate": round(completed / len(events) * 100, 1) if events else 0,
        "longest_streak": longest_streak,
        "play_days_count": play_days_count,
        "max_day_hours": max_day_hours,
        "rewatched": rewatched,
        "avg_plays": avg_plays,
        "first_movie": first_movie,
        "last_movie": last_movie,
        "comp_tiers": comp_tiers,
        "tod": [{"lbl": tod_lbl[i], "count": tod[i]} for i in range(4)],
        "decades": [{"dec": d, "count": c} for d, c in sorted(decades.items())],
        "monthly": [{"month": m, "hours": round(monthly_hours[m], 1),
                      "movies": len(monthly_movies[m])} for m in range(1, 13)],
        "weekday": [{"day": i, "name": ["一","二","三","四","五","六","日"][i],
                      "hours": round(weekday_hours[i], 1)} for i in range(7)],
        "genres": [{"id": g, "count": c, "name": _genre_name(g)} for g, c in top_genres],
        "countries": [{"id": c, "count": n} for c, n in top_countries],
        "top_actors": [{"name": n, "count": c} for n, c in top_actors],
        "top10": [{"name": n, "plays": c, "poster": poster_map.get(n, "")} for n, c in top10list],
        "users": [
            {"uid": uid, "movies": len(ud["movies"]),
             "hours": round(ud["hours"], 1), "plays": ud["plays"]}
            for uid, ud in sorted(user_data.items())
        ],
    }


_AVATARS = ["#e94560","#0f3460","#f59e0b","#10b981","#8b5cf6","#ec4899","#14b8a6"]

# 主题色配置：年度=金色 / 月度=蓝色 / 周度=紫色
_THEMES = {
    "annual": {
        "primary": "#d4a853", "primary_rgb": "212,168,83",
        "hero_from": "#1a1510", "hero_to": "#0d0a07",
        "glow": "rgba(212,168,83,0.12)",
        "badge_bg": "rgba(212,168,83,0.15)", "badge_color": "#d4a853",
        "tag": "\u5e74\u5ea6\u62a5\u544a",
    },
    "monthly": {
        "primary": "#4da6ff", "primary_rgb": "77,166,255",
        "hero_from": "#0a1628", "hero_to": "#061018",
        "glow": "rgba(77,166,255,0.1)",
        "badge_bg": "rgba(77,166,255,0.15)", "badge_color": "#4da6ff",
        "tag": "\u6708\u5ea6\u62a5\u544a",
    },
    "weekly": {
        "primary": "#c084fc", "primary_rgb": "192,132,252",
        "hero_from": "#120a1e", "hero_to": "#0a0614",
        "glow": "rgba(192,132,252,0.1)",
        "badge_bg": "rgba(192,132,252,0.15)", "badge_color": "#c084fc",
        "tag": "\u5468\u62a5\u544a",
    },
}

_GENRE_NAMES = {
    28: "\u52a8\u4f5c", 12: "\u5192\u9669", 16: "\u52a8\u753b", 35: "\u559c\u5267",
    80: "\u72af\u7f6a", 99: "\u7eaa\u5f55\u7247", 18: "\u5267\u60c5", 10751: "\u5bb6\u5ead",
    14: "\u5947\u5e7b", 36: "\u5386\u53f2", 27: "\u6050\u6016", 10402: "\u97f3\u4e50",
    9648: "\u60ac\u7591", 10749: "\u7231\u60c5", 878: "\u79d1\u5e7b", 10770: "\u7535\u89c6\u7535\u5f71",
    53: "\u60ac\u5ff5", 10752: "\u6218\u4e89", 37: "\u897f\u90e8",
}

def _genre_name(gid):
    return _GENRE_NAMES.get(gid, "\u7c7b\u578b" + str(gid))

_HTML_TPL = """<!DOCTYPE html><html lang="zh-CN"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#070b14;color:#e2e8f0;min-height:100vh;line-height:1.5}
.app{max-width:1120px;margin:0 auto;padding:20px 16px 40px}
.topbar{display:flex;align-items:center;justify-content:space-between;padding:16px 0 24px}
.topbar .logo{display:flex;align-items:center;gap:10px}
.topbar .logo-icon{width:32px;height:32px;border-radius:8px;background:linear-gradient(135deg,__PRIMARY__,rgba(__PRIMARY_RGB__,0.4));display:flex;align-items:center;justify-content:center;font-size:16px}
.topbar .logo-text{font-size:17px;font-weight:600;color:#f1f5f9}
.topbar .logo-sub{font-size:11px;color:rgba(255,255,255,0.35)}
.topbar .meta{display:flex;align-items:center;gap:16px;font-size:12px;color:rgba(255,255,255,0.4)}
.topbar .meta span{display:flex;align-items:center;gap:5px}
.status-dot{width:7px;height:7px;border-radius:50%;background:#22c55e;box-shadow:0 0 6px rgba(34,197,94,0.5)}
.hero-card{background:linear-gradient(135deg,__HERO_FROM__ 0%,__HERO_TO__ 100%);border:1px solid rgba(255,255,255,0.06);border-radius:18px;padding:36px 32px;position:relative;overflow:hidden;margin-bottom:20px}
.hero-card::before{content:'';position:absolute;top:-80px;right:-60px;width:280px;height:280px;background:radial-gradient(circle,__GLOW__ 0%,transparent 70%);pointer-events:none}
.hero-card::after{content:'';position:absolute;bottom:-100px;left:-40px;width:240px;height:240px;background:radial-gradient(circle,rgba(__PRIMARY_RGB__,0.05) 0%,transparent 70%);pointer-events:none}
.hero-tag{display:inline-flex;align-items:center;gap:6px;padding:5px 14px;border-radius:20px;background:__BADGE_BG__;color:__BADGE_COLOR__;font-size:12px;font-weight:600;margin-bottom:14px;position:relative;z-index:1}
.hero-year{font-size:56px;font-weight:700;color:__PRIMARY__;letter-spacing:-2px;line-height:1;position:relative;z-index:1;text-shadow:0 0 40px rgba(__PRIMARY_RGB__,0.2)}
.hero-title{font-size:18px;color:#f1f5f9;margin-top:6px;position:relative;z-index:1;font-weight:500}
.hero-desc{font-size:13px;color:rgba(255,255,255,0.4);margin-top:6px;position:relative;z-index:1}
.hero-date{position:absolute;top:20px;right:24px;font-size:12px;color:rgba(255,255,255,0.3);z-index:1}
.section-title{font-size:14px;font-weight:600;color:#f1f5f9;margin-bottom:14px;display:flex;align-items:center;gap:8px}
.section-title .dot{width:4px;height:16px;border-radius:2px;background:__PRIMARY__;flex-shrink:0}
.card{background:rgba(255,255,255,0.03);border:1px solid rgba(255,255,255,0.06);border-radius:14px;padding:20px;margin-bottom:16px}
.stats-row{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:16px}
.stat-box{text-align:center;padding:16px 8px;border-radius:12px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.04)}
.stat-box .s-num{font-size:28px;font-weight:700;color:__PRIMARY__;letter-spacing:-1px}
.stat-box .s-lbl{font-size:11px;color:rgba(255,255,255,0.4);margin-top:2px}
.stat-box .s-sub{font-size:10px;color:rgba(255,255,255,0.25);margin-top:1px}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:16px}
.chart-wrap{height:220px;position:relative}
.chart-full{height:200px;position:relative}
.poster-row{display:flex;gap:14px;overflow-x:auto;padding-bottom:8px;scrollbar-width:thin;scrollbar-color:rgba(255,255,255,0.1) transparent}
.poster-row::-webkit-scrollbar{height:5px}
.poster-row::-webkit-scrollbar-track{background:transparent}
.poster-row::-webkit-scrollbar-thumb{background:rgba(255,255,255,0.1);border-radius:4px}
.pitem{flex-shrink:0;width:130px;cursor:pointer;transition:transform 0.2s}
.pitem:hover{transform:translateY(-4px)}
.pitem .pimg{width:130px;height:185px;border-radius:10px;overflow:hidden;background:rgba(255,255,255,0.05)}
.pitem .pimg img{width:100%;height:100%;object-fit:cover;display:block}
.pitem .pimg .pfallback{width:100%;height:100%;display:flex;align-items:center;justify-content:center;font-size:36px;color:rgba(255,255,255,0.15)}
.pitem .prank{position:absolute;top:6px;left:6px;width:22px;height:22px;border-radius:6px;display:flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff;z-index:2}
.pitem .prank.r1{background:linear-gradient(135deg,#d4a853,#b8860b)}
.pitem .prank.r2{background:linear-gradient(135deg,#94a3b8,#64748b)}
.pitem .prank.r3{background:linear-gradient(135deg,#cd7f32,#a0522d)}
.pitem .prank.rx{background:rgba(255,255,255,0.15);backdrop-filter:blur(4px)}
.pitem .pwrap{position:relative;margin-bottom:8px}
.pitem .pname{font-size:12px;font-weight:500;color:#e2e8f0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:130px}
.pinfo{font-size:11px;color:rgba(255,255,255,0.4)}
.pinfo b{color:__PRIMARY__;font-weight:600}
.triple{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}
.t-item{text-align:center;padding:16px 8px;border-radius:10px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.04)}
.t-item .tlbl{font-size:11px;color:rgba(255,255,255,0.35);margin-bottom:6px}
.t-item .tval{font-size:15px;font-weight:600;color:#f1f5f9}
.t-item .tval-big{font-size:26px;font-weight:700;color:__PRIMARY__}
.user-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:10px}
.user-item{display:flex;align-items:center;gap:12px;padding:14px;border-radius:12px;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.04)}
.u-avatar{width:40px;height:40px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:600;color:#fff;flex-shrink:0}
.u-info .u-name{font-size:13px;font-weight:600;color:#f1f5f9}
.u-info .u-detail{font-size:11px;color:rgba(255,255,255,0.4);margin-top:2px}
.actor-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:12px}
.actor-item{background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.04);border-radius:12px;padding:16px;text-align:center}
.actor-item .ai-char{width:44px;height:44px;border-radius:50%;background:linear-gradient(135deg,__PRIMARY__,rgba(__PRIMARY_RGB__,0.4));display:flex;align-items:center;justify-content:center;margin:0 auto 10px;color:#fff;font-size:16px;font-weight:600}
.actor-item .ai-name{font-size:12px;font-weight:600;color:#e2e8f0}
.actor-item .ai-count{font-size:11px;color:rgba(255,255,255,0.4);margin-top:3px}
.footer{margin-top:24px;padding:16px;text-align:center;font-size:11px;color:rgba(255,255,255,0.2);border-top:1px solid rgba(255,255,255,0.04)}
@media(max-width:768px){
.stats-row{grid-template-columns:repeat(2,1fr)}.two-col{grid-template-columns:1fr}.triple{grid-template-columns:1fr}.hero-year{font-size:42px}.hero-card{padding:24px 20px}
.pitem{width:110px}.pitem .pimg,.pitem .pimg{width:110px;height:157px}
}
@media(max-width:480px){.stats-row{grid-template-columns:repeat(2,1fr)}.topbar{flex-direction:column;gap:10px;text-align:center}}
</style></head><body>
<div class="app">
<div class="topbar">
<div class="logo"><div class="logo-icon">\U0001F3AC</div><div><div class="logo-text">个人NAS观影报告</div><div class="logo-sub">你的专属观影数据洞察</div></div></div>
<div class="meta"><span>\u6570\u636E\u7edf\u8ba1\u622a\u6b62: __DATE__</span><span><i class="status-dot"></i> NAS \u5728\u7ebf</span></div>
</div>

<div class="hero-card">
<div class="hero-date">__RANGE__</div>
<div class="hero-tag">__TAG__</div>
<div class="hero-year">__YEAR_DISPLAY__</div>
<div class="hero-title">__TITLE_LINE__</div>
<div class="hero-desc">__DESC__</div>
</div>

<div class="stats-row">
<div class="stat-box"><div class="s-num">__MOVIES__</div><div class="s-lbl">观影部数</div><div class="s-sub">__MOVIES_CHG__</div></div>
<div class="stat-box"><div class="s-num">__HOURS__</div><div class="s-lbl">观看时长</div><div class="s-sub">\u8f85\u52bf __AVG_DAILY__h/\u5929</div></div>
<div class="stat-box"><div class="s-num">__COMPLETION__</div><div class="s-lbl">完播率</div><div class="s-sub">\u5171 __TOTAL_PLAYS__ \u6b21\u64ad\u653e</div></div>
<div class="stat-box"><div class="s-num">__STREAK__<small style="font-size:13px;color:rgba(255,255,255,0.3)"> 天</small></div><div class="s-lbl">最长连续</div><div class="s-sub">\u91cd\u770b <b style="color:__PRIMARY__">__REWATCHED__</b> \u90e8</div></div>
</div>

<div class="card">
<div class="section-title"><span class="dot"></span>年度总览</div>
<div class="two-col" style="margin-bottom:20px">
<div>
<div style="margin-bottom:12px"><div style="font-size:11px;color:rgba(255,255,255,0.35);margin-bottom:8px">观影偏好</div><div id="genre-mini"></div></div>
<div style="margin-bottom:12px"><div style="font-size:11px;color:rgba(255,255,255,0.35);margin-bottom:8px">地区分布</div><div id="country-mini" style="font-size:12px;color:rgba(255,255,255,0.5)"></div></div>
</div>
<div>
<div style="margin-bottom:12px"><div style="font-size:11px;color:rgba(255,255,255,0.35);margin-bottom:8px">类型分布</div><div class="chart-wrap"><canvas id="cg"></canvas></div></div>
</div>
</div>
<div class="triple">
<div class="t-item"><div class="tlbl">最长单日观影</div><div class="tval-big">__MAX_DAY_HOURS__<small style="font-size:12px;color:rgba(255,255,255,0.3)"> 小时</small></div></div>
<div class="t-item"><div class="tlbl">最爱的影片</div><div class="tval" style="max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;margin:0 auto">__FAV_MOVIE__</div><div class="pinfo" style="margin-top:4px">★ __FAV_SCORE__ · __FAV_PLAYS__ \u6b21</div></div>
<div class="t-item"><div class="tlbl">观影最高峰</div><div class="tval">__PEAK_DATE__</div><div class="pinfo" style="margin-top:4px">__PEAK_COUNT__ \u90e8\u7247</div></div>
</div>
</div>

<div class="card">
<div class="section-title"><span class="dot"></span>年度TOP10影片</div>
<div class="poster-row">__TOP10__</div>
</div>

<div class="two-col">
<div class="card">
<div class="section-title"><span class="dot"></span>每月观影时长</div>
<div class="chart-full"><canvas id="cm"></canvas></div>
</div>
<div class="card">
<div class="section-title"><span class="dot"></span>完成度分布</div>
<div class="chart-wrap"><canvas id="cct"></canvas></div>
</div>
</div>

<div class="two-col">
<div class="card">
<div class="section-title"><span class="dot"></span>星期几最爱看</div>
<div class="chart-wrap"><canvas id="cw"></canvas></div>
</div>
<div class="card">
<div class="section-title"><span class="dot"></span>最常观影时段</div>
<div class="chart-wrap"><canvas id="ctd"></canvas></div>
</div>
</div>

<div class="card" id="actors-sec" style="display:none">
<div class="section-title"><span class="dot"></span>出镜最多的演员</div>
<div class="actor-grid" id="actor-grid"></div>
</div>

<div class="card">
<div class="section-title"><span class="dot"></span>家庭成员</div>
<div class="user-grid">__USER_LIST__</div>
</div>

<div class="footer">电影是生活的镜子，愿每一帧都值得铭记 —— <b style="color:__PRIMARY__">NAS</b> · 数据驱动</div>
</div>
<script>
const _M=__MONTHLY_JSON__,_W=__WEEKDAY_JSON__,__G=__GENRE_JSON__;
const _CT=__COMP_TIERS__,_TD=__TOD_JSON__,__DC=__DECADES_JSON__,__CO=__COUNTRIES_JSON__,__AC=__ACTORS_JSON__;
const _PC='__PRIMARY__',_PR='__PRIMARY_RGB__';

if(__AC&&__AC.length){
 document.getElementById('actors-sec').style.display='';
 var ag=document.getElementById('actor-grid');
 __AC.slice(0,12).forEach(function(a){
  ag.innerHTML+='<div class="actor-item"><div class="ai-char">'+html.escape(a.name).charAt(0)+'</div><div class="ai-name">'+html.escape(a.name)+'</div><div class="ai-count">'+a.count+' 次</div></div>';
 });
}

var _CH=[_PC,'#22c55e','#f97316','#c084fc','#ec4899','#14b8a6','#eab308','#f43f5e','#6366f1','#8b5cf6'];
function _darkTooltip(){return{backgroundColor:'rgba(15,23,42,0.95)',cornerRadius:8,titleColor:'#f1f5f9',bodyColor:'#94a3b8',padding:10,boxPadding:4,titleFont:{size:12},bodyFont:{size:11}}}
function _darkGrid(c){return{color:c||'rgba(255,255,255,0.05)',drawBorder:false}}

new Chart(document.getElementById('cm'),{type:'bar',data:{labels:_M.map(function(m){return m.month+'\u6708'}),datasets:[{label:'h',data:_M.map(function(m){return m.hours}),backgroundColor:function(ctx){var i=ctx.dataIndex;return _CH[i%_CH.length]+'30'},borderColor:_CH,borderWidth:1.5,borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:_darkTooltip()},scales:{y:{beginAtZero:true,grid:_darkGrid(),ticks:{color:'rgba(255,255,255,0.35)',font:{size:10}}},x:{grid:{display:false},ticks:{color:'rgba(255,255,255,0.35)',font:{size:10}}}}}});
new Chart(document.getElementById('cg'),{type:'doughnut',data:{labels:__G.map(function(g){return g.name}),datasets:[{data:__G.map(function(g){return g.count}),backgroundColor:_CH.slice(0,__G.length),borderWidth:0}]},options:{responsive:true,maintainAspectRatio:false,cutout:'58%',plugins:{legend:{position:'bottom',labels:{padding:12,font:{size:11},color:'rgba(255,255,255,0.5)',usePointStyle:true,pointStyle:'circle'}},tooltip:_darkTooltip()}}});
new Chart(document.getElementById('cw'),{type:'bar',data:{labels:_W.map(function(w){return '\u5468'+w.name}),datasets:[{label:'h',data:_W.map(function(w){return w.hours}),backgroundColor:_PC+'28',borderColor:_PC,borderWidth:1.5,borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:_darkTooltip()},scales:{y:{beginAtZero:true,grid:_darkGrid(),ticks:{color:'rgba(255,255,255,0.35)',font:{size:10}}},x:{grid:{display:false},ticks:{color:'rgba(255,255,255,0.35)',font:{size:10}}}}}});
new Chart(document.getElementById('cct'),{type:'bar',data:{labels:['<25%','25-50%','50-75%','75-90%','90%+'],datasets:[{label:'n',data:_CT,backgroundColor:['rgba(244,63,94,0.25)','rgba(249,115,22,0.25)','rgba(234,179,8,0.25)','rgba(34,197,94,0.25)',_PC+'40'],borderColor:['#f43f5e','#f97316','#eab308','#22c55e',_PC],borderWidth:1.5,borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,indexAxis:'y',plugins:{legend:{display:false},tooltip:_darkTooltip()},scales:{x:{beginAtZero:true,grid:_darkGrid(),ticks:{color:'rgba(255,255,255,0.35)',font:{size:10}}},y:{grid:{display:false},ticks:{color:'rgba(255,255,255,0.45)',font:{size:11}}}}}});
new Chart(document.getElementById('ctd'),{type:'bar',data:{labels:_TD.map(function(t){return t.lbl}),datasets:[{label:'n',data:_TD.map(function(t){return t.count}),backgroundColor:['rgba(100,116,139,0.2)','#3b82f630','#f9731630','#a855f730'],borderColor:['#64748b','#3b82f6','#f97316','#a855f7'],borderWidth:1.5,borderRadius:4}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:_darkTooltip()},scales:{y:{beginAtZero:true,grid:_darkGrid(),ticks:{color:'rgba(255,255,255,0.35)',font:{size:10}}},x:{grid:{display:false},ticks:{color:'rgba(255,255,255,0.45)',font:{size:11}}}}}});

if(__CO&&__CO.length){var cm=document.getElementById('country-mini');cm.innerHTML=__CO.map(function(c){return '<span style="display:inline-block;margin:4px 8px 4px 0;color:rgba(255,255,255,0.5)">'+html.escape(String(c.id))+' <b style="color:'+_PC+'">'+c.count+'</b></span>';}).join('')}
if(__G&&__G.length){var gm=document.getElementById('genre-mini');gm.innerHTML='<div style="display:flex;flex-wrap:wrap;gap:6px">'+__G.slice(0,6).map(function(g){return '<span style="padding:3px 10px;border-radius:12px;background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.06);font-size:11px;color:rgba(255,255,255,0.6)">'+html.escape(g.name)+' <b style="color:'+_PC+'">'+g.count+'%</b></span>'}).join('')+'</div>'}
</script></body></html>"""


def _build_top10_item(idx, item, poster_dir):
    """生成横排海报卡片：130x185 海报 + 排名角标 + 片名"""
    rank_cls = "r1" if idx == 0 else ("r2" if idx == 1 else ("r3" if idx == 2 else "rx"))
    poster_src = ""
    if poster_dir and item.get("poster"):
        src = item["poster"]
        if os.path.isfile(src):
            ext = os.path.splitext(src)[1] or ".jpg"
            safe_name = item["name"].replace("/", "_").replace("\\", "_")
            dest = os.path.join(poster_dir, safe_name + ext)
            try:
                shutil.copy2(src, dest)
                poster_src = "posters/" + safe_name + ext
            except (OSError, shutil.Error):
                pass
    if poster_src:
        img_html = '<img src="%s" alt="" loading="lazy">' % poster_src
    else:
        img_html = '<div class="pfallback">%s</div>' % chr(0x1F3AC)
    return (
        '<div class="pitem">'
        '<div class="pwrap">'
        '%s'
        '<div class="prank %s">%d</div>'
        '</div>'
        '<div class="pname" title="%s">%s</div>'
        '</div>'
    ) % (img_html, rank_cls, idx + 1,
         html.escape(item["name"], quote=True),
         html.escape(item["name"][:14] + ("..." if len(item["name"]) > 14 else "")))


def _build_html(data, report_type, report_dir=None):
    """按深色仪表盘风格构建报告 HTML，根据 report_type 自动切换主题色"""
    theme = _THEMES.get(report_type, _THEMES["annual"])
    title = "{y}年{r}{w}观影报告".format(
        y=data.get("year", ""),
        r=("{m}月".format(m=data.get("month", 0))) if report_type == "monthly" else "",
        w=(" 第{w}周".format(w=data.get("week", 0))) if report_type == "weekly" else "",
    )
    if data.get("empty"):
        return (
            '<!DOCTYPE html><html><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>%s</title>'
            '<style>body{margin:0;padding:40px 20px;font-family:-apple-system,sans-serif;'
            'background:#070b14;text-align:center;color:rgba(255,255,255,0.4)}'
            'h1{font-size:20px;font-weight:500;color:#f1f5f9}</style></head>'
            '<body><h1>%s</h1><p>暂无播放记录</p></body></html>'
        ) % (title, title)

    poster_dir = os.path.join(report_dir, "posters") if report_dir else None
    if poster_dir:
        os.makedirs(poster_dir, exist_ok=True)
    top10_html = "".join(
        _build_top10_item(i, item, poster_dir) for i, item in enumerate(data["top10"])
    )

    # 用户列表
    user_html = "".join(
        '<div class="user-item"><div class="uavatar" style="background:{bg}">{abbr}</div>'
        '<div class="u-info"><div class="u-name">用户{uid}</div>'
        '<div class="u-detail">{movies} 部 · {hours}h · {plays} 次</div></div></div>'
        .format(bg=_AVATARS[idx % len(_AVATARS)], abbr=html.escape(str(u["uid"])[:2]),
                uid=html.escape(str(u["uid"])), movies=u["movies"],
                hours=round(u["hours"], 1), plays=u["plays"])
        for idx, u in enumerate(data["users"])
    )

    # 年度显示文本
    year_val = data.get("year", "")
    if report_type == "monthly":
        year_display = "%04d年%02d月" % (year_val, data.get("month", 0))
    elif report_type == "weekly":
        year_display = "%04d年 第%d周" % (year_val, data.get("week", 0))
    else:
        year_display = str(year_val)

    # 时间范围
    if report_type == "monthly":
        range_text = "%02d.01 – %02d.%s" % (
            data.get("month", 0), data.get("month", 0),
            "末" if data.get("month", 0) in [1,3,5,7,8,10,12] else ("30" if data.get("month", 0) not in [2] else "28/29")
        )
    elif report_type == "weekly":
        range_text = "W%s – %d天" % (data.get("week", 0), 7)
    else:
        range_text = "01.01 – 12.31"

    # 统计数据
    total_movies = data.get("total_movies", 0)
    total_hours = data.get("total_hours", 0)
    total_plays = data.get("total_plays", 0)
    completion = data.get("completion_rate", 0)
    streak = data.get("longest_streak", 0)
    rewatched = data.get("rewatched", 0)

    # 真实衍生指标（均来自已聚合数据，不再编造）
    play_days_count = data.get("play_days_count", 0)
    avg_daily = round(total_hours / max(play_days_count, 1), 1) if play_days_count else 0
    max_day_hours = data.get("max_day_hours", 0)

    # 最爱影片（取 top1）
    fav_movie = ""
    fav_plays = 0
    if data.get("top10"):
        fav_movie = data["top10"][0]["name"]
        fav_plays = data["top10"][0]["plays"]
    # 该影片占全部播放次数的真实比例（无评分数据，用占比代替虚构"评分"）
    fav_share = round(fav_plays / max(total_plays, 1) * 100, 1) if total_plays else 0

    # 最高峰日期：从 monthly 数据找观看时长最高的月份
    peak_date = "—"
    peak_count = 0
    months_data = data.get("monthly", [])
    if months_data:
        peak_month = max(months_data, key=lambda m: m.get("hours", 0))
        peak_date = "%d月" % peak_month.get("month", 0)
        peak_count = peak_month.get("movies", 0)

    # 年度同比（仅年度报真实计算；其它类型不编造）
    movies_chg = "—"
    if report_type == "annual":
        prev_start = int(datetime(year_val - 1, 1, 1).timestamp())
        prev_end = int(datetime(year_val, 1, 1).timestamp())
        prev_data = _aggregate(_scan_events(prev_start, prev_end), year_val - 1)
        prev_count = prev_data.get("total_movies", 0)
        if prev_count:
            movies_chg = "较去年 %+d%%" % round((total_movies - prev_count) / prev_count * 100)
        else:
            movies_chg = "较去年 新"

    h = _HTML_TPL
    replacements = [
        ("__TITLE__", title),
        ("__DATE__", datetime.now().strftime("%Y-%m-%d")),
        ("__PRIMARY__", theme["primary"]),
        ("__PRIMARY_RGB__", theme["primary_rgb"]),
        ("__HERO_FROM__", theme["hero_from"]),
        ("__HERO_TO__", theme["hero_to"]),
        ("__GLOW__", theme["glow"]),
        ("__BADGE_BG__", theme["badge_bg"]),
        ("__BADGE_COLOR__", theme["badge_color"]),
        ("__TAG__", theme["tag"]),
        ("__YEAR_DISPLAY__", year_display),
        ("__TITLE_LINE__", title),
        ("__DESC__",
         "这一年，光影陪伴你的每一刻都值得珍藏" if report_type == "annual"
         else "每一部影片，都是生活的注脚" if report_type == "monthly"
         else "一周时光，银幕流转不停"),
        ("__RANGE__", range_text),
        ("__MOVIES__", str(total_movies)),
        ("__HOURS__", ("%.1f" % total_hours) if isinstance(total_hours, float) else str(total_hours)),
        ("__COMPLETION__", ("%.1f%%" % completion)),
        ("__STREAK__", str(streak)),
        ("__REWATCHED__", str(rewatched)),
        ("__TOTAL_PLAYS__", str(total_plays)),
        ("__MOVIES_CHG__", movies_chg),
        ("__AVG_DAILY__", str(avg_daily)),
        ("__MAX_DAY_HOURS__", str(max_day_hours)),
        ("__FAV_MOVIE__", html.escape(fav_movie[:12] + ("..." if len(fav_movie) > 12 else ""))),
        ("__FAV_SCORE__", "%.1f%%" % fav_share),
        ("__FAV_PLAYS__", str(fav_plays)),
        ("__PEAK_DATE__", peak_date),
        ("__PEAK_COUNT__", str(peak_count)),
        ("__TOP10__", top10_html),
        ("__USER_LIST__", user_html),
        ("__COMP_TIERS__", json.dumps(data.get("comp_tiers", []))),
        ("__TOD_JSON__", json.dumps(data.get("tod", []))),
        ("__DECADES_JSON__", json.dumps(data.get("decades", []))),
        ("__GENRE_JSON__", json.dumps(data.get("genres", []))),
        ("__COUNTRIES_JSON__", json.dumps(data.get("countries", []))),
        ("__MONTHLY_JSON__", json.dumps(data.get("monthly", []))),
        ("__WEEKDAY_JSON__", json.dumps(data.get("weekday", []))),
        ("__ACTORS_JSON__", json.dumps(data.get("top_actors", []))),
    ]
    for old, new in replacements:
        h = h.replace(old, new)
    return h


def generate_report(report_type, year, month=None, week=None, db_conn=None):
    now = datetime.now()
    if report_type == "annual":
        start_ts = int(datetime(year, 1, 1).timestamp())
        end_ts = int(datetime(year + 1, 1, 1).timestamp())
    elif report_type == "monthly":
        start_ts = int(datetime(year, month, 1).timestamp())
        end_ts = int(datetime(year + 1 if month == 12 else year, month + 1 if month < 12 else 1, 1).timestamp())
    elif report_type == "weekly":
        import datetime as dt_mod
        first_day = dt_mod.date.fromisocalendar(year, week, 1)
        start_ts = int(datetime.combine(first_day, datetime.min.time()).timestamp())
        end_ts = start_ts + 7 * 86400
    else:
        log.warning("未知报告类型: %s", report_type)
        return
    log.info("生成报告: %s %d-%s", report_type, year,
             ("%02d" % month) if month else ("W%02d" % week) if week else "")
    events = _scan_events(start_ts, end_ts)
    data = _aggregate(events, year, month, week, db_conn=db_conn)
    year_dir = os.path.join(_REPORTS_DIR, str(year))
    os.makedirs(year_dir, exist_ok=True)
    fname = "annual.html" if report_type == "annual" else \
            ("%02d.html" % month) if report_type == "monthly" else ("W%02d.html" % week)
    path = os.path.join(year_dir, fname)
    html = _build_html(data, report_type, report_dir=year_dir)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    log.info("报告已写入: %s", path)


def generate_scheduled_reports():
    from datetime import date, timedelta
    today = date.today()
    if today.weekday() == 0:
        lw = today - timedelta(days=7)
        iso = lw.isocalendar()
        generate_report("weekly", iso[0], week=iso[1])
    if today.day == 1:
        lm = today.replace(day=1) - timedelta(days=1)
        generate_report("monthly", lm.year, month=lm.month)
    if today.month == 1 and today.day == 1:
        generate_report("annual", today.year - 1)
