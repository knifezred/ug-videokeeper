# ug-videokeeper

> 绿联影视中心数据守护工具 —— PostgreSQL ↔ NFO 双向同步，保护播放记录、收藏、合集与用户编辑数据，防止重新刮削导致数据丢失。

## 为什么需要它

绿联影视中心重新刮削或媒体库重建时，`ug_video_info` 表会被重置（生成新的 `ug_video_info_id`），后果：

- 用户手动编辑的标题、简介、海报等信息消失
- 播放进度（`play_history`）因 `ug_video_info_id` 变化而断链
- 收藏（`favorites`）失效
- 合集归属（`ug_collection`）丢失

ug-videokeeper 将这些数据持久化为视频目录下的 `movie.nfo`，数据库被重建后自动回写。

## 同步策略（核心规则）

以 `category_id` 作为唯一业务标识，两阶段扫描，通过 `<ugreen>` 节点中的 `ctime`/`utime` 决策同步方向：

### 决策规则

| 场景 | 触发条件 | 同步方向 | 说明 |
|------|---------|:---:|------|
| 规则 1 | DB 有数据，本地无 NFO 文件 | **DB → NFO** | 新建 NFO 文件 |
| 规则 2 | 本地有 NFO 但无 `<ugreen>` 节点 | **DB → NFO** | 首次覆盖（历史遗留 NFO） |
| 规则 3.1 | `<ugreen>` 存在，ctime 一致，DB.utime > NFO.utime | **DB → NFO** | 用户在影视中心编辑了数据 |
| 规则 3.2 | `<ugreen>` 存在，DB.ctime > NFO.ctime | **NFO → DB** | 发生重新刮削，DB 记录被重建 |
| 规则 3.3 | `<ugreen>` 存在，ctime 和 utime 均一致 | **跳过** | 无变化 |
| 兜底 | DB 中无此 `category_id` 的记录 | **NFO → DB** | 数据被清空，从本地恢复 |

### 决策流程

```
Phase 1 ── 扫描本地 NFO 文件
    │
    ├─ DB 中无此 category_id ──→ NFO → DB
    │
    ├─ NFO 无 <ugreen> ──→ DB → NFO
    │
    └─ NFO 有 <ugreen>
         │
         ├─ DB.ctime > NFO.ctime ──→ NFO → DB    (规则 3.2: 重新刮削)
         │
         ├─ ctime 一致, DB.utime 更新 ──→ DB → NFO  (规则 3.1: 用户编辑)
         │
         ├─ ctime 一致, NFO.utime 更新 ──→ NFO → DB  (手动编辑 NFO)
         │
         └─ ctime+utime 均一致 ──→ 跳过            (规则 3.3)

Phase 2 ── 扫描 DB，查找无 NFO 的记录
    │
    └─ 创建 NFO 文件 ──→ DB → NFO               (规则 1)
```

## 涉及的数据表

| 类别 | 表名 | 同步到 NFO | 回写到 DB | 说明 |
|------|------|:---:|:---:|------|
| 文件信息 | `file_info` | ❌ | ❌ | 作为遍历驱动源，提供 `folder_path` 定位 NFO |
| 视频元数据 | `ug_video_info` | ✅ | ✅ | 核心同步目标 |
| 剧集 | `ug_television_episode` | ✅ | ✅ | |
| 合集 | `ug_collection` | ✅ | ✅ | |
| 演员 | `ug_actor` + `ug_video_actor_relation` | ✅ | ✅ | |
| 播放记录 | `play_history` | ✅ | ✅ | |
| 收藏 | `favorites` | ✅ | ✅ | |
| 媒体库配置 | `media_lib_set` | ❌ | ❌ | |

## NFO 文件格式

