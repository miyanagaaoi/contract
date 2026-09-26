# 19. V2.0 上线清单与升级步骤（Go-Live Checklist）

> 适用：把环境从 **V1.0（合同台账）升级到 V2.0（ERP 进销存）**，或全新部署 V2.0。
> 依据：`12-erp-system-design.md` §10（迁移步骤）、`08-deployment.md`（Windows/Linux 部署）、`10-docker-single.md`（单容器）。

## 1. 里程碑与发布物

| 里程碑 | 内容 | 验收报告 | Git tag |
|---|---|---|---|
| M1 | 权限与主数据地基（账号/角色/权限/数据范围、资料库） | `13-m1-acceptance.md` | `v2.0-m1` |
| M2 | 采购线与库存过账（单据、下推、过账、盘点、附件） | `14-m2-acceptance.md` | `v2.0-m2` |
| M3 | 销售与盘点、导出、打印 | `18-m3-acceptance.md` | `v2.0-m3` |
| 正式发布 | 全量回归 + UAT 通过 | `17-uat-plan.md`（执行后归档） | `v2.0` |

发布物二选一：① 单容器 Docker 镜像 tar（`10-docker-single.md`）；② Windows 原生（NSSM 服务 + 前端静态产物，`08-deployment.md`）。

## 2. 上线前检查（必须全部为 ✅）

- [ ] `pytest app/tests -q` 全绿（当前基线 **244 passed**）
- [ ] 端到端冒烟全绿：`smoke_m1.py` 15/15、`smoke_m2.py` 11/11、`smoke_m3.py` 11/11、`smoke_p0.py` 13/13
- [ ] `npm run build` 通过，且部署目录存在最新 `web/dist`
- [ ] 权限矩阵复核无异常：`app\tools\audit_role_matrix.py`（记录见 `16-permission-matrix.md`）
- [ ] 备份恢复演练通过：`app\tests\drill_backup_restore.py`（记录见 `15-backup-drill.md`）
- [ ] **上线前备份**：`app/data/ctms.db` + `app/uploads/`（或调用 `POST /api/system/backup` 生成 zip 并另存到备份盘）
- [ ] 环境变量确认：`CTMS_JWT_SECRET`（生产必须显式设置）、`CTMS_AUTH_ENABLED=1`、
      `CTMS_DB_URL`/`CTMS_UPLOAD_DIR`（如自定义路径）
- [ ] 上线窗口与通知：3~4 名用户已知会停机时间（升级过程约 10 分钟）

## 3. 升级步骤（V1.0 → V2.0）

