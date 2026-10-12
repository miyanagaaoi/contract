# V2.5.0 发行说明（财务模块）

> 标签：`v2.5.0`　产物：`ctms-image-2.5.0.tar`　镜像：`ctms:2.5.0`

## 1. 本版内容

**财务模块（新）**
- 付款单 / 收款单 / 发票：走既有单据状态机（提交 → 财务审核即记账 → 反审核红冲）；
  发票为「草稿 → 确认入账 → 作废」+ 认证状态；
- **核销**：多态核销明细（付款→采购单/入库单、收款→销售订单/出库单、发票→采购单/销售订单）；
  M1 界面一对一，M3 起支持一单核多单；
- **回写与进度**：采购单/销售订单新增 `paid_amount`/`received_amount`/`invoiced_amount`，
  审核回写、反审核精确红冲；列表新增六条进度列（收货/付款/收票、发货/收款/开票，
  含税口径，分母 0 显示 `—`，超额标红）；
- **快速发起**：采购单/销售订单列表「更多」→ 发起付款单/收款单、登记进项/销项发票，
  预填往来单位与未付/未收票金额；
- **资金概览 + 账龄**：待付/待收/待收票/待开票、待认证与超额提醒；
  账龄 0-30/31-60/61-90/90+（按单据日期，支持 `as_of` 基准日）与 Excel 导出；
- **付款申请单打印模板**：严格对齐纸质模板（A4 横向、列宽比例/行高/字体/页边距同值，
  固定 12 行 × 7 列，金额大写自动换算），**模板外项目默认关闭打印**；
- 合同「累计已付」按增量自动回写（保留人工补录值）。

**相邻修复与改进**
- 修复下推生成的单据被编辑后丢失 `src_item_id`，导致已入库数量/收货进度不回写、可重复下推
  （含存量数据修复工具 `app/tools/backfill_src_item_v25.py`，默认 dry-run）；
- 下推对话框提示"已下推但未生效"的下游单据（保守口径，不改可推量算法）；
- 单据列表「来源单号」「关联合同」可点击 → 抽屉查看上游单据 / 合同详情；
- 飞书扫码未绑定自动建号（零角色、待管理员分配，`/pending` 页）；
- 项目 logo 接入（登录页/侧栏/标签页图标）；
- 物料档案商品类型选不中（404 路径）、合同汇总金额不实时、合同经办人改选系统用户、
  合同行项显示单位。

## 2. 数据库变更（启动时幂等自动执行）

- 新增 6 张表：`payment_orders`、`receipt_orders`、`invoices`、`payment_allocations`、
  `receipt_allocations`、`invoice_allocations`；
- `payment_orders` 纸质模板字段 9 列（`payee_bank`/`payee_account`/`payer_bank`/`category_l1`/
  `category_l2`/`belong_period`/`bank_purpose`/`pay_reason`/`plan_type`）；
- 回写列 4 个：`purchase_orders.paid_amount`/`invoiced_amount`、
  `sales_orders.received_amount`/`invoiced_amount`；
- 新增 20 个权限点（`finance.*`）：升级后执行 `python -m app.init_db --sync-roles` 同步内置角色
  （`sysadmin` 自动补齐）。

## 3. 部署

```bash
docker load -i ctms-image-2.5.0.tar
# SQLite（卷内）
docker run -d --name ctms -p 8080:8000 -v ctms_data:/data ctms:2.5.0
# PostgreSQL
docker run -d --name ctms -p 8080:8000 -v ctms_data:/data \
  -e CTMS_DB_URL="postgresql+psycopg2://ctms:<密码>@<PG主机>:5444/ctms" ctms:2.5.0
# 飞书配置：--env-file .env（或 compose env_file），详见 docs/34
```

详见 `docs/34-postgresql-production-setup.md`（含 PG 建库授权、迁移、校验、备份回滚、常见问题）。

## 4. 验收

| 项 | 结果 |
|---|---|
| `pytest app/tests -q` | **447 passed** |
| `npm run build` | ✓ built |
| 财务 E2E（`20-finance.spec.ts`） | 4 passed（0% → 30% → 反审核回 0%、权限显隐、发票票号唯一） |
| 财务冒烟 `smoke_v25_finance.py` | 5/5（回写与核销明细一致、无孤儿、权限种子齐备） |
| 容器 | `ctms:2.5.0` 连 SQLite / PostgreSQL 均启动正常（`/api/health` `db:true`） |
| 付款申请单版式 | headless Chrome 渲染截图与参考模板逐格比对（列宽/行高/字体/勾选串/大写） |

逐条 AC 覆盖见 `docs/32-v2.5-acceptance.md`（AC-V2.5-01~20 全绿）。