遵循[绿联官方 NFO 规范](https://support.ugnas.com/knowledgecenter/#/detail/eyJjb2RlIjoiMiYmNjY1In0=)，兼容 Jellyfin/Emby/Kodi。官方字段之外，绿联扩展数据统一放入 `<ugreen>` 命名空间节点，包含同步决策关键字段与用户行为数据。

**四种 NFO 类型：**

| NFO 文件 | 路径 | 根标签 | 说明 |
|---------|------|--------|------|
| `movie.nfo` | `{视频目录}/movie.nfo` | `<movie>` | 电影元数据 |
| `tvshow.nfo` | `{剧集根目录}/tvshow.nfo` | `<tvshow>` | 电视剧主信息 |
| `season.nfo` | `{剧集目录}/Season {N}/season.nfo` | `<season>` | 季信息、季间自动合集 |
| `{视频文件名}.nfo` | `{视频目录}/Season {N}/{视频文件名}.nfo` | `<episodedetails>` | 单集信息 |

**官方支持字段速查：**

| 字段 | 适用标签 | 说明 | 示例 |
|------|---------|------|------|
| `<title>` | 全部 | 标题 | `<title>肖申克的救赎</title>` |
| `<year>` | movie / tvshow | 年份 | `<year>1994</year>` |
| `<plot>` | 全部 | 简介 | `<plot>...</plot>` |
| `<tmdbid>` | movie / tvshow | TMDB ID | `<tmdbid>278</tmdbid>` |
| `<doubanid>` | movie / tvshow | 豆瓣 ID | `<doubanid>1292052</doubanid>` |
| `<releasedate>` | movie / tvshow | 播出日期 | `<releasedate>1994-09-10</releasedate>` |
| `<rating>` | movie / tvshow | 评分 | `<rating>9.7</rating>` |
| `<country>` | movie / tvshow | ISO 3166-1 三位数字码 | `<country>156</country>` (中国) |
| `<genre>` | movie / tvshow | 风格 ID 或名称 | `<genre>18</genre>` (剧情) |
| `<mpaa>` | movie / tvshow | 分级 | `<mpaa>PG-13</mpaa>` |
| `<season>` | episodedetails | 季编号 | `<season>1</season>` |
| `<episode>` | episodedetails | 集编号 | `<episode>1</episode>` |
| `<seasonnumber>` | season | 季编号 | `<seasonnumber>1</seasonnumber>` |
| `<actor>` (含子元素) | movie / tvshow | 演员 | 见模板 |

**风格 ID 对照表：**

| ID | 名称 | ID | 名称 |
|----|------|----|------|
| 18 | 剧情 | 10749 | 爱情 |
| 35 | 喜剧 | 53 | 惊悚 |
| 28 | 动作 | 80 | 犯罪 |
| 12 | 冒险 | 14 | 奇幻 |
| 9648 | 悬疑 | 10752 | 战争 |
| 878 | 科幻 | 16 | 动画 |
| 27 | 恐怖 | 10751 | 家庭 |
| 36 | 历史 | 99 | 纪录 |
| 10402 | 音乐 | 37 | 西部 |

**海报图片命名规范：**

| 类型 | 电影 | 电视剧 | 推荐尺寸 |
|------|------|--------|---------|
| 竖版海报 | `{视频文件名}-poster.jpg` | `poster.jpg` | 1080×1920 |
| 横版海报 | `{视频文件名}-fanart.jpg` | `fanart.jpg` | 1920×1080 |
| Logo | `{视频文件名}-logo.png` | `logo.png` | 800×310 |
| 季海报 | - | `season{N}-poster.jpg` | 1080×1920 |
| 集封面 | - | `{视频文件名}.jpg` | 1920×1080 |

**绿联扩展字段 `<ugreen>`：**

| 字段 | 说明 | 同步决策作用 |
|------|------|:---:|
| `ug_video_info_id` | DB 主键，用于判断是否重新刮削 | ✅ 核心 |
| `category_id` | 业务唯一标识，跨刮削不变 | ✅ 核心 |
| `use_nfo` | 是否使用本地 NFO | - |
| `media_lib_set_id` | 所属媒体库 ID | - |
| `ctime` / `utime` | 创建/更新时间戳（Unix 秒） | ✅ 用于比较新 |
| `play_history` | 播放进度与状态，可多个（按 uid 区分） | 回写 `play_history` 表 |
| `favorites` | 收藏标记，可多个（按 uid 区分） | 回写 `favorites` 表 |
| `collection` | 合集归属 | 回写 `ug_collection` 表 |
| `fileinfo` | 文件流信息（分辨率、编码、时长） | 只读 |

> 完整示例见 `examples/` 目录：
> - [肖申克的救赎/movie.nfo](examples/肖申克的救赎/movie.nfo)
> - [怪奇物语/tvshow.nfo](examples/怪奇物语/tvshow.nfo)
> - [怪奇物语/Season 1/season.nfo](examples/怪奇物语/Season%201/season.nfo)
> - [怪奇物语/Season 1/episode.nfo](examples/怪奇物语/Season%201/episode.nfo)

## 配置项

通过环境变量配置（12-Factor App 风格）：

| 环境变量 | 必填 | 默认值 | 说明 |
|---------|:---:|--------|------|
| `DB_HOST` | ✅ | - | PostgreSQL 主机地址 |
| `DB_PORT` | | `5433` | PostgreSQL 端口（绿联默认 5433） |
| `DB_NAME` | | `video` | 数据库名 |
| `DB_USER` | | `postgres` | 数据库用户 |
| `DB_PASSWORD` | | `""` | 数据库密码（绿联默认 trust 认证） |
| `MEDIA_LIB_PATHS` | | 已弃用（同步） | 仅用于 Watchdog 监控目录，同步本身由 `file_info.folder_path` 驱动 |
| `WATCHDOG_ENABLED` | | `true` | 是否启用 NFO 文件实时监控 |
| `WATCHDOG_DEBOUNCE` | | `3.0` | 文件稳定等待秒数（防抖） |
| `SCAN_INTERVAL` | | `3600` | 扫描间隔（秒），`0` 表示只执行一次后退出 |
| `SYNC_MODE` | | `bidirectional` | `export`(DB→NFO) / `import`(NFO→DB) / `bidirectional` |
| `DRY_RUN` | | `false` | 试运行，不实际写入 |
| `LOG_LEVEL` | | `INFO` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

## 部署

### Docker（推荐，无需自建镜像）

```bash
docker run -d \
  --name ug-videokeeper \
  --restart unless-stopped \
  -e DB_HOST=192.168.1.100 \
  -e MEDIA_LIB_PATHS=/media/movie:/media/tv \
  -v /你的绿联媒体目录:/media \
  python:3.11-slim \
  sh -c "pip install psycopg2-binary schedule && python /app/main.py"
```

### Docker Compose

```yaml
version: "3.8"
services:
  ug-videokeeper:
    image: python:3.11-slim
    container_name: ug-videokeeper
    restart: unless-stopped
    environment:
      - DB_HOST=192.168.1.100
      - DB_PORT=5433
      - DB_NAME=video
      - DB_USER=postgres
      - DB_PASSWORD=
      - MEDIA_LIB_PATHS=/media/movie:/media/tv
      - SCAN_INTERVAL=3600
      - SYNC_MODE=bidirectional
      - LOG_LEVEL=INFO
    volumes:
      - /你的绿联媒体目录:/media
      - ./app:/app
    working_dir: /app
    command: sh -c "pip install -r requirements.txt && python main.py"
```

启动：

```bash
docker-compose up -d
docker-compose logs -f ug-videokeeper
```

## 目录结构

```
ug-videokeeper/
├── README.md
├── requirements.txt           # psycopg2-binary, schedule
├── docker-compose.yml
├── main.py                    # 入口：连接 DB，启动调度器
├── config.py                  # 环境变量解析
├── db/
│   ├── __init__.py
│   ├── connection.py          # 数据库连接
│   └── queries.py             # 各表查询函数
├── nfo/
│   ├── __init__.py
│   ├── reader.py              # NFO → dict
│   └── writer.py              # dict → NFO
├── sync/
│   ├── __init__.py
│   ├── strategy.py            # 三种场景决策逻辑
│   └── executor.py            # 执行读写操作
├── examples/                  # NFO 示例（模拟绿联文件目录结构）
│   ├── 肖申克的救赎/
│   │   └── movie.nfo
│   └── 怪奇物语/
│       ├── tvshow.nfo
│       └── Season 1/
│           ├── season.nfo
│           └── episode.nfo
├── state.py                   # JSON 状态缓存（跳过无变化记录）
├── watcher.py                 # Watchdog NFO 实时监控
├── models.py                  # dataclass 定义
├── scheduler.py               # 定时调度 + Watchdog 管理
└── data/
    └── state.json              # 缓存快照 {category_id: {db_ctime, db_utime, nfo_mtime}}
```

## 同步执行流程

```
连接 PostgreSQL
  │
  ▼
SELECT * FROM file_info f
LEFT JOIN ug_video_info v ON f.category_id = v.category_id
  │
  ▼
┌────────── 遍历每条 file_info 记录 ──────────────────┐
│                                                       │
│  1. 取 folder_path，检测本地 NFO 是否存在              │
│                                                       │
│  ┌─ 无 NFO ──→ 规则 1: 从 DB 创建 movie.nfo           │
│  │                                                    │
│  └─ 有 NFO ──→ 读 NFO，查 ug_video_info               │
│       │                                               │
│       ├─ DB 无记录 ──→ NFO → DB                       │
│       │                                               │
│       └─ DB 有记录 ──→ 按规则决策：                    │
│            ├─ 无 <ugreen> ──→ [规则 2] DB → NFO        │
│            ├─ ctime 一致, DB.utime 新 ──→ [规则 3.1]   │
│            ├─ DB.ctime 新 ──→ [规则 3.2] (重新刮削)    │
│            └─ 时间一致 ──→ [规则 3.3] 跳过             │
│                                                       │
│  执行同步 + 附属数据（actor/play_history/favorites/    │
│  collection）                                         │
│                                                       │
└────────────── 提交事务 → 等待 SCAN_INTERVAL ──────────┘
```

## Watchdog 实时监控

周期同步之外，通过 `watchdog` 库实时监控 NFO 文件的 `modified` / `created` 事件：

```
┌───────────────────────────────────────────────────┐
│  文件系统事件                                      │
│    .nfo modified / created                        │
│         │                                         │
│         ▼ 防抖等待 WATCHDOG_DEBOUNCE 秒           │
│         │                                         │
│         ▼ 读取 NFO，连接 DB                        │
│         │                                         │
│         ▼ 执行 decide() → NFO→DB 即时回写          │
│         │                                         │
│         ▼ 更新 state.json 缓存                     │
└───────────────────────────────────────────────────┘
```

- 防抖机制：同一文件连续触发时只处理最后一次稳定后的状态
- 仅回写方向（NFO → DB）：用户手动编辑 NFO 的场景
- DB → NFO 方向仍由周期同步处理
- 可通过 `WATCHDOG_ENABLED=false` 关闭

**配置：**

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `WATCHDOG_ENABLED` | `true` | 是否启用实时监控 |
| `WATCHDOG_DEBOUNCE` | `3.0` | 防抖秒数 |
| `MEDIA_LIB_PATHS` | - | Watchdog 监控的根目录（多个用 `:` 分隔） |

## 回写数据库的风险与保护

写数据库是高危操作，因此在 `DRY_RUN` 模式下不会执行任何写入。生产部署时：

- 回写仅更新视频相关的 5 张表（`ug_video_info`、`ug_television_episode`、`ug_video_actor_relation`、`play_history`、`favorites`），不触及其他系统表
- 写操作必须在事务中完成，失败时整体回滚
- 每次回写前备份被修改的原始行到日志
- 首次运行建议用 `DRY_RUN=true` 验证扫描结果

## 开发

```bash
# 本地测试
pip install -r requirements.txt

# 试运行（不写入）
DRY_RUN=true \
DB_HOST=127.0.0.1 \
MEDIA_LIB_PATHS=/test/movie \
python main.py

# 单次同步
SCAN_INTERVAL=0 \
DB_HOST=127.0.0.1 \
MEDIA_LIB_PATHS=/test/movie \
python main.py
```

## FAQ

**Q: 为什么用 `python:3.11-slim` 而不是自建镜像？**
A: 减少维护负担。依赖只有 `psycopg2-binary` 和 `schedule`，启动时 pip 安装即可。如果你需要更快的启动速度，可以在 compose 中挂载一个 pip 缓存卷。

**Q: ug-videokeeper 如何找到 NFO 文件？**
A: 不再扫描文件系统。改为遍历 `file_info` 表，用每行的 `folder_path` 直接定位视频目录，在目录下查找 `movie.nfo` / `tvshow.nfo` / `season.nfo`。`file_info` 无对应目录时跳过。

**Q: 每次运行都会读所有 NFO 文件吗？**
A: 首次运行会。之后通过 `data/state.json` 缓存每个 `category_id` 的 DB `ctime`+`utime` 和 NFO 文件 `mtime`，匹配则直接跳过，避免全量 NFO 解析。只有 DB 或 NFO 发生变化时才触发同步。

**Q: 多个用户（uid）的播放记录怎么处理？**
A: NFO 中可以包含多个 `<ug_playhistory>` 节点，每个节点对应一个用户，通过 `<uid>` 区分。回写时按 uid 匹配更新或新建。