```powershell
# 1) 停服
#    - NSSM：nssm stop CTMS
#    - 前台/其他：停止 uvicorn 进程（确认无写入）
Stop-Process -Name python -ErrorAction SilentlyContinue

# 2) 备份（关键！）
Copy-Item app\data\ctms.db "D:\backup\ctms_before_v2_$(Get-Date -Format yyyyMMdd_HHmmss).db"
Copy-Item app\uploads "D:\backup\uploads_before_v2" -Recurse -Force

# 3) 取得新版本代码（或解压发布包/加载镜像）
git fetch --all; git checkout v2.0    # 或解压发布 tar

# 4) 后端依赖（V2.0 无新增第三方依赖，仍建议确认）
app\.venv\Scripts\python.exe -m pip install -r app\requirements.txt

# 5) 数据库迁移（幂等：建新表 + 补列 + 重建 change_logs/attachments + 种子角色/权限/超管/系统参数）
app\.venv\Scripts\python.exe -m app.init_db

# 6) 前端构建（若使用后端托管静态产物）
cd web; npm install; npm run build; cd ..

# 7) 启动
$env:CTMS_SERVE_STATIC=1; $env:CTMS_WEB_DIST="D:\dsh\hetong\web\dist"
$env:CTMS_JWT_SECRET="<32 位以上随机串>"
app\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### 3.1 迁移做了什么（可核对）

| 动作 | 说明 |
|---|---|
| 建新表 | `org_units`、`users`、`roles`、`role_permissions`、`user_roles`、`operation_logs`、`customers`、`suppliers`、`product_types`、`uoms`、`warehouses`、`products`、`party_drafts`、`stocks`、`stock_ledger`、7 类单据主表与行项表 |
| 补列（ALTER TABLE ADD COLUMN） | `contracts.customer_id/supplier_id/org_id/created_by`、`change_logs.operator_id/operator_name/object_type/object_id`、`attachments.object_type/object_id`、`contract_tag.auto` |
| **重建表**（SQLite 无法改列约束） | `change_logs.contract_id`、`attachments.contract_id` 由 NOT NULL 改为可空；**历史数据完整保留**，迁移前自动 `DROP INDEX` 避免索引名冲突 |
| 回填 | 历史 `change_logs` 补 `object_type='contract'`、`object_id=contract_id` |
| 种子（幂等） | 8 个内置角色 + 权限点、初始超管 `admin`（首登强制改密）、系统参数默认值 |

> 迁移只做"新增/放开"，不删除任何业务数据；重复执行安全。

## 4. 上线后验证（10 分钟）

```powershell
$env:CTMS_SMOKE_BASE='http://127.0.0.1:8000/api'
app\.venv\Scripts\python.exe app\tests\smoke_m1.py     # 权限与主数据 15/15
app\.venv\Scripts\python.exe app\tests\smoke_m2.py     # 采购与过账 11/11
app\.venv\Scripts\python.exe app\tests\smoke_m3.py     # 销售与盘点 11/11
app\.venv\Scripts\python.exe app\tests\smoke_p0.py     # 合同模块无回归 13/13
app\.venv\Scripts\python.exe app\tests\drill_backup_restore.py   # 备份可生成可还原
```

- [ ] 用 `admin` 登录 → 强制改密 → 首页看板正常
- [ ] 建 1 个组织、1 个角色、1 个账号；用新账号登录确认菜单裁剪正确
- [ ] 历史合同：列表/详情/导出正常，变更历史中 V1.0 记录操作人显示"—"
- [ ] 执行 `POST /api/contracts/migrate-parties` 生成历史甲乙方草案 → 在"历史档案认领"页认领一条
- [ ] 系统管理 → 备份页签：生成备份并下载 zip
- [ ] 关闭 `CTMS_AUTH_ENABLED`（设为 0）重启可作为应急回退（仅本地调试用，生产不建议常开）

## 5. 回滚方案

| 场景 | 处置 |
|---|---|
| 迁移失败（启动即报错） | 停服 → 用第 2 步的 `ctms.db` + `uploads/` 覆盖 → 回退代码到 `v1.0` 或上一个 tag → 启动 |
| 运行期严重缺陷 | 保留现场（库与日志）→ 回退代码版本（DB 结构向后兼容，无需回退库）→ 缺陷登记后修复 |
| 仅前端问题 | 用上一版 `web/dist` 覆盖即可，无需动库 |

> 注意：V2.0 迁移是**结构新增**，V1.0 代码无法识别新表但可继续运行；若发生**数据**层面的不可逆变更（例如已确认认领的档案绑定），回滚库会丢失该部分数据 —— 因此第 2 步备份必须先做。

## 6. 上线后运维

| 项 | 做法 |
|---|---|
| 每日备份 | 计划任务/容器 cron 调用 `POST /api/system/backup`（需令牌）或直接跑 Python 一行；产物在 `app/data/backups/` |
| 备份保留 | 本地 14 份 + 每周一份异地；单份约 1~1.2MB（含附件） |
| 健康检查 | `GET /api/health` → `{"status":"ok","db":true}` |
| 对账巡检 | 每月执行 `POST /api/stock/recalc`，确认"结存 = 流水累计" |
| 演练 | 每季度跑 `drill_backup_restore.py`；每半年做一次真实恢复（见 `15-backup-drill.md` §4） |
| 日志 | 操作日志页（`system.log.view`）可查登录、审核、反审核、导出、备份等动作 |

## 7. 已知限制（上线时向用户说明）

1. 销售/出库/盘点页面与打印入口以后端接口为准确认（浏览器点击清单见 `17-uat-plan.md` §4）；
2. 单据打印为固定 A4 模板（表头/行项/合计/签字栏），不支持自定义模板；
3. 库存只记数量、不记成本；不含财务模块（应收应付、收付款、开票）——见 `11` §14；
4. 多单位换算、批次/保质期不在本期范围。

---

## 8. V2.1 升级步骤（V2.0 → V2.1）

> 适用：把环境从 **V2.0 升级到 V2.1（增量升级）**。
> 依据：`22-v2.1-requirements.md`、`23-v2.1-system-design.md`、`21-v2.1-upgrade-doc-plan.md`。
> ⚠️ V2.1 存在**两条互斥路径**，执行前必须先判定库内数据性质。

### 8.1 路径判定（第一步，不可跳过）

| 库内数据性质 | 走哪条路径 | 后果 |
|---|---|---|
| **仅有演示/验收数据** | **路径 A：清库重建**（§8.3） | 旧数据全部丢弃；演示合同重建为"含绑定物料行项"的新数据 |
| **含真实业务数据** | **路径 B：仅增量迁移**（§8.2） | 数据保留；但**旧合同的合同行项为空且未绑定物料**，"提取合同明细"对旧合同不可用（Q1 已接受的取舍） |

> 🚫 **强制门禁**：走路径 A 前，必须取得业务方对"库内数据可弃"的**书面确认**。这是**不可逆操作**，且不属于"迁移失败可回滚"的范畴（回滚代码无法恢复被清空的业务数据）。

### 8.2 增量迁移（路径 A 与 B 共同的前半段）

```powershell
# 1) 停服
Stop-Process -Name python -ErrorAction SilentlyContinue

