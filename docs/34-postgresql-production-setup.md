# 34. 正式环境连接 PostgreSQL：配置与上线步骤

> 适用版本：V2.5（含 V2.3 起的 PostgreSQL 支持）。实测环境：PostgreSQL 18.6 @ `192.168.31.27:5444`，
> 镜像 `ctms:2.5.0` 容器连 PG 启动成功（`/api/health` → `db:true`，47 张表、V2.5 财务表与新增列自动就绪）。

## 1. 一句话结论

后端**只认一个环境变量** `CTMS_DB_URL`：把它指向 PostgreSQL 即完成切换，
建表/增量加列在同一进程启动时**幂等自动执行**，无需 Alembic、无需手工 DDL。

```
CTMS_DB_URL=postgresql+psycopg2://<用户>:<密码>@<PG主机>:<端口>/<库名>
```

## 2. 前置条件

| 项 | 要求 |
|---|---|
| PostgreSQL | ≥ 13（生产实测 16 / 18 均可），字符集 UTF8 |
| 网络 | 应用服务器 → PG 的 5432（本项目实测用 5444）放通；PG 的 `pg_hba.conf` 允许该网段 |
| 驱动 | 容器镜像**已内置** `psycopg2-binary`（V2.3 起）；裸机需 `pip install -r app/requirements-pg.txt` |

## 3. 第 1 步：在 PG 上建专用库与账号（不要用 postgres 超级用户）

```sql
-- 以超级用户执行
CREATE ROLE ctms WITH LOGIN PASSWORD '<改成强密码>';
CREATE DATABASE ctms OWNER ctms ENCODING 'UTF8';
\c ctms
GRANT ALL ON SCHEMA public TO ctms;      -- PG 15+ 默认 public 只读，必须显式授权
```

## 4. 第 2 步：配置连接串

写入项目根目录 `.env`（已被 `.gitignore` 排除；生产更推荐由 NSSM/systemd/compose 注入真实环境变量，
优先级：**真实环境变量 > .env > 代码默认值**）：

```bash
CTMS_DB_URL=postgresql+psycopg2://ctms:<密码>@192.168.31.27:5444/ctms
```

要点：
- 驱动名 `+psycopg2` **必须写**（写 `postgresql://` 会尝试 psycopg2 之外的默认驱动）；
- 密码里若含 `@ : / # %` 等字符需做 URL 编码（例如 `@` → `%40`）；
- 改完**必须重启后端**（配置在模块导入时读取）。

## 5. 第 3 步：迁移数据（可选）或直接建表

**A. 沿用现有 SQLite 数据**（推荐一次性搬迁）：

```bash
app/.venv/Scripts/python.exe -m app.tools.migrate_sqlite_to_pg \
  --sqlite app/data/ctms.db \
  --pg-url "postgresql+psycopg2://ctms:<密码>@192.168.31.27:5444/ctms"
```

脚本会：按 ORM 元数据建表 + 补增量列与索引 → 按外键顺序拷贝 → **重置自增序列** →
逐表比对行数（不一致即非 0 退出，避免"看起来成功"）。支持 `--dry-run` / `--verify-only` / `--truncate`。

**B. 全新库**：什么都不用做。启动后端时 `create_all` + `ensure_schema_upgrades` 会自动建齐
（V2.5 的 6 张财务表、`payment_orders` 9 个纸质模板字段、采购/销售 4 个回写列都在其中）。

## 6. 第 4 步：启动

### 方式一：容器 + 外部 PG（本项目生产推荐）

```bash
docker run -d --name ctms -p 8080:8000 \
  -e CTMS_DB_URL="postgresql+psycopg2://ctms:<密码>@192.168.31.27:5444/ctms" \
  -v ctms_data:/data \
  ctms:2.5.0
```

或使用仓库内编排文件 `deploy/docker-compose.external-pg.yml`（在 `deploy/.env` 里写 `CTMS_DB_URL`）：

