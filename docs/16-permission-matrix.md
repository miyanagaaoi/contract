# 16. 权限矩阵复核记录（T-V2-39）

> 生成时间：2026-09-25 22:24　·　生成方式：`app/tools/audit_role_matrix.py`（自动探测）
> 复核内容：内置角色的生效权限点、菜单裁剪，以及各模块接口的 200（有权）/ 403（无权）实际返回。

## 1. 角色 × 权限点

| 角色 | 数据范围 | 权限点数 | 与预设一致 | 菜单入口 |
|---|---|---|---|---|
| 系统管理员（`sysadmin`） | ALL | 90 | ✅ | dashboard, contract, purchase, purchase-request, purchase-order, sales, sales-request, sales-order, stock, stock-in, stock-out, stock-balance, stock-take, master, m-org, m-role, m-user, m-customer, m-supplier, m-base, m-ptype, m-prod, m-uom, m-wh, m-system |
| 采购主管（`purchase_manager`） | DEPT_SUB | 29 | ✅ | dashboard, contract, purchase, purchase-request, purchase-order, stock, stock-balance, master, m-customer, m-supplier, m-base, m-ptype, m-prod, m-uom, m-wh |
| 采购员（`buyer`） | SELF | 21 | ✅ | dashboard, contract, purchase, purchase-request, purchase-order, stock, stock-balance, master, m-supplier, m-base, m-ptype, m-prod, m-uom, m-wh |
| 销售主管（`sales_manager`） | DEPT_SUB | 29 | ✅ | dashboard, contract, sales, sales-request, sales-order, stock, stock-balance, master, m-customer, m-supplier, m-base, m-ptype, m-prod, m-uom, m-wh |
| 销售员（`seller`） | SELF | 21 | ✅ | dashboard, contract, sales, sales-request, sales-order, stock, stock-balance, master, m-customer, m-base, m-ptype, m-prod, m-uom, m-wh |
| 仓管员（`keeper`） | ALL | 31 | ✅ | dashboard, contract, purchase, purchase-order, sales, sales-order, stock, stock-in, stock-out, stock-balance, stock-take, master, m-base, m-ptype, m-prod, m-uom, m-wh |
| 财务（`finance`） | ALL | 21 | ✅ | dashboard, contract, purchase, purchase-request, purchase-order, sales, sales-request, sales-order, stock, stock-in, stock-out, stock-balance, stock-take, master, m-customer, m-supplier, m-base, m-ptype, m-prod, m-uom, m-wh |
| 只读/管理层（`viewer`） | ALL | 18 | ✅ | dashboard, contract, purchase, purchase-request, purchase-order, sales, sales-request, sales-order, stock, stock-in, stock-out, stock-balance, stock-take, master, m-customer, m-supplier, m-base, m-ptype, m-prod, m-uom, m-wh |

## 2. 接口探测矩阵

> ✔=有权且通过鉴权；—=无权且被 403 拦截；!N=异常（需修复）

| 角色 | 首页 | 合同 | 合同-导出 | 客户 | 供应商 | 物料 | 商品类型 | 计量单位 | 仓库 | 组织架构 | 角色 | 账号 | 采购申请 | 采购单 | 销售申请 | 销售订单 | 入库单 | 出库单 | 盘点单 | 库存明细 | 操作日志 | 系统参数 | 变更历史 | 关于 | 物料维护(写) | 单据审核(写) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 系统管理员 | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ |
| 采购主管 | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | — | — | — | ✔ | ✔ | — | — | — | — | — | ✔ | — | — | — | — | — | ✔ |
| 采购员 | ✔ | ✔ | ✔ | — | ✔ | ✔ | ✔ | ✔ | ✔ | — | — | — | ✔ | ✔ | — | — | — | — | — | ✔ | — | — | — | — | — | — |
| 销售主管 | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | — | — | — | — | — | ✔ | ✔ | — | — | — | ✔ | — | — | — | — | — | — |
| 销售员 | ✔ | ✔ | ✔ | ✔ | — | ✔ | ✔ | ✔ | ✔ | — | — | — | — | — | ✔ | ✔ | — | — | — | ✔ | — | — | — | — | — | — |
| 仓管员 | ✔ | ✔ | — | — | — | ✔ | ✔ | ✔ | ✔ | — | — | — | — | ✔ | — | ✔ | ✔ | ✔ | ✔ | ✔ | — | — | — | — | — | — |
| 财务 | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | — | — | — | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | — | — | — | — | — | — |
| 只读/管理层 | ✔ | ✔ | — | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | — | — | — | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | — | — | — | — | — | — |

## 3. 结论

**全部通过**：所有内置角色的权限点、菜单裁剪与接口访问控制一致，未发现越权放行或有权被拦的情况。

## 4. 复核要点说明

- 权限判定只在服务端执行（`require_perm`），前端隐藏按钮仅改善体验（AC-V2-41）；
- 主数据全公司共享但**写操作受独立权限点控制**（AC-V2-42）；
- 数据范围（本人/本部门/本部门及下级/全部）与权限点正交，本表只覆盖**权限点**维度，
  数据范围的自动化验证见 `test_v2_contract_perm.py`、`test_v2_docs.py`、`smoke_m1.py`。
