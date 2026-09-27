"""权限点清单与菜单树（V2.0，唯一真源）。

设计（对应 `12-erp-system-design.md` §3.3）：
- 权限点以**代码常量**定义在此文件，是唯一真源；角色-权限关系落库（`role_permissions`）。
  这样可避免"权限点被误删导致系统不可用"。
- 权限点类型：`menu`（决定导航可见性）/ `button`（决定动作可点）。
- 数据范围（`SELF/DEPT/DEPT_SUB/ALL`）与权限点正交，定义在 `Role.data_scope`。
- 前端菜单不写死：由 `menu_tree_for()` 按当前用户权限裁剪后返回。
"""
from __future__ import annotations

# (code, 名称, 模块, 类型)
PERMISSIONS: list[tuple[str, str, str, str]] = [
    ("dashboard.view", "首页看板", "dashboard", "menu"),

    ("contract.view", "合同查看", "contract", "menu"),
    ("contract.create", "合同新增", "contract", "button"),
    ("contract.edit", "合同编辑", "contract", "button"),
    ("contract.delete", "合同停用/恢复", "contract", "button"),
    ("contract.import", "合同导入", "contract", "button"),
    ("contract.export", "合同导出", "contract", "button"),
    ("contract.log.view", "合同变更历史", "contract", "button"),

    ("purchase.request.view", "采购申请查看", "purchase", "menu"),
    ("purchase.request.create", "采购申请新增", "purchase", "button"),
    ("purchase.request.edit", "采购申请编辑", "purchase", "button"),
    ("purchase.request.submit", "采购申请提交", "purchase", "button"),
    ("purchase.request.approve", "采购申请审核", "purchase", "button"),
    ("purchase.request.void", "采购申请作废", "purchase", "button"),
    ("purchase.request.export", "采购申请导出", "purchase", "button"),

    ("purchase.order.view", "采购单查看", "purchase", "menu"),
    ("purchase.order.create", "采购单新增", "purchase", "button"),
    ("purchase.order.edit", "采购单编辑", "purchase", "button"),
    ("purchase.order.submit", "采购单提交", "purchase", "button"),
    ("purchase.order.approve", "采购单审核", "purchase", "button"),
    ("purchase.order.void", "采购单作废", "purchase", "button"),
    ("purchase.order.push", "采购单下推入库", "purchase", "button"),
    ("purchase.order.export", "采购单导出", "purchase", "button"),

    ("sales.request.view", "销售申请查看", "sales", "menu"),
    ("sales.request.create", "销售申请新增", "sales", "button"),
    ("sales.request.edit", "销售申请编辑", "sales", "button"),
    ("sales.request.submit", "销售申请提交", "sales", "button"),
    ("sales.request.approve", "销售申请审核", "sales", "button"),
    ("sales.request.void", "销售申请作废", "sales", "button"),
    ("sales.request.export", "销售申请导出", "sales", "button"),

    ("sales.order.view", "销售订单查看", "sales", "menu"),
    ("sales.order.create", "销售订单新增", "sales", "button"),
    ("sales.order.edit", "销售订单编辑", "sales", "button"),
    ("sales.order.submit", "销售订单提交", "sales", "button"),
    ("sales.order.approve", "销售订单审核", "sales", "button"),
    ("sales.order.void", "销售订单作废", "sales", "button"),
    ("sales.order.push", "销售订单下推出库", "sales", "button"),
    ("sales.order.export", "销售订单导出", "sales", "button"),

    ("stock.in.view", "入库单查看", "stock", "menu"),
    ("stock.in.create", "入库单新增", "stock", "button"),
    ("stock.in.edit", "入库单编辑", "stock", "button"),
    ("stock.in.submit", "入库单提交", "stock", "button"),
    ("stock.in.approve", "入库单审核(过账)", "stock", "button"),
    ("stock.in.void", "入库单作废", "stock", "button"),
    ("stock.in.export", "入库单导出", "stock", "button"),

    ("stock.out.view", "出库单查看", "stock", "menu"),
    ("stock.out.create", "出库单新增", "stock", "button"),
    ("stock.out.edit", "出库单编辑", "stock", "button"),
    ("stock.out.submit", "出库单提交", "stock", "button"),
    ("stock.out.approve", "出库单审核(过账)", "stock", "button"),
    ("stock.out.void", "出库单作废", "stock", "button"),
    ("stock.out.export", "出库单导出", "stock", "button"),

    ("stock.take.view", "盘点单查看", "stock", "menu"),
    ("stock.take.create", "盘点单新增", "stock", "button"),
    ("stock.take.edit", "盘点单编辑", "stock", "button"),
    ("stock.take.submit", "盘点单提交", "stock", "button"),
    ("stock.take.approve", "盘点单审核", "stock", "button"),
    ("stock.take.void", "盘点单作废", "stock", "button"),
    ("stock.take.export", "盘点单导出", "stock", "button"),

    ("stock.balance.view", "库存明细", "stock", "menu"),
    ("stock.ledger.view", "库存流水", "stock", "button"),

    # ---- V2.1（N13）：调拨单 ----
    ("stock.transfer.view", "调拨单查看", "stock", "menu"),
    ("stock.transfer.create", "调拨单新增", "stock", "button"),
    ("stock.transfer.edit", "调拨单编辑", "stock", "button"),
    ("stock.transfer.submit", "调拨单提交", "stock", "button"),
    ("stock.transfer.approve", "调拨单审核(过账)", "stock", "button"),
    ("stock.transfer.void", "调拨单作废", "stock", "button"),
    ("stock.transfer.export", "调拨单导出", "stock", "button"),

    ("master.org.view", "组织架构查看", "master", "menu"),
    ("master.org.edit", "组织架构维护", "master", "button"),
    ("master.role.view", "角色查看", "master", "menu"),
    ("master.role.edit", "角色维护", "master", "button"),
    ("master.user.view", "账号查看", "master", "menu"),
    ("master.user.edit", "账号维护", "master", "button"),
    ("master.user.resetpwd", "重置密码", "master", "button"),
    ("master.customer.view", "客户查看", "master", "menu"),
    ("master.customer.edit", "客户维护", "master", "button"),
    ("master.supplier.view", "供应商查看", "master", "menu"),
    ("master.supplier.edit", "供应商维护", "master", "button"),
    ("master.product.view", "物料查看", "master", "menu"),
    ("master.product.edit", "物料维护", "master", "button"),
    ("master.ptype.view", "商品类型查看", "master", "menu"),
    ("master.ptype.edit", "商品类型维护", "master", "button"),
    ("master.uom.view", "计量单位查看", "master", "menu"),
    ("master.uom.edit", "计量单位维护", "master", "button"),
    ("master.wh.view", "仓库查看", "master", "menu"),
    ("master.wh.edit", "仓库维护", "master", "button"),

    ("system.dict.view", "数据字典查看", "system", "menu"),
    ("system.dict.edit", "数据字典维护", "system", "button"),
    ("system.param.view", "系统参数查看", "system", "button"),
    ("system.param.edit", "系统参数维护", "system", "button"),
    ("system.number.view", "编号规则查看", "system", "button"),
    ("system.log.view", "操作日志查看", "system", "menu"),
    ("system.changelog.view", "变更历史查看", "system", "menu"),
    ("system.backup.create", "生成备份", "system", "button"),
    ("system.backup.download", "下载备份", "system", "button"),
    ("system.about.view", "关于", "system", "button"),

    # ---- V2.2：单据打印模板（版面可视化调整） ----
    ("system.print.view", "打印模板查看", "system", "menu"),
    ("system.print.edit", "打印模板维护", "system", "button"),
]

