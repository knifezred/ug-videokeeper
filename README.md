# ug-videokeeper

> 绿联影视中心数据守护工具。保护你的播放记录、收藏、合集和手动编辑数据，防止重新刮削导致数据丢失。

---

## 一、项目介绍

### 核心目标

绿联影视中心在重新刮削或媒体库重建时，会重置视频元数据表，导致：

- 你手动编辑的标题、简介、评分 —— **消失**
- 你和家人的播放进度 —— **断链**
- 收藏、合集归属 —— **丢失**

**ug-videokeeper 的目标很简单：刮削前后，数据一致。**

### 实现方式

项目在每部视频目录下自动维护一个隐藏文件 `.ugreen.json`（绿联 NAS 默认不显示 `.` 开头的文件），全量备份 `ug_video_info` 全部字段 + 播放记录 + 收藏 + 合集 + 剧集列表。当数据库被刮削重置后，从这些备份文件中恢复全部数据。

**项目不写入、不修改、不依赖任何 NFO 文件。** 数据流转完全基于 `.ugreen.json`。

### 数据流

```
绿联重刮
  → 检测 category_id 变化或 ctime 增大
  → 从 .ugreen.json 恢复 35 个字段到 DB

用户播放/收藏/编辑合集
  → 检测 max_mtime（5 张表最新时间戳）增大
  → 从 DB 备份到 .ugreen.json

用户编辑视频元数据（utime 不变）
  → 检测 9 个关键字段的 MD5 哈希变化
  → 从 DB 备份到 .ugreen.json

手动编辑 movie.nfo
  → Watchdog 检测到变化
  → 合并 NFO 的 7 个字段到 .ugreen.json
  → 恢复合并后的 .ugreen.json 到 DB
```

### 核心功能

| 功能 | 说明 |
|------|------|
| 定时周期同步 | 每隔指定时间（默认 1 小时）检查数据库是否有变化，自动备份或恢复 |
| Watchdog 实时监控 | 检测到 NFO 文件被手动编辑后，合并 NFO 字段到 `.ugreen.json`，写回数据库 |
| 播放记录完整历史 | `.ugreen.json` 保存全部播放记录，新旧合并去重，不丢历史 |
| 安全写入 | `DRY_RUN` 模式可预览操作，不实际写入数据库 |

---

## 二、实际场景

### 场景 1：刮削后数据还在

你在影视中心里编辑了电影标题、修改了简介、标记了收藏——然后点了"重新刮削"。

**有了 ug-videokeeper，刮削后：**

- ✅ 你编辑的标题、简介、评分——恢复
- ✅ 你和家人的播放进度——恢复
- ✅ 收藏、合集归属——恢复

### 场景 2：你手动改了 NFO 文件

你打开 `movie.nfo`，把标题改成自己喜欢的名字，保存。

**Watchdog 合并 NFO 到 `.ugreen.json`，写入 DB。** 周期同步也保护这个值。

### 场景 3：你把视频文件夹移到了新硬盘

从 `/volume1/media/电影/肖申克的救赎` 移到 `/volume2/media/电影/肖申克的救赎`。

绿联重新扫描后，`category_id` 会变。程序从 `file_info` 获取最新 `category_id`，`.ugreen.json` 跟着目录走，播放记录通过哈希匹配，全部恢复。

### 场景 4：你重命名了视频文件

`Inception_4K.mkv` → `盗梦空间 4K.mkv`

播放记录基于文件内容哈希匹配文件，改名不影响匹配。

### 数据保护范围

| 你的操作 | 保护方式 |
|---------|---------|
| 在影视中心编辑标题/简介/评分 | content_hash 检测变化 → DB→JSON 备份 |
| 观看视频（播放进度） | max_mtime 检测变化 → DB→JSON 备份，保存完整历史 |
| 标记收藏 | max_mtime 检测 → 直接覆盖 JSON |
| 编辑合集 | max_mtime 检测 → 直接覆盖 JSON |
| 手动编辑 `movie.nfo` | Watchdog 合并到 JSON → 写回 DB |
| 移动文件夹到新路径 | 从 file_info 获取最新 category_id 恢复 |
| 重命名文件 | 内容哈希不变，播放记录不丢失 |
| 删除 `.ugreen.json` | 下次周期同步时从数据库自动重建 |

---

## 三、开发与部署

### 前置条件

- 绿联 NAS（或任何运行绿联影视中心的设备）
- Docker（推荐）或 Python 3.11+
- PostgreSQL 数据库（绿联影视中心使用，默认端口 5433）

### 配置项

