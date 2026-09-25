# 20. V2.0 验收报告（AC 逐条覆盖 · 汇总）

> 用途：一份文档回答"V2.0 每条验收场景由谁验证、用什么证据、结论如何"。
> 本报告由开发侧据**可复现的自动化证据**出具；业务侧确认（UAT）按 `17-uat-plan.md` 执行后在本文件 §5 补签。

## 1. 范围与版本

| 项 | 内容 |
|---|---|
| 需求规格 | `11-erp-requirements.md`（PRD V2.0，AC-V2-01 ~ AC-V2-42） |
| 详细设计 | `12-erp-system-design.md`（V2.0，已冻结） |
| 回归范围 | V1.0 合同模块 AC-01 ~ AC-15（`01-requirements.md`） |
| 里程碑 | M1 `v2.0-m1`、M2 `v2.0-m2`、M3 `v2.0-m3`（`v2.0` 待 UAT 后打） |
| 代码基线 | 分支 main，最新提交见仓库 `git log` |

## 2. 验证环境与命令（可复现）

```powershell
# 后端测试
app\.venv\Scripts\python.exe -m pytest app/tests -q

# 端到端冒烟（服务需运行在 :8010，见 19-go-live-checklist.md）
$env:CTMS_SMOKE_BASE='http://127.0.0.1:8010/api'
app\.venv\Scripts\python.exe app\tests\smoke_m1.py            # 权限与主数据
app\.venv\Scripts\python.exe app\tests\smoke_m2.py            # 采购线与库存过账
app\.venv\Scripts\python.exe app\tests\smoke_m3.py            # 销售、盘点、导出、打印
app\.venv\Scripts\python.exe app\tests\smoke_p0.py            # V1.0 合同模块回归
app\.venv\Scripts\python.exe app\tests\drill_backup_restore.py  # 备份可生成可还原
app\.venv\Scripts\python.exe app\tools\audit_role_matrix.py     # 权限矩阵复核

# 前端
cd web; npm run build
```

## 3. 总体验证结果

| 验证项 | 结果 | 证据 |
|---|---|---|
| 单元/接口测试 | **244 passed** | `pytest app/tests -q` |
| M1 端到端冒烟 | **15/15 PASS** | `smoke_m1.py` |
| M2 端到端冒烟 | **11/11 PASS** | `smoke_m2.py` |
| M3 端到端冒烟 | **11/11 PASS** | `smoke_m3.py` |
| V1.0 合同模块回归 | **13/13 PASS** | `smoke_p0.py` |
| 权限矩阵 | 8 角色 × 26 接口全部一致 | `16-permission-matrix.md` |
| 备份恢复演练 | 12 张表行数一致、`integrity_check=ok` | `15-backup-drill.md` |
| 前端构建 | `✓ built in 4.80s` | `npm run build` |
| 服务健康 | `{"status":"ok","db":true}` | `GET /api/health` |
| SPA 路由可达 | 采购/销售/出入库/盘点/库存明细均 200 | 路由检查 |

## 4. AC 逐条覆盖（AC-V2-01 ~ AC-V2-42）