PERM_CODES: set[str] = {p[0] for p in PERMISSIONS}
PERM_NAMES: dict[str, str] = {p[0]: p[1] for p in PERMISSIONS}
PERM_MODULES: dict[str, str] = {p[0]: p[2] for p in PERMISSIONS}

# 模块中文名（权限树与菜单分组展示用）
MODULE_LABELS: dict[str, str] = {
    "dashboard": "首页看板",
    "contract": "合同管理",
    "purchase": "采购管理",
    "sales": "销售管理",
    "stock": "库存管理",
    "master": "资料库",
    "system": "系统管理",
}

# 菜单树：(key, 标题, 路由, 图标名, 权限点, 子菜单)
MENUS: list[dict] = [
    {"key": "dashboard", "title": "首页看板", "path": "/", "icon": "Odometer",
     "perm": "dashboard.view"},
    {"key": "contract", "title": "合同管理", "path": "/contracts", "icon": "Files",
     "perm": "contract.view"},
    {"key": "purchase", "title": "采购管理", "icon": "ShoppingCart",
     "perm": "purchase.request.view", "children": [
         {"key": "purchase-request", "title": "采购申请单", "path": "/purchase/requests",
          "perm": "purchase.request.view"},
         {"key": "purchase-order", "title": "采购单", "path": "/purchase/orders",
          "perm": "purchase.order.view"}]},
    {"key": "sales", "title": "销售管理", "icon": "Sell",
     "perm": "sales.request.view", "children": [
         {"key": "sales-request", "title": "销售申请单", "path": "/sales/requests",
          "perm": "sales.request.view"},
         {"key": "sales-order", "title": "销售订单", "path": "/sales/orders",
          "perm": "sales.order.view"}]},
    {"key": "stock", "title": "库存管理", "icon": "Box",
     "perm": "stock.balance.view", "children": [
         {"key": "stock-in", "title": "入库单", "path": "/stock/in-orders",
          "perm": "stock.in.view"},
         {"key": "stock-out", "title": "出库单", "path": "/stock/out-orders",
          "perm": "stock.out.view"},
         {"key": "stock-balance", "title": "库存明细", "path": "/stock/balances",
          "perm": "stock.balance.view"},
         {"key": "stock-take", "title": "盘点单", "path": "/stock/takes",
          "perm": "stock.take.view"},
         {"key": "stock-transfer", "title": "调拨单", "path": "/stock/transfers",
          "perm": "stock.transfer.view"}]},
    {"key": "master", "title": "资料库", "icon": "Folder",
     "perm": "master.product.view", "children": [
         {"key": "m-org", "title": "组织架构", "path": "/master/orgs", "perm": "master.org.view"},
         {"key": "m-role", "title": "角色管理", "path": "/master/roles", "perm": "master.role.view"},
         {"key": "m-user", "title": "账号管理", "path": "/master/users", "perm": "master.user.view"},
         {"key": "m-customer", "title": "客户信息", "path": "/master/customers",
          "perm": "master.customer.view"},
         {"key": "m-supplier", "title": "供应商信息", "path": "/master/suppliers",
          "perm": "master.supplier.view"},
         {"key": "m-base", "title": "基础信息", "perm": "master.product.view", "children": [
             {"key": "m-ptype", "title": "商品类型", "path": "/master/product-types",
              "perm": "master.ptype.view"},
             {"key": "m-prod", "title": "物料档案", "path": "/master/products",
              "perm": "master.product.view"},
             {"key": "m-uom", "title": "计量单位", "path": "/master/uoms",
              "perm": "master.uom.view"},
             {"key": "m-wh", "title": "仓库", "path": "/master/warehouses",
              "perm": "master.wh.view"}]},
         {"key": "m-system", "title": "系统管理", "path": "/system", "perm": "system.dict.view"},
         {"key": "m-print", "title": "打印模板", "path": "/system/print-templates",
          "perm": "system.print.view"}]},
]

