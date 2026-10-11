# 10. 单容器 Docker 打包与导入启动

> 把 CTMS（前端+后端）打成**一个镜像文件**：任意有 Docker 的机器构建 → `docker save` 成单个 tar
> → 拷到服务器 → `docker load` → 一条命令启动。数据（SQLite+附件+日志）持久化在 `/data` 卷，
> 删容器/升级不丢数据。

## 0. 不需要本地 Docker 的办法：GitHub Actions 出包

仓库已带 `.github/workflows/docker-image.yml`：在 GitHub 网页 → **Actions** → 选择
"Build CTMS single-container image" → **Run workflow**；跑完后在本次运行页底部
**Artifacts** 下载 `ctms-image-1.0.0.tar.gz` → 解压得 `ctms-image-1.0.0.tar` → 服务器
`docker load -i` 即可。本机无需安装 Docker。

## 1. 生成镜像文件（在有 Docker 的机器上构建）

```bash
cd 项目根目录
scripts\export-docker.bat          # Windows
bash scripts/export-docker.sh      # Linux/macOS/服务器
```

- 产物：`ctms-image-1.0.0.tar`（约几百 MB，取决于基础镜像）；
- 构建自动完成前端 `npm run build` 并把 `dist` 打进镜像，无需手工传前端；
- 国内网络慢可加代理参数：`--build-arg NPM_REGISTRY=https://registry.npmmirror.com`。

## 2. 导入到目标服务器（宝塔 Docker 或命令行）

```bash
# 上传 tar 到服务器后：
docker load -i ctms-image-1.0.0.tar        # 导入镜像
docker images | grep ctms                   # 应看到 ctms  1.0.0
```

宝塔路径：宝塔软件商店装 **Docker 管理器** → 镜像 → 导入 → 选择该 tar 即可。

## 3. 启动（任选其一）

### 3.1 docker run（最简）

```bash
docker run -d --name ctms -p 8080:8000 -v ctms_data:/data ctms:1.0.0
```

访问 `http://<服务器IP>:8080`（记得在宝塔安全/云安全组放行 8080）。

### 3.2 docker compose（推荐，含卷声明）

```yaml
# deploy/docker-compose.single.yml 已备好
services:
  ctms:
    image: ctms:1.0.0
    container_name: ctms
    restart: unless-stopped
    ports:
      - "8080:8000"
    volumes:
      - ctms_data:/data
volumes:
  ctms_data:
```

```bash
docker compose -f deploy/docker-compose.single.yml up -d
docker compose -f deploy/docker-compose.single.yml logs -f ctms   # 看日志
```

## 4. 启动后验证

- 页面：浏览器开首页看板；F12 无 API 报错；
- 健康：`curl http://127.0.0.1:8080/api/health` → `{"status":"ok","version":"1.0.0-rc1","db":true}`；
- 数据库：容器 `/data/ctms.db`、附件 `/data/uploads/`、日志 `/data/logs/`（已映射到命名卷 `ctms_data`）。

## 5. 数据备份 / 恢复（服务器上）

```bash
# 备份：拷贝卷内容
docker run --rm -v ctms_data:/data -v $PWD:/backup alpine sh -c \
  "cd /data && tar czf /backup/ctms-data.tar.gz ."

# 恢复
docker stop ctms
docker run --rm -v ctms_data:/data -v $PWD:/backup alpine sh -c \
  "rm -rf /data/* && tar xzf /backup/ctms-data.tar.gz -C /data"
docker start ctms
```

建议放入宝塔计划任务每日执行（等价于上一份文档 9 节的备份策略）。

## 6. 升级版本

```bash
# 任意有 Docker 的机器重新构建并导出新 tar
docker build -t ctms:1.0.0 -f deploy/Dockerfile.single .
docker save -o ctms-image-1.0.0.tar ctms:1.0.0

# 服务器上
docker load -i ctms-image-1.0.0.tar
docker compose -f deploy/docker-compose.single.yml up -d --force-recreate
# 或：docker stop ctms && docker rm ctms && docker run -d --name ctms -p 8080:8000 -v ctms_data:/data ctms:1.0.0
```

> 后端每次启动自动 `create_all` + 增量迁移，无需手工改表；`/data` 卷保留，数据不丢。

## 7. 常见问题

| 现象 | 处理 |
|---|---|
| `docker build` 拉取基础镜像慢/失败 | 给 Docker 配镜像加速（国内加速源）或用 `--build-arg NPM_REGISTRY=...` |
| 访问页面 502/连接失败 | 端口冲突换端口（`-p 8090:8000`）、宝塔安全+云安全组放行 |
| 上传超 20M | 附件上限在后端；如需调大改 `app/config.py MAX_UPLOAD_MB` 重新构建 |
| 重启后数据还在吗 | 只要使用 `ctms_data:/data` 卷，数据就在；**别用**不带 `-v` 的裸运行（除非允许丢弃） |
| 想换 PostgreSQL | **V2.3 起镜像已内置 `psycopg2`**，无需重打；`environment: CTMS_DB_URL: postgresql+psycopg2://...` 即可（见 §9） |

## 8. V2.3：连 PostgreSQL 与数据迁移

镜像自 V2.3 起一并安装 `app/requirements-pg.txt`（`psycopg2-binary`），单容器可直接连 PG；
`app/tools` 也已打进镜像，可在容器内执行迁移。

```bash
# 9.1 连既有 PostgreSQL 启动（开发库示例：192.168.31.27:5444/ctms）
docker run -d --name ctms -p 8080:8000 -v ctms_data:/data \
  -e CTMS_DB_URL="postgresql+psycopg2://postgres:密码@192.168.31.27:5444/ctms" ctms:2.3.0

# 或使用编排（连接串可由 deploy/.env 注入，避免密码进命令行历史）
cd deploy && docker compose -f docker-compose.external-pg.yml up -d

# 9.2 迁移既有 SQLite 数据（把 ctms.db 放进 /data 后，在容器内跑一次）
docker cp app/data/ctms.db ctms:/data/ctms.db
docker exec ctms python -m app.tools.migrate_sqlite_to_pg \
  --sqlite /data/ctms.db \
  --pg-url "postgresql+psycopg2://postgres:密码@192.168.31.27:5444/ctms"

# 9.3 V2.3 存量字段回填（仓库所属公司 / 单据签约公司 / 调拨单位；只填空值、幂等）
docker exec -e CTMS_DB_URL="postgresql+psycopg2://postgres:密码@192.168.31.27:5444/ctms" \
  ctms python -m app.tools.backfill_subject_v23 --dry-run
docker exec -e CTMS_DB_URL="postgresql+psycopg2://postgres:密码@192.168.31.27:5444/ctms" \
  ctms python -m app.tools.backfill_subject_v23
```

> 若希望数据库与应用同栈部署（推荐给新环境）：`deploy/docker-compose.yml` 已内置
> `postgres:16` 服务 + 健康检查 + `pgdata` 卷，`cd deploy && docker compose up -d --build` 即可。
> 迁移脚本会先建表、逐表拷贝、重置自增序列，并**逐表校验行数**（不一致直接失败退出）。
> 回退：把 `CTMS_DB_URL` 去掉即回到 `/data/ctms.db`（SQLite 文件始终保留）。

## 9. 与本项目其他交付物的关系

- 本方式替代 `docs/08` 的“Nginx+Supervisor”两手装：单容器开箱即用，适合 3~4 人规模；
- 需要域名/HTTPS/白名单等网关层时，仍建议外层加 Nginx（宝塔反代或 `docs/09` 建站方式把 8080 反代出去）。