| 环境变量 | 必填 | 默认值 | 说明 |
|---------|:---:|--------|------|
| `DB_HOST` | ✅ | - | PostgreSQL 主机地址 |
| `DB_PORT` | | `5433` | 数据库端口 |
| `DB_NAME` | | `video` | 数据库名 |
| `DB_USER` | | `postgres` | 数据库用户 |
| `DB_PASSWORD` | | `""` | 数据库密码 |
| `MEDIA_LIB_PATHS` | | `""` | Watchdog 监控的媒体目录（多个用 `:` 分隔） |
| `WATCHDOG_ENABLED` | | `true` | 启用 NFO 文件实时监控 |
| `WATCHDOG_DEBOUNCE` | | `3.0` | 文件防抖秒数 |
| `SCAN_INTERVAL` | | `3600` | 周期同步间隔（秒），`0` 表示仅运行一次后进入纯 Watchdog 模式 |
| `DRY_RUN` | | `false` | 试运行，不实际写入 |
| `TARGET_PATH` | | 空 | 限定同步路径范围，仅处理该路径前缀下的视频。用于小范围测试 |
| `LOG_LEVEL` | | `INFO` | 日志级别：`DEBUG` / `INFO` / `WARNING` / `ERROR` |

### Docker Compose

```yaml
version: "3.8"
services:
  ug-videokeeper:
    image: python:3.11-slim
    container_name: ug-videokeeper
    restart: unless-stopped
    environment:
      - DB_HOST=127.0.0.1
      - DB_PORT=5433
      - DB_NAME=video
      - DB_USER=postgres
      - DB_PASSWORD=
      - SCAN_INTERVAL=3600
      - LOG_LEVEL=INFO
      - WATCHDOG_ENABLED=true
      - WATCHDOG_DEBOUNCE=3.0
      - MEDIA_LIB_PATHS=/volume4/disk4/library:/volume3/云盘下载
    volumes:
      - /volume4/disk4/library:/volume4/disk4/library
      - /volume3/云盘下载:/volume3/云盘下载
      - ./app:/app
    working_dir: /app
    command: sh -c "pip install -r requirements.txt && python main.py"
```

### 首次运行建议

1. 先用 `DRY_RUN=true` 跑一次，查看日志确认程序能正常连接数据库、识别视频文件
2. 确认无误后关闭 `DRY_RUN`，正式运行
3. 首次同步会为每部视频创建 `.ugreen.json` 备份文件，建立本地缓存
4. 之后每次周期同步只检查有变化的记录

### 目录结构

```
ug-videokeeper/
├── main.py                    # 入口
├── checks.py                  # 启动自检
├── config.py                  # 配置解析
├── models.py                  # 数据模型
├── utils.py                   # 工具函数
├── scheduler.py               # 定时调度 + Watchdog 管理
├── state.py                   # 状态缓存
├── watcher.py                 # Watchdog 实时监控
├── db/
│   ├── connection.py          # 数据库连接
│   ├── queries.py             # 数据库查询
│   └── sync.py                # 数据库写入
├── nfo/
│   ├── reader.py              # NFO 文件读取
│   ├── writer.py              # .ugreen.json 写入
│   └── ugreen.py              # .ugreen.json 读写
├── sync/
│   ├── strategy.py            # 同步决策
│   └── executor.py            # 同步执行
└── data/
    └── state.json             # 同步缓存
```

### FAQ

**Q: 为什么用 `python:3.11-slim` 而不是自建镜像？**
A: 依赖只有三个包（`psycopg2-binary`、`schedule`、`watchdog`），启动时 pip 安装即可。

**Q: `.ugreen.json` 和 NFO 文件是什么关系？**
A: 互不干扰。项目**不写入 NFO**，全部数据存到 `.ugreen.json`。Watchdog 监控 NFO 变化时，将 NFO 编辑的字段合并到 `.ugreen.json`，再写回数据库。

**Q: 每次运行都会读所有文件吗？**
A: 不会。首次运行建立基线后，后续通过缓存对比时间戳和内容哈希，无变化则跳过。

**Q: 播放记录回写时如何找到正确的文件？**
A: 三级匹配：1) 文件内容哈希（改名/移动后仍可匹配）；2) strm 文件自行计算哈希；3) 文件名前缀匹配。

**Q: 播放记录会丢历史吗？**
A: 不会。`.ugreen.json` 保存完整播放历史，DB 只保留最新一条。每次同步合并新旧记录并去重。

**Q: 电视剧的数据写在什么地方？**
A: 电视剧目录的 `.ugreen.json`，`video_type == 2`。包含 `ug_video_info` 全字段 + 剧集列表 + 播放记录 + 收藏 + 合集。

**Q: 移动目录后数据会丢吗？**
A: 不会。`.ugreen.json` 跟着目录走，程序从 `file_info` 获取最新 `category_id`，播放记录通过哈希匹配恢复。

**Q: 手动编辑 ug_video_info（如改名字）utime 不变怎么办？**
A: 程序对 9 个用户可编辑字段计算 MD5 哈希，哈希变化即触发 DB→JSON 同步。

**Q: `DRY_RUN` 模式做什么？**
A: 扫描文件、比对数据、输出日志，但**不执行任何数据库写入**。

## 致谢

- 感谢 [WorkBuddy](https://www.codebuddy.cn/work/) 提供免费算力额度
- 感谢 [wa3ytsm](https://club.ugnas.com/home.php?mod=space&uid=3326&do=thread&view=me&from=space) 对本项目的启发和指导