# 数据范围
DATA_SCOPES = [
    ("SELF", "本人"),
    ("DEPT", "本部门"),
    ("DEPT_SUB", "本部门及下级"),
    ("ALL", "全部"),
]
DATA_SCOPE_CODES = {c for c, _ in DATA_SCOPES}
# 取值范围排序（用于多角色取最宽）
_SCOPE_RANK = {"SELF": 1, "DEPT": 2, "DEPT_SUB": 3, "ALL": 4}

# 预置角色（对应 `11-erp-requirements.md` §3.4 权限矩阵；perms 支持 "模块.*" 通配）
ROLE_PRESETS: list[dict] = [
    {"code": "sysadmin", "name": "系统管理员", "data_scope": "ALL",
     "remark": "全部权限；内置角色不可删除", "perms": ["*"]},
    {"code": "purchase_manager", "name": "采购主管", "data_scope": "DEPT_SUB",
     "remark": "采购单据审核 + 采购域数据", "perms": [
         "dashboard.view", "contract.view", "contract.create", "contract.edit",
         "contract.export", "contract.log.view",
         "purchase.*", "stock.balance.view", "stock.ledger.view",
         "master.product.view", "master.ptype.view", "master.uom.view", "master.wh.view",
         "master.customer.view", "master.supplier.view"]},
    {"code": "buyer", "name": "采购员", "data_scope": "SELF",
     "remark": "采购单据录入与提交（不可审核）", "perms": [
         "dashboard.view", "contract.view", "contract.create", "contract.edit",
         "contract.export",
         "purchase.request.view", "purchase.request.create", "purchase.request.edit",
         "purchase.request.submit", "purchase.request.export",
         "purchase.order.view", "purchase.order.create", "purchase.order.edit",
         "purchase.order.submit", "purchase.order.export",
         "stock.balance.view", "master.product.view", "master.ptype.view",
         "master.uom.view", "master.wh.view", "master.supplier.view"]},
    {"code": "sales_manager", "name": "销售主管", "data_scope": "DEPT_SUB",
     "remark": "销售单据审核 + 销售域数据", "perms": [
         "dashboard.view", "contract.view", "contract.create", "contract.edit",
         "contract.export", "contract.log.view",
         "sales.*", "stock.balance.view", "stock.ledger.view",
         "master.product.view", "master.ptype.view", "master.uom.view", "master.wh.view",
         "master.customer.view", "master.supplier.view"]},
    {"code": "seller", "name": "销售员", "data_scope": "SELF",
     "remark": "销售单据录入与提交（不可审核）", "perms": [
         "dashboard.view", "contract.view", "contract.create", "contract.edit",
         "contract.export",
         "sales.request.view", "sales.request.create", "sales.request.edit",
         "sales.request.submit", "sales.request.export",
         "sales.order.view", "sales.order.create", "sales.order.edit",
         "sales.order.submit", "sales.order.export",
         "stock.balance.view", "master.product.view", "master.ptype.view",
         "master.uom.view", "master.wh.view", "master.customer.view"]},
    {"code": "keeper", "name": "仓管员", "data_scope": "ALL",
     "remark": "出入库与盘点录入、审核（触发库存过账）", "perms": [
         "dashboard.view", "contract.view", "stock.*",
         "purchase.order.view", "sales.order.view",
         "master.product.view", "master.ptype.view", "master.uom.view", "master.wh.view"]},
    {"code": "finance", "name": "财务", "data_scope": "ALL",
     "remark": "全量只读 + 导出（V2.0 不含财务模块）", "perms": [
         "dashboard.view", "contract.view", "contract.export", "contract.log.view",
         "purchase.request.view", "purchase.order.view", "purchase.order.export",
         "sales.request.view", "sales.order.view", "sales.order.export",
         "stock.in.view", "stock.out.view", "stock.take.view", "stock.transfer.view", "stock.balance.view",
         "stock.ledger.view",
         "master.product.view", "master.ptype.view", "master.uom.view", "master.wh.view",
         "master.customer.view", "master.supplier.view"]},
    {"code": "viewer", "name": "只读/管理层", "data_scope": "ALL",
     "remark": "全量只读", "perms": [
         "dashboard.view", "contract.view", "contract.log.view",
         "purchase.request.view", "purchase.order.view",
         "sales.request.view", "sales.order.view",
         "stock.in.view", "stock.out.view", "stock.take.view", "stock.transfer.view", "stock.balance.view",
         "stock.ledger.view",
         "master.product.view", "master.ptype.view", "master.uom.view", "master.wh.view",
         "master.customer.view", "master.supplier.view"]},
]


