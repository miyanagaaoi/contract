# V2.5.1 发行说明（增量）

> 标签：`v2.5.1`　产物：`ctms-image-2.5.1.tar`　镜像：`ctms:2.5.1`
> 基线：`v2.5.0`（财务模块）。本版为**增量修复 + 四项业务改进**，无破坏性变更。

## 1. 本版内容

**打印模板：5 个组成部分显示开关**
- 标题区 / 表头信息 / 行项明细 / 签字栏 / 页脚各自一个开关，默认全开；
- 旧模板配置缺这些键时自动按"全开"处理，升级后版面不变；
- 付款单（《付款申请单》固定网格）同样生效：标题行、信息网格（含日期与备注行）、签字行分段可控。

**物料档案**
- 编码**留空即自动生成**（按商品类型码 + 序号），编辑态只读（编码是审计线索）；
- 「品牌」改为**从供应商档案选择**并显示**简称**（`Supplier.short_name`），落库仍是文本快照，
  历史自由文本有兜底项不会被清空。

**合同台账「已付金额」按财务单据取数**
- 采购/支出类合同取**付款单**（`paid_amount`），销售/收入类合同取**收款单**（新增 `received_amount`）；
- 收款单审核/反审核与付款单同构：增量回写、反审核精确回退、人工补录值不被覆盖；
- 列表/表单/详情/合同抽屉按合同方向自动取数；销售合同导入的"已付金额"落到 `received_amount`。

**工程**
- 版本号置为 `2.5.1`（`/api/health`、系统管理「关于」页显示）；
- 一键发行脚本 `scripts/publish-release.ps1` 默认值切到 `v2.5.1` / `ctms-image-2.5.1.tar`。

## 2. 数据库变更（启动时幂等自动执行）

- 仅新增 1 列：`contracts.received_amount NUMERIC(14,2) NOT NULL DEFAULT 0`（`db_migrate` 同步）；
- 无新表、无破坏性变更；V2.5.0 的 6 张财务表与 14 个字段沿用。

## 3. 升级步骤（从 2.5.0）

```bash
docker load -i ctms-image-2.5.1.tar
docker rm -f ctms && docker run -d --name ctms -p 8080:8000 -v ctms_data:/data \
  -e CTMS_DB_URL="postgresql+psycopg2://ctms:<密码>@<PG主机>:5444/ctms" \
  --env-file .env ctms:2.5.1
# 首次启动自动补 contracts.received_amount 列；如需权限同步：
app/.venv/Scripts/python.exe -m app.init_db --sync-roles
```

## 4. 验收

| 项 | 结果 |
|---|---|
| `pytest app/tests -q` | **455 passed** |
| `npm run build` | ✓ built |
| 新增用例 | 打印开关（默认/兼容/跳过/付款单分段）3 项、物料留空编码 1 项、合同收款回写 4 项 |
| 迁移 | `contracts.received_amount` 在临时库与真实库副本各加 1 列且幂等（真实库只读未写入） |

## 5. 本版未覆盖（如需请确认口径）

- 合同台账 **Excel 导出**的已付列与 Dashboard `paid_sum` 仍取 `paid_amount`；
- 历史销售合同人工填在 `paid_amount` 的值不会丢，但列表改显示 `received_amount`（未走收款单时为 0）——
  如需一次性平移（仅销售类 `paid_amount` → `received_amount`），需业务确认后执行数据脚本。