# 2) 备份（关键）
Copy-Item app\data\ctms.db "D:\backup\ctms_before_v21_$(Get-Date -Format yyyyMMdd_HHmmss).db"
Copy-Item app\uploads "D:\backup\uploads_before_v21" -Recurse -Force

# 3) 取新版本代码
git fetch --all; git checkout v2.1

# 4) 数据库迁移（幂等：加列 + 建表 + 种子权限/编号规则）
app\.venv\Scripts\python.exe -m app.init_db

# 4.1) ⚠️ 必做：把内置角色权限同步为 V2.1 预设
#      为什么必须单独执行：`init_db` 只会**新增**缺失的权限点，**不会**更新既有角色的
#      权限分配。而 V2.1 新增了 7 个 `stock.transfer.*` 权限点——不同步的话，
#      **既有角色（含仓管员）登录后看不到"调拨单"菜单**（会被前端路由守卫拦下）。
app\.venv\Scripts\python.exe -m app.init_db --sync-roles

# 5) 前端构建
cd web; npm install; npm run build; cd ..
```

> ⚠️ **`--sync-roles` 的副作用**：它会把内置角色权限**重置为代码预设**，因此
> **会覆盖运维手工调整过的内置角色权限**。若生产上曾手工改过内置角色，请先导出
> 当前权限分配（系统管理 → 角色）再做同步。

**迁移动作（可核对）**：

| 动作 | 说明 |
|---|---|
| 补列 | `contract_items.product_id/product_code/product_name`；7 类既有单据表各加 `handler_name` |
| 建表 | `stock_transfers`、`stock_transfer_items` |
| 索引 | `stock_ledger(product_id, warehouse_id, biz_type)`（支撑"货品总额度"聚合） |
| 种子（幂等） | 新增 `stock_transfer` 编号规则；新增 7 个 `stock.transfer.*` 权限点并授权给相关角色 |
| 数据 | **不删除、不修改任何既有业务数据** |

### 8.3 路径 A：演示数据重建（仅当数据可弃）

```powershell
# 6A) 移走旧库（保留 .bak 以便后悔）
Move-Item app\data\ctms.db app\data\ctms.db.bak

# 7A) 建表 + 种子
app\.venv\Scripts\python.exe -m app.init_db

# 8A) 演示数据（账号/组织/主数据/演示合同——合同已含绑定物料的行项）
app\.venv\Scripts\python.exe app\tools\seed_demo_v2.py --no-force-change
```

> ⚠️ **不要执行 `python -m app.init_db --demo`**：该路径生成的 V1.0 风格演示合同**没有行项**，在 V2.1 下无法"提取合同明细"，属僵尸数据（`23` §9.3 设计决策）。

### 8.4 上线后验证

```powershell
$env:CTMS_SMOKE_BASE='http://127.0.0.1:8000/api'
app\.venv\Scripts\python.exe -m pytest app/tests -q     # 全绿（基线 + V2.1 新增用例）
app\.venv\Scripts\python.exe app\tests\smoke_m1.py      # 权限与主数据
app\.venv\Scripts\python.exe app\tests\smoke_m2.py      # 采购与过账
app\.venv\Scripts\python.exe app\tests\smoke_m3.py      # 销售与盘点
app\.venv\Scripts\python.exe app\tests\smoke_p0.py      # 合同模块无回归
app\.venv\Scripts\python.exe app\tools\audit_role_matrix.py   # 权限矩阵重算（见 16）
app\.venv\Scripts\python.exe app\tests\drill_backup_restore.py
```

- [ ] **行项合计金额显示为数值**（不是 `[object Object]`）——V2.1 修复的 N3 缺陷，须人工目视确认
- [ ] 采购申请单：经办人为账号下拉且默认当前账号；关联合同后可一键提取明细、可拉出合同详情抽屉
- [ ] 采购申请单：全部下推完毕后下推按钮消失、状态为"已完成"
- [ ] 库存明细：可见"货品总额度"；可按数量区间与物料类型筛选
- [ ] 调拨单：新建 → 审核 → 两仓结存同事务变化且产生两条流水；反审核后结存回滚
- [ ] 物料档案：商品类型树状展开；商品类型/计量单位可现场快建并回填
- [ ] **管理员自审**：用 `admin` 审核自己提交的申请单应成功；用非管理员账号自审应被拒绝

### 8.5 回滚

| 场景 | 处置 |
|---|---|
| 路径 B 迁移失败 | 停服 → 用 §8.2 第 2 步的备份覆盖 → 回退代码至 `v2.0` → 启动 |
| 路径 A 重建后发现问题 | 用 `ctms.db.bak` 恢复**旧库**（数据回到 V2.0 状态）→ 回退代码至 `v2.0` |
| 仅前端问题 | 用上一版 `web/dist` 覆盖，无需动库 |

> 注意：V2.1 迁移本身是**结构新增**，V2.0 代码可继续运行于迁移后的库（新表/新列被忽略）；但**路径 A 的清库动作不可逆**。
