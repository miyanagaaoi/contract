# 15. 备份与恢复演练记录（T-V2-40）

> 对应验收：`docs/11-erp-requirements.md` **AC-V2-39 手动备份下载**；
> 对应实现：`app/services/backup_service.py`、`POST/GET /api/system/backup`、系统管理 → 备份页签。

## 1. 演练目的

证明"备份可用、可还原"，而不是只证明"按钮能点"：

1. 备份产物内容完整（数据库一致性快照 + 附件目录）；
2. 备份库可独立打开且通过 SQLite 完整性校验；
3. 备份库中的业务数据与生产库一致（关键表行数逐表比对）；
4. 恢复路径明确、可由运维按步骤执行。

演练脚本：`app/tests/drill_backup_restore.py`（全自动，可重复执行）。

## 2. 演练记录（实测）

| 步骤 | 结果 |
|---|---|
| 1. 生成备份 | `ctms_backup_20260925_221211.zip`，**1,243,500 字节**；包含 `ctms.db` + `uploads/`（18 个附件） |
| 2. 下载备份 | 1,243,500 字节，zip 魔数 `PK` 校验通过 |
| 3. 解压 | 20 个条目（数据库 1 + 附件 18 + `backup_info.txt` 1） |
| 4. 完整性校验 | 备份库 `PRAGMA integrity_check` = **ok** |
| 5. 行数一致性 | 12 张关键表**逐表一致**（见下） |
| 6. 恢复后数据可读性 | 合同 / 入库单（`approved`,`posted=1`）/ 结存 记录均可正常读出 |
| 7. 清理 | 演练产生的备份已删除 |

关键表行数（备份 vs 生产）：`contracts 68/68`、`users 8/8`、`roles 14/14`、`customers 6/6`、
`suppliers 6/6`、`products 8/8`、`warehouses 7/7`、`purchase_orders 2/2`、`stock_in_orders 7/7`、
`stocks 6/6`、`stock_ledger 10/10`、`change_logs 105/105` —— **全部一致**。

> 复现命令（先启动后端）：
> ```powershell
> $env:CTMS_SMOKE_BASE='http://127.0.0.1:8010/api'
> app\.venv\Scripts\python.exe app\tests\drill_backup_restore.py
> ```

## 3. 备份机制（实现说明）

- **数据库快照**：使用 Python `sqlite3` 的在线 backup API（`src.backup(dst)`），而不是复制文件——
  避免在写入事务进行中复制出损坏的库；WAL 模式下同样安全。
- **附件**：`app/uploads/` 整目录打包进 zip，保持相对路径（`uploads/<contract_id>/<uuid>.<ext>`）。
- **产物位置**：`app/data/backups/ctms_backup_YYYYmmdd_HHMMSS.zip`。
- **下载安全**：文件名白名单正则 `^ctms_backup_\d{8}_\d{6}\.zip$` + 解析后路径必须位于备份目录内
  （防路径穿越），下载需 `system.backup.download` 权限。
- **留痕**：生成/删除备份都会写操作日志（`module=system`，`action=backup`）。

## 4. 恢复步骤（Windows 原生部署）

```powershell
# 0) 备份当前库（回滚用）——即使已有备份，恢复前也要再留一份
Copy-Item app\data\ctms.db "app\data\ctms.db.before-restore" -Force
Copy-Item app\uploads "app\uploads.before-restore" -Recurse -Force

# 1) 停服（关闭 uvicorn / NSSM 服务 / 计划任务）
#    - 若是 NSSM：nssm stop CTMS
#    - 若是前台进程：Ctrl+C，或 Stop-Process -Name python（确认无其他 python 业务进程）

# 2) 解压备份
Expand-Archive -Path app\data\backups\ctms_backup_20260925_221211.zip -DestinationPath $env:TEMP\ctms_restore -Force

# 3) 覆盖数据库与附件（注意先删除 WAL/SHM 残留，避免与新库不匹配）
Remove-Item app\data\ctms.db-wal, app\data\ctms.db-shm -ErrorAction SilentlyContinue
Copy-Item $env:TEMP\ctms_restore\ctms.db app\data\ctms.db -Force
if (Test-Path $env:TEMP\ctms_restore\uploads) {
  Remove-Item app\uploads -Recurse -Force -ErrorAction SilentlyContinue
  Copy-Item $env:TEMP\ctms_restore\uploads app\uploads -Recurse -Force
}

# 4) 启动并自检
app\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
#    - 健康检查：GET /api/health → {"status":"ok","db":true}
#    - 登录 admin 后执行冒烟：smoke_m1.py / smoke_m2.py / smoke_p0.py
```

Docker 单容器部署：把 zip 中的 `ctms.db` 与 `uploads/` 覆盖到容器挂载的 `/data` 与 `/data/uploads`，
再 `docker restart ctms`；随后同样跑冒烟脚本。

## 5. 结论与运维建议

| 项 | 建议 |
|---|---|
| 自动备份频率 | 每日 1 次（Windows 计划任务/Docker cron 调用 `POST /api/system/backup` 或直接跑 Python 一行脚本） |
| 保留策略 | 本地保留最近 14 份 + 每周一份异地副本；单份体积约 1~1.2MB（含附件） |
| 演练周期 | 每季度执行一次本脚本（自动）+ 每半年做一次**真实恢复**（按 §4 覆盖到测试实例） |
| 恢复后注意 | ① 所有登录令牌失效需重新登录；② 备份时间点之后的数据会丢失，需业务确认；③ 若备份来自旧版本，启动时 `ensure_schema_upgrades()` 会自动补列/重建表 |
| 风险 | 附件与数据库必须**同批**恢复（zip 内含两者）；单独恢复其一会出现"附件记录指向丢失文件" |

## 6. 变更记录

| 日期 | 内容 |
|---|---|
| 2026 | 首次演练（本文件 §2），全部检查通过；脚本纳入仓库 `app/tests/drill_backup_restore.py` |