| AC | 场景 | 证据（可复现） | 结果 |
|---|---|---|---|
| AC-V2-01 | 登录与鉴权（含失败登录写日志） | `smoke_m1` / `test_v2_auth_api.py` | ✅ |
| AC-V2-02 | 未登录拦截（接口 401、前端跳登录） | `smoke_m1` / `test_v2_api_gate.py` | ✅ |
| AC-V2-03 | 菜单与按钮权限（越权调接口 403） | `smoke_m1` / `16-permission-matrix.md` | ✅ |
| AC-V2-04 | 数据范围-本人 | `smoke_m1` / `test_v2_contract_perm.py` | ✅ |
| AC-V2-05 | 数据范围-本部门及下级 | `smoke_m1` | ✅ |
| AC-V2-06 | 多角色权限并集（范围取最宽、写仍受限） | `smoke_m1` | ✅ |
| AC-V2-07 | 组织节点删除校验 | `smoke_m1` / `test_v2_org.py` | ✅ |
| AC-V2-08 | 首登强制改密 + 管理员重置 | `smoke_m1` / `test_v2_role_user.py` | ✅ |
| AC-V2-09 | 商品类型树与物料挂载（非叶子拒绝） | `smoke_m1` / `test_v2_master.py` | ✅ |
| AC-V2-10 | 物料编码自动生成与唯一 | `smoke_m1` / `test_v2_master.py` | ✅ |
| AC-V2-11 | 计量单位小数位校验（含行项录入） | `smoke_m1` / `test_v2_master.py` / `test_v2_docs.py` | ✅ |
| AC-V2-12 | 客户/供应商停用（下拉隐藏、历史显示） | `smoke_m1` | ✅ |
| AC-V2-13 | 采购申请提交与审核 | `smoke_m2` / `test_v2_docs.py` | ✅ |
| AC-V2-14 | 驳回回草稿并记录原因 | `smoke_m2` | ✅ |
| AC-V2-15 | 创建人不可自审 | `test_v2_docs.py` | ✅ |
| AC-V2-16 | 申请下推采购单（剩余量约束） | `smoke_m2` | ✅ |
| AC-V2-17 | 作废留痕、默认不进列表 | `test_v2_docs.py` | ✅ |
| AC-V2-18 | 已入库数量回写采购单 | `smoke_m2` | ✅ |
| AC-V2-19 | 入库审核增加库存 + 流水 | `smoke_m2` | ✅ |
| AC-V2-20 | 出库审核减少库存 | `smoke_m2` / `smoke_m3` | ✅ |
| AC-V2-21 | 负库存拦截（库存与状态均不变） | `smoke_m2` / `smoke_m3` / `test_v2_docs.py` | ✅ |
| AC-V2-22 | 反审核红冲（追加负向流水） | `smoke_m2` | ✅ |
| AC-V2-23 | 过账幂等（重复审核不重复过账） | `smoke_m2` / `test_v2_docs.py` | ✅ |
| AC-V2-24 | 有下游单据时禁止反审核 | `smoke_m2` / `test_v2_docs.py` | ✅ |
| AC-V2-25 | 库存流水下钻（含变动后结存） | `/api/stock/ledger` + 前端流水抽屉（`test_v2_docs.py`） | ✅ |
| AC-V2-26 | 结存 == 流水累计（recalc） | `smoke_m2` / `smoke_m3` | ✅ |
| AC-V2-27 | 全盘按结存生成行项、账面只读 | `smoke_m3` / `test_v2_docs.py` | ✅ |
| AC-V2-28 | 盘亏自动生成盘亏出库单并过账 | `smoke_m3` | ✅ |
| AC-V2-29 | 盘盈自动生成盘盈入库单 | `smoke_m3` / `test_v2_docs.py` | ✅ |
| AC-V2-30 | 抽盘（按类型/指定物料） | `test_v2_docs.py` | ✅ |
| AC-V2-31 | 单据关联合同（下拉仅同方向合同） | `/api/purchase/contract-options`、`/api/sales/contract-options` | ✅ |
| AC-V2-32 | 合同详情关联单据**只读**汇总 | `smoke_m2` / `smoke_m3` / `test_v2_docs.py` | ✅ |
| AC-V2-33 | 合同甲乙方档案化（id + 名称快照） | `test_v2_parties.py` / `smoke_m1` | ✅ |
| AC-V2-34 | 历史合同文本兼容 | `test_v2_parties.py` | ✅ |
| AC-V2-35 | 历史档案认领（扫描→认领→批量绑定） | `smoke_m1` / `test_v2_parties.py` | ✅ |
| AC-V2-36 | 操作日志（动作 + 时间范围筛选） | `test_v2_system.py` / `smoke_m1` | ✅ |
| AC-V2-37 | 变更历史带操作人（V1.0 显示"—"） | `test_v2_system.py` / `smoke_p0` | ✅ |
| AC-V2-38 | 系统管理整合（字典/参数/编号/日志/历史/备份/关于） | `smoke_m1` / `test_v2_system.py` | ✅ |
| AC-V2-39 | 手动备份下载（zip 含库与附件） | `smoke_m1` / `drill_backup_restore.py` | ✅ |
| AC-V2-40 | 导出与筛选一致（7 类单据 + 库存） | `test_v2_docs.py::TestDocExport` / `smoke_m3` | ✅ |
| AC-V2-41 | 权限后端强校验（构造请求 403） | `test_v2_master.py` / `16-permission-matrix.md` | ✅ |
| AC-V2-42 | 数据范围与主数据边界 | `smoke_m1` / `audit_role_matrix.py` | ✅ |

**V1.0 回归（AC-01 ~ AC-15）**：`smoke_p0.py` **13/13 PASS**，其中 AC-01~AC-11/12/14 逐条断言，
停用/恢复、质保算法、导出与筛选一致均覆盖。

## 5. 未由自动化覆盖的部分（人工确认）

| # | 项 | 说明 | 责任人 |
|---|---|---|---|
| 1 | 浏览器界面点击与观感 | 本环境浏览器自动化组件不可用；已用构建 + HTTP 契约 + SPA 路由可达替代 | 开发 + 业务用户 |
| 2 | 业务口径匹配度 | 如"下单金额与合同金额的拆分方式""盘点频率与责任人"是否符合实际 | 采购 / 财务 / 项目管理 |
| 3 | 三类用户逐条演示与签字 | 按 `17-uat-plan.md` §4 执行并填写异议与签字页 | 业务用户 |
| 4 | 上线窗口与培训 | 按 `19-go-live-checklist.md` §2 执行 | 运维 + 业务 |

## 6. 结论

- **开发侧交付完成**：T-V2-01 ~ T-V2-42 全部任务实现并提交，自动化证据全绿（244 测试 + 4 套端到端冒烟 + 权限矩阵 + 备份演练 + 构建）；
- **发布条件**：`19-go-live-checklist.md` §2 检查项全部满足，且 UAT（§5 第 3 项）≥80% 场景无异议；
- **风险提示**：库存只记数量不记成本、不含财务模块、打印为固定模板（详见 `11` §14 与 `19` §7）。

## 7. 签字

| 角色 | 姓名 | 结论 | 日期 |
|---|---|---|---|
| 采购 | | | |
| 财务 | | | |
| 项目管理 | | | |
| 开发/交付 | | | |
