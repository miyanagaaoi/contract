# CTMS V2.6.0 服务器升级说明书（由旧版 ctms-1.json 换算）

> 目标服务器：外部 PostgreSQL（192.168.81.50:5432/ctms）、宿主机端口 **9000**、
> 配置挂 `/docker/ctms/.env`、容器名 `ctms-1`。
> 本文给出 3 种等价升级方式：compose / docker run / 宝塔面板 UI。

---

## 0. 升级前备份（1 分钟，必做）

```bash
# PostgreSQL 逻辑备份（数据都在 PG，不在容器里）
docker exec -it <pg容器名或直接> pg_dump -h 192.168.81.50 -U ctms -d ctms -f /tmp/ctms_v252.sql
# 或：pg_dump -h 192.168.81.50 -p 5432 -U ctms -d ctms > ctms_v252_$(date +%F).sql

# 附件/上传目录（如果有内容）
mkdir -p /volume2/docker/ctms/data_backup && cp -r /volume2/docker/ctms/data/* /volume2/docker/ctms/data_backup/ 2>/dev/null || true

# 现容器配置留档
docker inspect ctms-1 > ctms-1.old.inspect.json
```

---

## 1. 导入新镜像

```bash
# 方案 A：只装业务核心包（71MB，推荐——同步走桥接/上传发票包）
gunzip -c ctms-image-2.6.0-core.tar.gz | docker load

# 方案 B：需要服务器自动同步（Chromium 固定，以后只更新核心包）
gunzip -c ctms-browser-1.tar.gz | docker load
gunzip -c ctms-image-2.6.0-core.tar.gz | docker load
docker build --network=none -t ctms:2.6.0-sync \
  --build-arg CORE=ctms:2.6.0 -f deploy/Dockerfile.sync-local .
```

## 2. 准备目录与 .env

```bash
mkdir -p /volume2/docker/ctms/data
# 在原有 /docker/ctms/.env 末尾追加 V2.6 发票同步凭据（按主体码）：
cat >> /docker/ctms/.env <<'EOF'
# ---- V2.6 发票同步（可用 base64:xxxx 混淆密码）----
CTMS_TAX_SYNC_YX_USERNAME=你的账号
CTMS_TAX_SYNC_YX_PASSWORD=你的密码
CTMS_TAX_SYNC_YX_TAX_NO=91149900MAECLDF33U
# CTMS_TAX_SYNC_ZC_USERNAME=
# CTMS_TAX_SYNC_ZC_PASSWORD=
# CTMS_TAX_SYNC_ZC_TAX_NO=
EOF
chmod 600 /docker/ctms/.env
```

## 3. 切换容器（三选一）

### 3.1 docker compose（推荐）

```bash
docker rm -f ctms-1
docker compose -f docker-compose.prod-server.yml up -d
docker logs -f ctms-1     # 看到启动完成且无迁移报错即可
```

### 3.2 docker run（等价命令）

```bash
docker rm -f ctms-1
docker run -d --name ctms-1 --restart unless-stopped \
  -p 9000:8000 \
  -e CTMS_DB_URL="postgresql+psycopg2://ctms:CHANGE_ME_DB_PASSWORD@192.168.81.50:5432/ctms" \
  -e CTMS_UPLOAD_DIR=/data/uploads \
  -e CTMS_LOG_DIR=/data/logs \
  -e CTMS_SERVE_STATIC=1 \
  -e CTMS_WEB_DIST=/srv/web/dist \
  -v /docker/ctms/.env:/app/.env \
  -v /volume2/docker/ctms/data:/data \
  ctms:2.6.0
# 需要自动同步则最后换成 ctms:2.6.0-sync
```

### 3.3 宝塔 / 面板 UI（按旧 ctms-1.json 逐项填）

| 项 | 旧值 | 新值 |
|---|---|---|
| 镜像 | `ctms:2.5.2` | **`ctms:2.6.0`**（或 `ctms:2.6.0-sync`） |
| 容器名 | `ctms-1` | `ctms-1`（保持不变） |
| 端口 | 9000 → 8000/tcp | 不变 |
| 网络 | bridge | 不变 |
| 重启策略 | 关闭 | 建议改为 **unless-stopped** |
| 环境变量 | 见下表 | 全部保留，另加 `CTMS_TAX_SYNC_*` |
| 挂载 | `/docker/ctms/.env` → `/app/.env` | 保留 |
| 挂载（**新增**） | — | **`/volume2/docker/ctms/data` → `/data`** |

环境变量（原样保留 5 项）：

```
CTMS_DB_URL=postgresql+psycopg2://ctms:CHANGE_ME_DB_PASSWORD@192.168.81.50:5432/ctms
CTMS_UPLOAD_DIR=/data/uploads
CTMS_LOG_DIR=/data/logs
CTMS_SERVE_STATIC=1
CTMS_WEB_DIST=/srv/web/dist
```

> 宝塔的旧容器配置里**没有挂 /data**，说明当时附件没有持久化（重启会丢）。
> V2.6 起发票包 PDF 存在 `/data/uploads/invoices`，**必须**把 `/volume2/docker/ctms/data` 挂到 `/data`。

## 4. 升级后自检

```bash
curl http://127.0.0.1:9000/api/health
# 期望: {"status":"ok","app":"CTMS","version":"2.6.0","db":true}

# 数据库自动迁移检查（启动日志里应有迁移动作，无报错）
docker logs ctms-1 2>&1 | grep -iE "error|exception|traceback" | head
```

浏览器打开 `http://<服务器IP>:9000`：
1. 发票管理 → 筛选「收票单位」能否筛出已同步票；
2. 筛选「原始文件 / 已下载 / 未上传」；
3. 勾选若干票 → **批量打印**（弹合并 PDF）；
4. 上传一个发票包（税务平台下载的 zip）→ 看“匹配挂附件 N 张”。

## 5. 回滚（若需）

```bash
docker rm -f ctms-1
docker run -d --name ctms-1 --restart unless-stopped -p 9000:8000 \
  -e CTMS_DB_URL="postgresql+psycopg2://ctms:CHANGE_ME_DB_PASSWORD@192.168.81.50:5432/ctms" \
  -e CTMS_UPLOAD_DIR=/data/uploads -e CTMS_LOG_DIR=/data/logs \
  -e CTMS_SERVE_STATIC=1 -e CTMS_WEB_DIST=/srv/web/dist \
  -v /docker/ctms/.env:/app/.env -v /volume2/docker/ctms/data:/data \
  ctms:2.5.2
# 数据库若已迁移（V2.6 只加列/加表，向后兼容 2.5.2 可正常读旧字段）；
# 如需完全还原数据：psql -h 192.168.81.50 -U ctms -d ctms < ctms_v252_2026xxxx.sql
```

## 6. 常见问题

**Q：升级后发票同步按钮点开提示"未配置"？**
在 `/docker/ctms/.env` 里补 `CTMS_TAX_SYNC_<主体码>_USERNAME/_PASSWORD/_TAX_NO` 后重启容器；
主体码必须已在「系统设置 → 我方公司」存在。

**Q：服务器是内网，能自动同步吗？**
能，但要 `ctms:2.6.0-sync` 镜像；且无头浏览器无法人工过点字验证码，
需先在办公机登录一次，把 `state_<主体码>.json` 复制进容器
`docker cp state_YX.json ctms-1:/app/app/data/tax_session/`，1 小时保活内发起同步。

**Q：数据库会重新建表吗？**
不会。启动时只做**增量**迁移（补列 + 建 `invoice_sync_logs` 表），幂等，可重复执行。