def expand_perms(patterns: list[str] | None) -> list[str]:
    """把 `["purchase.*", "contract.view"]` 展开为权限点清单（保持定义顺序去重）。"""
    pats = [p for p in (patterns or []) if p]
    if "*" in pats:
        return [p[0] for p in PERMISSIONS]
    picked: set[str] = set()
    for pat in pats:
        if pat.endswith(".*"):
            prefix = pat[:-1]           # "purchase."
            picked.update(c for c in PERM_CODES if c.startswith(prefix))
        elif pat in PERM_CODES:
            picked.add(pat)
    return [p[0] for p in PERMISSIONS if p[0] in picked]


def widest_scope(scopes) -> str:
    """多角色数据范围取最宽（BR-V2-08）。"""
    best = "SELF"
    for s in scopes or []:
        if _SCOPE_RANK.get(s, 0) > _SCOPE_RANK.get(best, 0):
            best = s
    return best


def _filter_menu(nodes: list[dict], perms: set[str]) -> list[dict]:
    out: list[dict] = []
    for n in nodes:
        item = {k: v for k, v in n.items() if k != "children"}
        children = _filter_menu(n.get("children") or [], perms)
        if children:
            item["children"] = children
            out.append(item)
        elif n.get("perm") in perms:
            out.append(item)
    return out


def menu_tree_for(perms: set[str] | None, is_superadmin: bool = False) -> list[dict]:
    """按权限裁剪后的导航树（超管返回全部）。"""
    if is_superadmin:
        return MENUS
    return _filter_menu(MENUS, perms or set())


def perm_tree() -> list[dict]:
    """权限点的分组清单（角色配置界面用）。"""
    groups: dict[str, list[dict]] = {}
    for code, name, module, ptype in PERMISSIONS:
        groups.setdefault(module, []).append({"code": code, "name": name, "type": ptype})
    return [
        {"module": m, "label": MODULE_LABELS.get(m, m), "perms": items}
        for m, items in groups.items()
    ]
