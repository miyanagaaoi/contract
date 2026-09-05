# 08. 正式版部署手册（P3）

> 面向 3~4 人纯内网使用。原则：先把"能用"跑稳（SQLite 在此规模完全够用），
> 需要多机/大库时再切 PostgreSQL；两种部署路径任选其一。

## 1. 服务构成

| 组件 | 端口 | 说明 |
|---|---|---|
| 后端 CTMS API（uvicorn） | 8000 | FastAPI，无登录（内网信任边界） |
| 前端（Vite 构建产物 / 或 dev） | 5173(dev) / 80(prod nginx) | Vue3 SPA，`/api` 反代到后端 |
| 数据库 | — | 默认 SQLite（`app/data/ctms.db`）；可选 PostgreSQL |
| 附件 | — | `app/uploads/`（可 env 改目录） |

## 2. 环境变量（可选，均有默认）

见根目录 `.env.example`：`CTMS_DB_URL` / `CTMS_UPLOAD_DIR` / `CTMS_LOG_DIR`。
后端自动建表（启动时 create_all）+ 轻量增量列迁移（`app/db_migrate.py`），无需手工建表。

## 3. 方案 A：Linux + Docker Compose（推荐，若服务器可装 Docker）

```bash
# 1) 前端构建产物
cd web && npm install && npm run build        # 生成 web/dist
# 2) 起服务
cd deploy && docker compose up -d --build
# 3) 访问 http://<服务器IP>:8080
```

- 数据卷：`ctms_data`（uploads/logs）；升级 = `git pull` → `docker compose up -d --build`；
- 备份（每日，宿主机 crontab）：
  ```bash
  0 2 * * *  cd /opt/ctms && tar czf /var/ctms-backups/ctms_$(date +\%F).tar.gz app/data app/uploads
  ```
  恢复：解包后 `docker compose restart app`；
- 若启用 PostgreSQL（取消 compose 中 db 注释、安装 psycopg2、设置 `CTMS_DB_URL`）：
  备份用 `docker exec <db容器> pg_dump -U ctms ctms > pg_$(date +\%F).sql`，恢复 `psql -U ctms ctms < 文件`。

## 4. 方案 B：Windows 内网（无 Docker / 公司规定 Windows）

```bash
# 1) 后端服务化（NSSM，管理员 PowerShell）
nssm install CTMSApp "C:\Python313\python.exe" "D:\ctms\app\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000"
nssm set CTMSApp AppDirectory "D:\ctms"
nssm start CTMSApp
```
（说明：NSSM 参数指向 python.exe 时第二参数可写完整 `-m ...` 命令行；如遇引号问题改用
`nssm set CTMSApp Application C:\...\python.exe` + `AppParameters "-m uvicorn app.main:app --host 0.0.0.0 --port 8000"`。）

```bash
# 2) 前端：构建后由 Nginx for Windows（或 IIS 反代）托管
cd web && npm install && npm run build
# 将 web\dist 配为站点根目录；反代 /api → http://127.0.0.1:8000（参考 deploy/nginx.conf，容器内路径替换为实际盘符）
```

```bash
# 3) 每日备份计划任务（schtasks，管理 PowerShell）
schtasks /Create /TN CTMS-Backup /SC DAILY /ST 02:00 /TR "powershell -ExecutionPolicy Bypass -File D:\ctms\scripts\backup.ps1"
```
备份脚本：SQLite online-backup + uploads 压缩 + 30 天保留（已实测）。

## 5. PostgreSQL 切换步骤（可选，扩规模时用）

1. 安装 PostgreSQL 16，建库建用户：`CREATE USER ctms PASSWORD '...'; CREATE DATABASE ctms OWNER ctms;`
2. `app\.venv\Scripts\python -m pip install -r app\requirements-pg.txt`
3. 设置 `CTMS_DB_URL=postgresql+psycopg2://ctms:密码@主机:5432/ctms` 后重启服务（首次自动建表）；
4. 存量 SQLite 数据迁移：小数据量建议按 Excel 导出/导入重录；或写一次性脚本把
   contracts/tags/items/attachments/logs 逐表搬移（表单行结构一致，可直接 INSERT-SELECT）；
5. 备份切换为 pg_dump（见上）；附件仍按 uploads 目录备份。

> 说明：本部署规模（3~4 人、数百~千级合同）SQLite 足够且运维最简；PostgreSQL 属"如需"路径，
> 二者由环境变量切换、代码不变。

## 6. 健康检查与验收

- 后端：`GET /api/health` 应返回 `{"status":"ok","db":true,...}`
- 回归：`app\.venv\Scripts\python -m pytest app\tests -q`（BR 单测）+ 启动后
  `app\.venv\Scripts\python app\tests\smoke_p0.py`（AC-01~AC-11 接口冒烟）

## 7. 升级发布流程

1. `git pull`（或拷贝新包）；
2. 后端：重启服务（NSSM：`nssm restart CTMSApp`；Docker：`docker compose up -d --build`）；
   启动自动执行增量建表/迁移；
3. 前端：`cd web && npm run build` 后刷新静态目录；
4. 建议先跑 6. 的回归，再让用户使用；本次改动记录见 `docs/` 各迭代文档。

## 8. 恢复演练

- SQLite：停服 → 用 `app\backups\ctms_*.db` 覆盖 `app\data\ctms.db` → 起服 → 检查 `/api/health` 与台账数量；
- 附件：解压 `uploads_*.zip` 到 uploads 目录；
- 建议每季度演练一次并记录（对应验收报告 DoD 的运维项）。
