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

项目在每部视频目录下自动维护一个隐藏文件 `.ugreen.json`（绿联 NAS 默认不显示 `.` 开头的文件），全量备份标题、年份、简介、评分、播放记录、收藏、合集、剧集列表等数据。当数据库被刮削重置后，从这些备份文件中恢复全部数据。

**项目从不写入、不修改、不创建任何 NFO 文件。** NFO 文件完全由绿联系统或用户自己管理。

### 核心功能

| 功能 | 说明 |
|------|------|
| 定时周期同步 | 每隔指定时间（默认 1 小时）检查数据库是否有变化，自动备份或恢复 |
| Watchdog 实时监控 | 检测到 NFO 文件被手动编辑后，立即将新内容写回数据库，无需等待周期同步 |
| 数据闭环 | 用户编辑 NFO 的时间会被记录下来，下次周期同步时写入 `.ugreen.json`，以后每次都以此时间为准 |
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

**Watchdog 会自动检测到变化，把新标题写回数据库。** 你不需要手动触发同步。

### 场景 3：你把视频文件夹移到了新硬盘

从 `/volume1/media/电影/肖申克的救赎` 移到 `/volume2/media/电影/肖申克的救赎`。

绿联重新扫描后，播放记录、收藏、合集全部自动恢复。**零手动操作。**

### 场景 4：你重命名了视频文件

`Inception_4K.mkv` → `盗梦空间 4K.mkv`

播放记录不会丢失。项目基于文件内容哈希匹配文件，改名不影响匹配。

### 数据保护范围

| 你的操作 | 保护方式 |
|---------|---------|
| 在影视中心编辑标题/简介/评分 | 下次同步备份到 `.ugreen.json`，刮削后恢复 |
| 观看视频（播放进度） | 备份到 `.ugreen.json`，基于文件内容哈希匹配，防错位 |
| 标记收藏 | 备份到 `.ugreen.json` |
| 编辑合集 | 完整 19 个字段全部备份 |
| 手动编辑 `movie.nfo` | Watchdog 检测到变化 → 立即写回数据库 |
| 移动文件夹到新路径 | `.ugreen.json` 跟着走，自动解析新路径 |
| 重命名文件 | 内容哈希不变，播放记录不丢失 |
| 删除 `.ugreen.json` | 下次周期同步时从数据库自动重建 |

---

## 三、开发与部署

### 前置条件

- 绿联 NAS（或任何运行绿联影视中心的设备）
- Docker（推荐）或 Python 3.11+
- PostgreSQL 数据库（绿联影视中心使用，默认端口 5433）

### 配置项

通过环境变量配置：

| 环境变量 | 必填 | 默认值 | 说明 |
|---------|:---:|--------|------|
| `DB_HOST` | ✅ | - | PostgreSQL 主机地址 |
| `DB_PORT` | | `5433` | 数据库端口 |
| `DB_NAME` | | `video` | 数据库名 |
| `DB_USER` | | `postgres` | 数据库用户 |
| `DB_PASSWORD` | | `""` | 数据库密码 |
| `MEDIA_LIB_PATHS` | | - | Watchdog 监控的媒体目录（多个用 `:` 分隔） |
| `WATCHDOG_ENABLED` | | `true` | 启用 NFO 文件实时监控 |
| `WATCHDOG_DEBOUNCE` | | `3.0` | 文件防抖秒数 |
| `SCAN_INTERVAL` | | `3600` | 周期同步间隔（秒），`0` 表示仅运行一次后进入纯 Watchdog 模式 |
| `DRY_RUN` | | `false` | 试运行，不实际写入 |
| `TARGET_PATH` | | 空 | 限定同步路径范围，仅处理该路径前缀下的视频。用于小范围测试 |
| `LOG_LEVEL` | | `INFO` | 日志级别：`DEBUG` / `INFO` / `WARNING` / `ERROR` |

### Docker 部署

**快速启动：**

```bash
docker run -d \
  --name ug-videokeeper \
  --restart unless-stopped \
  -e DB_HOST=127.0.0.1 \
  -v /你的绿联媒体目录:/你的绿联媒体目录 \
  -v ./app:/app \
  python:3.11-slim \
  sh -c "pip install psycopg2-binary schedule watchdog && python /app/main.py"
```

**Docker Compose：**

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
      # 可选：小范围测试
      # - TARGET_PATH=/volume1/media/movie
      # - DRY_RUN=true
    volumes:
      - /你的绿联媒体目录:/你的绿联媒体目录
      - ./app:/app
    working_dir: /app
    command: sh -c "pip install -r requirements.txt && python main.py"
```

```bash
docker-compose up -d
docker-compose logs -f ug-videokeeper
```

### 首次运行建议

1. 先用 `DRY_RUN=true` 跑一次，查看日志确认程序能正常连接数据库、识别视频文件
2. 确认无误后关闭 `DRY_RUN`，正式运行
3. 首次同步会完成两件事：为每部视频创建 `.ugreen.json` 备份文件；建立本地缓存避免重复工作
4. 之后每次周期同步只检查有变化的记录，效率很高

### 调试

```bash
# 查看实时日志
docker logs -f ug-videokeeper

# 试运行（不写入数据库）
docker run --rm -e DB_HOST=... -e DRY_RUN=true ...

# 单次同步后退出
docker run --rm -e DB_HOST=... -e SCAN_INTERVAL=0 ...

# 仅处理指定路径下的视频
docker run --rm -e DB_HOST=... -e TARGET_PATH=/volume1/media/movie ...
```

### 目录结构

```
ug-videokeeper/
├── main.py                    # 入口：启动调度器
├── config.py                  # 配置解析
├── models.py                  # 数据模型
├── utils.py                   # 工具函数
├── scheduler.py               # 定时调度 + Watchdog 管理
├── state.py                   # 状态缓存
├── watcher.py                 # Watchdog 实时监控
├── db/
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
A: 依赖只有三个包（`psycopg2-binary`、`schedule`、`watchdog`），启动时 pip 安装即可，无需维护镜像。

**Q: `.ugreen.json` 和 NFO 文件是什么关系？**
A: 互不干扰。项目**不写入 NFO**，所有扩展数据存到 `.ugreen.json`（隐藏文件）。NFO 仅用于 Watchdog 监控——你手动编辑 NFO 时，Watchdog 读取新值写回数据库。

**Q: 每次运行都会读所有文件吗？**
A: 不会。首次运行建立基线后，后续只对比时间戳，无变化则直接跳过。

**Q: 播放记录回写时如何找到正确的文件？**
A: 三级匹配：1) 文件内容哈希（改名/移动目录后仍可匹配）；2) strm 文件自行计算内容哈希；3) 文件名前缀匹配。匹配失败的记录跳过并告警。

**Q: 电视剧的数据写在什么地方？**
A: 电视剧根目录的 `.ugreen.json`。包含剧集列表、播放记录、收藏、合集。恢复时按哈希匹配逐条定位到具体文件。

**Q: 移动目录后数据会丢吗？**
A: 不会。`.ugreen.json` 跟视频目录一起移动，项目通过目录路径自动解析新 `category_id`，播放记录通过内容哈希匹配，移动不影响。

**Q: `DRY_RUN` 模式做什么？**
A: 扫描文件、比对数据、输出日志，但**不执行任何数据库写入**。用于验证配置和预览操作。