```bash
cd deploy && docker compose -f docker-compose.external-pg.yml up -d
```

### 方式二：裸机（venv + NSSM / systemd）

```bash
set CTMS_DB_URL=postgresql+psycopg2://ctms:<密码>@192.168.31.27:5444/ctms
app\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

> 容器内 `CTMS_SERVE_STATIC=1` + `CTMS_WEB_DIST=/srv/web/dist` 已由镜像设好（前后端同容器）。

## 7. 第 5 步：上线后必做的三项校验

```bash
# 1) 连通性与库指向
curl http://127.0.0.1:8080/api/health          # 期望 {"status":"ok","db":true}
docker exec ctms python -c "from app.database import engine; print(engine.url)"

# 2) 同步内置角色权限（V2.5 新增 20 个 finance.* 权限点；sysadmin 会自动补齐，其它内置角色需同步）
app/.venv/Scripts/python.exe -m app.init_db --sync-roles

# 3) 财务数据一致性冒烟（默认只读；--fix 才修正）
CTMS_DB_URL="postgresql+psycopg2://ctms:<密码>@192.168.31.27:5444/ctms" \
  app/.venv/Scripts/python.exe app/tests/smoke_v25_finance.py
```

结构自检（可选）：

```sql
select count(*) from pg_tables where schemaname='public';                    -- 期望 47
select column_name from information_schema.columns
 where table_name='payment_orders';                                          -- 期望含 payee_bank / pay_reason / plan_type …
```

## 8. ⚠️ 必须补做：存量"来源行丢失"数据修复（只在本机 SQLite 做过）

现场缺陷 `IN202610000005`（入库单已过账但采购单 `received_qty=0`、仍可继续下推）的修复，
**此前只对本机 SQLite 执行过**；PG 库中该值仍是旧数据（实测 `PO202609000029` 在 PG 里
`received_qty` 仍为 0）。切到 PG 后请补跑一次（脚本幂等，先 dry-run）：

```bash
export CTMS_DB_URL="postgresql+psycopg2://ctms:<密码>@192.168.31.27:5444/ctms"
app/.venv/Scripts/python.exe app/tools/backfill_src_item_v25.py          # 只报告
app/.venv/Scripts/python.exe app/tools/backfill_src_item_v25.py --fix    # 执行
```

脚本只补 `src_item_id` 来源标记与 `received_qty`/`shipped_qty` 数量回写，
**不动数量、金额、单据状态与库存**；执行前建议先备份。

## 9. 备份与回滚

```bash
pg_dump -Fc -h 192.168.31.27 -p 5444 -U ctms ctms > ctms_$(date +%F).dump   # 备份
pg_restore -h 192.168.31.27 -p 5444 -U ctms -d ctms --clean ctms_2026-10-11.dump
```

- **回滚代码**：镜像回退到旧 tag 即可；数据库侧 V2.5 **只加表、只加列**（可空或带默认值），
  旧版本读取时忽略，**无需回退 DDL**。
- **回滚数据库**：用上面的 `pg_restore`；或在迁移前先 `pg_dump` 留底。

## 10. 常见问题

| 现象 | 原因与解决 |
|---|---|
| `ModuleNotFoundError: psycopg2` | 裸机未装 `app/requirements-pg.txt`；容器镜像已内置 |
| `password authentication failed` | 密码含特殊字符未 URL 编码；或 `pg_hba.conf` 未放行该来源 IP |
| `connection refused / timeout` | 防火墙未放通端口（本项目 5444）；PG `listen_addresses` 未包含该网卡 |
| `relation "xxx" does not exist` | 连到了别的库（用上文 `engine.url` 核对）；或没跑迁移 |
| 插入主键冲突 | 手工导入数据后序列未重置：`select setval(pg_get_serial_sequence('表','id'), max(id)) from 表;` |
| 启动报 `column ... is of type boolean but default expression is of type integer` | 旧镜像在 PG 上建表的历史问题，V2.3 起已修（用 `server_default=false()`），升级镜像即可 |
