"""主数据服务（T-V2-07~11，对应 `12-erp-system-design.md` §4.2 与 §6.2）。

覆盖：
- 客户 / 供应商档案（编码自动生成 CUS/SUP，名称与编码全局唯一）
- 商品类型树（物化路径，**仅叶子可挂物料**，删除校验）
- 计量单位（含小数位）
- 仓库档案
- 物料档案（编码自动/手工、类型叶子校验、单位绑定、安全库存、启停用）

统一约定（与 `org_service` 一致）：
- 校验失败抛 `ValueError`，由路由层 `_run()` 转 HTTP 422 + 中文提示；
- 档案**不做物理删除的常规入口**：仅当无业务引用时才允许删除，否则提示改为停用；
- 主数据不分数据范围（`apply_data_scope` 不适用于本模块）。
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import inspect, or_, text
from sqlalchemy.orm import Session

from ..models import Contract
from ..models_master import (
    CUSTOMER_LEVELS,
    PARTY_STATUSES,
    Customer,
    Product,
    ProductType,
    Supplier,
    Uom,
    Warehouse,
)
from . import numbering_service

# 商品类型层级上限（与组织架构同级，防止无限下钻）
MAX_TYPE_LEVEL = 5
UOM_DECIMALS_RANGE = (0, 4)
TYPE_MAX_LEVEL = MAX_TYPE_LEVEL


# ==================== 通用工具 ====================

def _s(value) -> str:
    return str(value or "").strip()


def _opt(value) -> str | None:
    return _s(value) or None


def _dec(value, field: str, default: Decimal | None = None) -> Decimal | None:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        raise ValueError(f"{field}必须是数字")


def _int_opt(value) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError("整数字段取值非法")


def _paginate(query, page: int, page_size: int):
    total = int(query.count() or 0)
    page = max(1, int(page or 1))
    page_size = max(1, min(200, int(page_size or 20)))
    rows = query.offset((page - 1) * page_size).limit(page_size).all()
    return rows, total, page, page_size


def _page_payload(items: list[dict], total: int, page: int, page_size: int) -> dict:
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def count_refs(db: Session, kind: str, obj_id: int) -> int:
    """统计引用该档案的业务数据条数（按**已存在的表**动态探测）。

    这样 M1 只校验组织/合同引用，M2 单据与库存表建好后自动纳入，无需改动本函数。
    """
    checks: dict[str, list[tuple[str, str]]] = {
        "customer": [("contracts", "customer_id"), ("sales_orders", "customer_id"),
                     ("stock_out_orders", "customer_id")],
        "supplier": [("contracts", "supplier_id"), ("purchase_orders", "supplier_id"),
                     ("stock_in_orders", "supplier_id")],
        "product_type": [("products", "product_type_id")],
        "uom": [("products", "uom_id")],
        "product": [("stocks", "product_id"), ("stock_ledger", "product_id"),
                    ("purchase_request_items", "product_id"), ("purchase_order_items", "product_id"),
                    ("sales_request_items", "product_id"), ("sales_order_items", "product_id"),
                    ("stock_in_order_items", "product_id"), ("stock_out_order_items", "product_id"),
                    ("stock_take_items", "product_id")],
        "warehouse": [("stocks", "warehouse_id"), ("stock_ledger", "warehouse_id"),
                      ("stock_in_orders", "warehouse_id"), ("stock_out_orders", "warehouse_id"),
                      ("stock_takes", "warehouse_id"),
                      ("purchase_orders", "receipt_warehouse_id"), ("sales_orders", "ship_warehouse_id")],
    }
    targets = checks.get(kind) or []
    if not targets:
        return 0
    existing = set(inspect(db.get_bind()).get_table_names())
    total = 0
    for table, column in targets:
        if table not in existing:
            continue
        total += int(db.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE {column} = :oid"), {"oid": obj_id}
        ).scalar() or 0)
    return total


# ==================== 客户 / 供应商 ====================

_PARTY = {
    "customer": {"model": Customer, "label": "客户", "perm": "master.customer"},
    "supplier": {"model": Supplier, "label": "供应商", "perm": "master.supplier"},
}


def _party_conf(kind: str) -> dict:
    if kind not in _PARTY:
        raise ValueError(f"未知往来单位类别：{kind}")
    return _PARTY[kind]


def fmt_party(kind: str, obj) -> dict:
    data = {
        "id": obj.id,
        "code": obj.code,
        "name": obj.name,
        "short_name": obj.short_name,
        "tax_no": obj.tax_no,
        "contact_name": obj.contact_name,
        "contact_phone": obj.contact_phone,
        "address": obj.address,
        "bank_name": obj.bank_name,
        "bank_account": obj.bank_account,
        "credit_limit": float(obj.credit_limit) if obj.credit_limit is not None else None,
        "level": obj.level,
        "status": obj.status,
        "remark": obj.remark,
        "created_at": obj.created_at.isoformat() if obj.created_at else None,
        "updated_at": obj.updated_at.isoformat() if obj.updated_at else None,
    }
    if kind == "supplier":
        data["supply_scope"] = obj.supply_scope
        data["payment_days"] = obj.payment_days
    return data


def get_party(db: Session, kind: str, party_id: int):
    conf = _party_conf(kind)
    obj = db.get(conf["model"], party_id)
    if obj is None:
        raise ValueError(f"{conf['label']}档案不存在")
    return obj


def list_parties(db: Session, kind: str, *, keyword: str | None = None,
                 status: str | None = None, page: int = 1, page_size: int = 20) -> dict:
    conf = _party_conf(kind)
    model = conf["model"]
    query = db.query(model)
    if status:
        query = query.filter(model.status == status)
    kw = _s(keyword)
    if kw:
        like = f"%{kw}%"
        query = query.filter(or_(model.name.like(like), model.code.like(like),
                                 model.short_name.like(like), model.contact_name.like(like)))
    query = query.order_by(model.id.desc())
    rows, total, page, page_size = _paginate(query, page, page_size)
    return _page_payload([fmt_party(kind, r) for r in rows], total, page, page_size)


def _assert_party_unique(db: Session, kind: str, model, *, name: str, code: str,
                         exclude_id: int | None = None) -> None:
    label = _party_conf(kind)["label"]
    q = db.query(model).filter(model.name == name)
    if exclude_id:
        q = q.filter(model.id != exclude_id)
    if q.first() is not None:
        raise ValueError(f"已存在同名{label}：{name}")
    q = db.query(model).filter(model.code == code)
    if exclude_id:
        q = q.filter(model.id != exclude_id)
    if q.first() is not None:
        raise ValueError(f"{label}编码已存在：{code}")


def _apply_party_fields(db: Session, kind: str, obj, payload: dict) -> None:
    if "name" in payload:
        name = _s(payload.get("name"))
        if not name:
            raise ValueError(f"{_party_conf(kind)['label']}名称不能为空")
        if len(name) > 128:
            raise ValueError("名称最多 128 字")
        obj.name = name
    for field in ("short_name", "tax_no", "contact_name", "contact_phone", "address",
                  "bank_name", "bank_account", "level"):
        if field in payload:
            setattr(obj, field, _opt(payload.get(field)))
    if "credit_limit" in payload:
        obj.credit_limit = _dec(payload.get("credit_limit"), "授信额度")
    if "remark" in payload:
        obj.remark = _opt(payload.get("remark"))
    if "status" in payload:
        obj.status = "enabled" if payload.get("status") == "enabled" else "disabled"
    if kind == "supplier":
        if "supply_scope" in payload:
            obj.supply_scope = _opt(payload.get("supply_scope"))
        if "payment_days" in payload:
            days = _int_opt(payload.get("payment_days"))
            if days is not None and days < 0:
                raise ValueError("账期不能为负数")
            obj.payment_days = days


def create_party(db: Session, kind: str, payload: dict, user=None):
    conf = _party_conf(kind)
    model = conf["model"]
    name = _s(payload.get("name"))
    if not name:
        raise ValueError(f"{conf['label']}名称不能为空")

    def _build():
        code = _s(payload.get("code")).upper() or numbering_service.next_party_code(db, kind)
        obj = model(code=code, name=name, status="enabled",
                    created_by=getattr(user, "id", None))
        _apply_party_fields(db, kind, obj, payload)
        _assert_party_unique(db, kind, model, name=obj.name, code=obj.code)
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    return numbering_service.retry_on_conflict(db, _build)


def update_party(db: Session, kind: str, obj, payload: dict):
    conf = _party_conf(kind)
    model = conf["model"]
    if "code" in payload and _s(payload.get("code")):
        obj.code = _s(payload.get("code")).upper()
    _apply_party_fields(db, kind, obj, payload)
    _assert_party_unique(db, kind, model, name=obj.name, code=obj.code, exclude_id=obj.id)
    db.commit()
    db.refresh(obj)
    return obj


def set_party_status(db: Session, kind: str, obj, enabled: bool):
    obj.status = "enabled" if enabled else "disabled"
    db.commit()
    db.refresh(obj)
    return obj


def delete_party(db: Session, kind: str, obj) -> None:
    label = _party_conf(kind)["label"]
    if count_refs(db, kind, obj.id) > 0:
        raise ValueError(f"该{label}已被合同或单据引用，不能删除，请改为停用")
    db.delete(obj)
    db.commit()


def party_options(db: Session, kind: str, keyword: str | None = None, limit: int = 50) -> list[dict]:
    """轻量下拉数据（`/api/master/options/{kind}`）：仅启用档案。"""
    conf = _party_conf(kind)
    model = conf["model"]
    query = db.query(model).filter(model.status == "enabled")
    kw = _s(keyword)
    if kw:
        like = f"%{kw}%"
        query = query.filter(or_(model.name.like(like), model.code.like(like)))
    rows = query.order_by(model.name.asc()).limit(max(1, min(200, limit))).all()
    return [{"id": r.id, "code": r.code, "name": r.name, "short_name": r.short_name,
             "contact_name": r.contact_name, "contact_phone": r.contact_phone} for r in rows]


# ==================== 商品类型（树） ====================

def _fmt_type(node: ProductType, product_count: int = 0, child_count: int = 0) -> dict:
    return {
        "id": node.id,
        "parent_id": node.parent_id,
        "code": node.code,
        "name": node.name,
        "path": node.path,
        "level": node.level,
        "sort": node.sort,
        "enabled": node.enabled,
        "remark": node.remark,
        "is_leaf": child_count == 0,
        "child_count": child_count,
        "product_count": product_count,
    }


def build_type_tree(items: list[dict]) -> list[dict]:
    by_id = {i["id"]: dict(i, children=[]) for i in items}
    roots: list[dict] = []
    for item in by_id.values():
        parent = by_id.get(item.get("parent_id"))
        if parent is not None and parent is not item:
            parent["children"].append(item)
        else:
            roots.append(item)

    def _sort(nodes: list[dict]) -> None:
        nodes.sort(key=lambda x: (x.get("sort") or 0, x["id"]))
        for n in nodes:
            _sort(n["children"])

    _sort(roots)
    return roots


def list_product_types(db: Session, *, keyword: str | None = None,
                       include_disabled: bool = True) -> dict:
    query = db.query(ProductType)
    if not include_disabled:
        query = query.filter(ProductType.enabled == True)  # noqa: E712
    nodes = query.order_by(ProductType.sort.asc(), ProductType.id.asc()).all()

    from sqlalchemy import func as _func
    counts = dict(db.query(Product.product_type_id, _func.count(Product.id))
                  .group_by(Product.product_type_id).all())
    child_counts: dict[int, int] = {}
    for n in nodes:
        if n.parent_id:
            child_counts[n.parent_id] = child_counts.get(n.parent_id, 0) + 1

    items = [_fmt_type(n, counts.get(n.id, 0), child_counts.get(n.id, 0)) for n in nodes]
    kw = _s(keyword)
    if kw:
        # 命中节点**连同其下级**一起保留（搜"钢材"应看到钢材下的全部子类）
        matched = [n for n in nodes if kw in n.name or (n.code and kw in n.code)]
        matched_ids = {n.id for n in matched}
        prefixes = [n.path for n in matched]
        items = [i for i in items
                 if i["id"] in matched_ids
                 or any(i["path"].startswith(p) for p in prefixes)]
    return {"items": items, "tree": build_type_tree(items), "total": len(items),
            "max_level": MAX_TYPE_LEVEL}


def get_product_type(db: Session, type_id: int) -> ProductType:
    node = db.get(ProductType, type_id)
    if node is None:
        raise ValueError("商品类型不存在")
    return node


def fmt_product_type(db: Session, node: ProductType) -> dict:
    """单节点详情（含子节点数与物料数，供前端展示"可否挂物料/可否删除"）。"""
    from sqlalchemy import func as _func

    child_count = int(db.query(_func.count(ProductType.id))
                      .filter(ProductType.parent_id == node.id).scalar() or 0)
    product_count = int(db.query(_func.count(Product.id))
                        .filter(Product.product_type_id == node.id).scalar() or 0)
    return _fmt_type(node, product_count, child_count)


def is_leaf(db: Session, type_id: int) -> bool:
    return db.query(ProductType.id).filter(ProductType.parent_id == type_id).first() is None


def assert_leaf_enabled(db: Session, type_id: int) -> ProductType:
    node = get_product_type(db, type_id)
    if not node.enabled:
        raise ValueError(f"商品类型「{node.name}」已停用，不能挂物料")
    if not is_leaf(db, node.id):
        raise ValueError(f"商品类型「{node.name}」下还有子类型，物料只能挂在叶子类型上")
    return node


def _assert_type_sibling_unique(db: Session, parent_id: int | None, name: str,
                                exclude_id: int | None = None) -> None:
    query = db.query(ProductType).filter(ProductType.parent_id == parent_id,
                                         ProductType.name == name)
    if exclude_id:
        query = query.filter(ProductType.id != exclude_id)
    if query.first() is not None:
        raise ValueError("同级下已存在同名商品类型")


def _apply_type_path(db: Session, node: ProductType, new_parent_id: int | None) -> None:
    old_prefix = node.path or ""
    parent = db.get(ProductType, new_parent_id) if new_parent_id else None
    if new_parent_id and parent is None:
        raise ValueError("上级类型不存在")
    base = parent.path if parent else "/"
    new_prefix = f"{base}{node.id}/"
    new_level = new_prefix.count("/") - 1
    if new_level > MAX_TYPE_LEVEL:
        raise ValueError(f"商品类型最多 {MAX_TYPE_LEVEL} 级")
    if parent is not None and old_prefix and parent.path.startswith(old_prefix):
        raise ValueError("不能把类型移动到它自己的下级")

    if old_prefix and old_prefix != new_prefix:
        for child in db.query(ProductType).filter(ProductType.path.like(old_prefix + "%")).all():
            child.path = new_prefix + child.path[len(old_prefix):]
            child.level = child.path.count("/") - 1
    else:
        node.path = new_prefix
        node.level = new_level
    node.parent_id = new_parent_id


def create_product_type(db: Session, payload: dict) -> ProductType:
    name = _s(payload.get("name"))
    if not name:
        raise ValueError("类型名称不能为空")
    if len(name) > 64:
        raise ValueError("类型名称最多 64 字")
    parent_id = _int_opt(payload.get("parent_id"))
    if parent_id is not None:
        parent = get_product_type(db, parent_id)
        if parent.level >= MAX_TYPE_LEVEL:
            raise ValueError(f"商品类型最多 {MAX_TYPE_LEVEL} 级")
    _assert_type_sibling_unique(db, parent_id, name)

    node = ProductType(
        parent_id=parent_id, name=name,
        code=(_s(payload.get("code")).upper() or None),
        sort=int(payload.get("sort") or 0),
        enabled=bool(payload.get("enabled", True)),
        remark=_opt(payload.get("remark")),
        path="", level=1,
    )
    db.add(node)
    db.flush()
    _apply_type_path(db, node, parent_id)
    db.commit()
    db.refresh(node)
    return node


def update_product_type(db: Session, node: ProductType, payload: dict) -> ProductType:
    new_parent_id = node.parent_id
    if "parent_id" in payload:
        new_parent_id = _int_opt(payload.get("parent_id"))
    if "name" in payload:
        name = _s(payload.get("name"))
        if not name:
            raise ValueError("类型名称不能为空")
        node.name = name
    if "code" in payload:
        node.code = _s(payload.get("code")).upper() or None
    if "sort" in payload:
        node.sort = int(payload.get("sort") or 0)
    if "enabled" in payload:
        node.enabled = bool(payload["enabled"])
    if "remark" in payload:
        node.remark = _opt(payload.get("remark"))

    if new_parent_id != node.parent_id:
        if new_parent_id is not None:
            parent = get_product_type(db, new_parent_id)
            if parent.level >= MAX_TYPE_LEVEL:
                raise ValueError(f"商品类型最多 {MAX_TYPE_LEVEL} 级")
        _apply_type_path(db, node, new_parent_id)
    _assert_type_sibling_unique(db, node.parent_id, node.name, exclude_id=node.id)
    db.commit()
    db.refresh(node)
    return node


def set_product_type_enabled(db: Session, node: ProductType, enabled: bool) -> ProductType:
    node.enabled = bool(enabled)
    db.commit()
    db.refresh(node)
    return node


def delete_product_type(db: Session, node: ProductType) -> None:
    if not is_leaf(db, node.id):
        raise ValueError("该类型下存在子类型，请先处理子类型，或改为停用")
    if count_refs(db, "product_type", node.id) > 0:
        raise ValueError("该类型下存在物料，不能删除，请改为停用")
    db.delete(node)
    db.commit()


def product_type_options(db: Session, keyword: str | None = None, leaf_only: bool = True) -> list[dict]:
    query = db.query(ProductType).filter(ProductType.enabled == True)  # noqa: E712
    kw = _s(keyword)
    if kw:
        like = f"%{kw}%"
        query = query.filter(or_(ProductType.name.like(like), ProductType.code.like(like)))
    nodes = query.order_by(ProductType.path.asc()).all()
    child_ids = {n.parent_id for n in db.query(ProductType.parent_id).all() if n[0]}
    out = []
    for n in nodes:
        if leaf_only and n.id in child_ids:
            continue
        out.append({"id": n.id, "code": n.code, "name": n.name, "path": n.path,
                    "level": n.level, "is_leaf": n.id not in child_ids})
    return out


# ==================== 计量单位 ====================

def fmt_uom(obj: Uom) -> dict:
    return {
        "id": obj.id, "code": obj.code, "name": obj.name, "decimals": obj.decimals,
        "enabled": obj.enabled, "remark": obj.remark,
        "usage_count": None,
    }


def get_uom(db: Session, uom_id: int) -> Uom:
    obj = db.get(Uom, uom_id)
    if obj is None:
        raise ValueError("计量单位不存在")
    return obj


def list_uoms(db: Session, *, keyword: str | None = None,
              include_disabled: bool = True) -> dict:
    query = db.query(Uom)
    if not include_disabled:
        query = query.filter(Uom.enabled == True)  # noqa: E712
    kw = _s(keyword)
    if kw:
        like = f"%{kw}%"
        query = query.filter(or_(Uom.name.like(like), Uom.code.like(like)))
    rows = query.order_by(Uom.id.asc()).all()
    return {"items": [fmt_uom(u) for u in rows], "total": len(rows)}


def _norm_decimals(value, default: int = 2) -> int:
    raw = 2 if value in (None, "") else value
    try:
        decimals = int(raw)
    except (TypeError, ValueError):
        raise ValueError("小数位必须是整数")
    low, high = UOM_DECIMALS_RANGE
    if not low <= decimals <= high:
        raise ValueError(f"小数位需在 {low}~{high} 之间")
    return decimals


def create_uom(db: Session, payload: dict) -> Uom:
    code = _s(payload.get("code")).upper()
    name = _s(payload.get("name"))
    if not code:
        raise ValueError("单位编码不能为空")
    if not name:
        raise ValueError("单位名称不能为空")
    if db.query(Uom).filter(or_(Uom.code == code, Uom.name == name)).first() is not None:
        raise ValueError("单位编码或名称已存在")
    obj = Uom(code=code, name=name, decimals=_norm_decimals(payload.get("decimals")),
              enabled=bool(payload.get("enabled", True)), remark=_opt(payload.get("remark")))
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update_uom(db: Session, obj: Uom, payload: dict) -> Uom:
    if "code" in payload and _s(payload.get("code")):
        obj.code = _s(payload.get("code")).upper()
    if "name" in payload:
        name = _s(payload.get("name"))
        if not name:
            raise ValueError("单位名称不能为空")
        obj.name = name
    if "decimals" in payload:
        obj.decimals = _norm_decimals(payload.get("decimals"))
    if "enabled" in payload:
        obj.enabled = bool(payload["enabled"])
    if "remark" in payload:
        obj.remark = _opt(payload.get("remark"))
    dup = db.query(Uom).filter(or_(Uom.code == obj.code, Uom.name == obj.name),
                               Uom.id != obj.id).first()
    if dup is not None:
        raise ValueError("单位编码或名称已存在")
    db.commit()
    db.refresh(obj)
    return obj


def set_uom_enabled(db: Session, obj: Uom, enabled: bool) -> Uom:
    obj.enabled = bool(enabled)
    db.commit()
    db.refresh(obj)
    return obj


def delete_uom(db: Session, obj: Uom) -> None:
    if count_refs(db, "uom", obj.id) > 0:
        raise ValueError("该单位已被物料引用，不能删除，请改为停用")
    db.delete(obj)
    db.commit()


# ==================== 仓库 ====================

def fmt_warehouse(db: Session, obj: Warehouse) -> dict:
    keeper = None
    if obj.keeper_user_id:
        from ..models_auth import User
        user = db.get(User, obj.keeper_user_id)
        keeper = user.real_name if user else None
    return {
        "id": obj.id, "code": obj.code, "name": obj.name, "address": obj.address,
        "keeper_user_id": obj.keeper_user_id, "keeper_name": keeper,
        "enabled": obj.enabled, "remark": obj.remark,
    }


def get_warehouse(db: Session, wh_id: int) -> Warehouse:
    obj = db.get(Warehouse, wh_id)
    if obj is None:
        raise ValueError("仓库不存在")
    return obj


def list_warehouses(db: Session, *, keyword: str | None = None,
                    include_disabled: bool = True) -> dict:
    query = db.query(Warehouse)
    if not include_disabled:
        query = query.filter(Warehouse.enabled == True)  # noqa: E712
    kw = _s(keyword)
    if kw:
        like = f"%{kw}%"
        query = query.filter(or_(Warehouse.name.like(like), Warehouse.code.like(like)))
    rows = query.order_by(Warehouse.id.asc()).all()
    return {"items": [fmt_warehouse(db, w) for w in rows], "total": len(rows)}


def create_warehouse(db: Session, payload: dict) -> Warehouse:
    code = _s(payload.get("code")).upper()
    name = _s(payload.get("name"))
    if not code:
        raise ValueError("仓库编码不能为空")
    if not name:
        raise ValueError("仓库名称不能为空")
    if db.query(Warehouse).filter(or_(Warehouse.code == code, Warehouse.name == name)).first():
        raise ValueError("仓库编码或名称已存在")
    obj = Warehouse(code=code, name=name, address=_opt(payload.get("address")),
                    keeper_user_id=_int_opt(payload.get("keeper_user_id")),
                    enabled=bool(payload.get("enabled", True)),
                    remark=_opt(payload.get("remark")))
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


def update_warehouse(db: Session, obj: Warehouse, payload: dict) -> Warehouse:
    if "code" in payload and _s(payload.get("code")):
        obj.code = _s(payload.get("code")).upper()
    if "name" in payload:
        name = _s(payload.get("name"))
        if not name:
            raise ValueError("仓库名称不能为空")
        obj.name = name
    if "address" in payload:
        obj.address = _opt(payload.get("address"))
    if "keeper_user_id" in payload:
        obj.keeper_user_id = _int_opt(payload.get("keeper_user_id"))
    if "enabled" in payload:
        obj.enabled = bool(payload["enabled"])
    if "remark" in payload:
        obj.remark = _opt(payload.get("remark"))
    dup = db.query(Warehouse).filter(or_(Warehouse.code == obj.code, Warehouse.name == obj.name),
                                     Warehouse.id != obj.id).first()
    if dup is not None:
        raise ValueError("仓库编码或名称已存在")
    db.commit()
    db.refresh(obj)
    return obj


def set_warehouse_enabled(db: Session, obj: Warehouse, enabled: bool) -> Warehouse:
    obj.enabled = bool(enabled)
    db.commit()
    db.refresh(obj)
    return obj


def delete_warehouse(db: Session, obj: Warehouse) -> None:
    if count_refs(db, "warehouse", obj.id) > 0:
        raise ValueError("该仓库已存在库存或单据记录，不能删除，请改为停用")
    db.delete(obj)
    db.commit()


# ==================== 物料 ====================

def fmt_product(db: Session, obj: Product) -> dict:
    return {
        "id": obj.id,
        "code": obj.code,
        "name": obj.name,
        "spec": obj.spec,
        "product_type_id": obj.product_type_id,
        "product_type_name": obj.product_type.name if obj.product_type else None,
        "product_type_code": obj.product_type.code if obj.product_type else None,
        "uom_id": obj.uom_id,
        "uom_name": obj.uom.name if obj.uom else None,
        "uom_decimals": obj.uom.decimals if obj.uom else None,
        "brand": obj.brand,
        "barcode": obj.barcode,
        "default_price": float(obj.default_price) if obj.default_price is not None else None,
        "safety_stock": float(obj.safety_stock) if obj.safety_stock is not None else None,
        "status": obj.status,
        "remark": obj.remark,
        "created_at": obj.created_at.isoformat() if obj.created_at else None,
        "updated_at": obj.updated_at.isoformat() if obj.updated_at else None,
    }


def get_product(db: Session, product_id: int) -> Product:
    obj = db.get(Product, product_id)
    if obj is None:
        raise ValueError("物料不存在")
    return obj


def list_products(db: Session, *, keyword: str | None = None, product_type_id: int | None = None,
                  status: str | None = None, page: int = 1, page_size: int = 20) -> dict:
    query = db.query(Product)
    if product_type_id:
        # 选中父类型时连同其下级一起过滤（物化路径前缀）
        node = db.get(ProductType, product_type_id)
        if node is None:
            raise ValueError("商品类型不存在")
        ids = [r[0] for r in db.query(ProductType.id)
               .filter(ProductType.path.like(f"{node.path}%")).all()] or [node.id]
        query = query.filter(Product.product_type_id.in_(ids))
    if status:
        query = query.filter(Product.status == status)
    kw = _s(keyword)
    if kw:
        like = f"%{kw}%"
        query = query.filter(or_(Product.name.like(like), Product.code.like(like),
                                 Product.spec.like(like), Product.brand.like(like),
                                 Product.barcode.like(like)))
    query = query.order_by(Product.id.desc())
    rows, total, page, page_size = _paginate(query, page, page_size)
    return _page_payload([fmt_product(db, r) for r in rows], total, page, page_size)


def _apply_product_fields(db: Session, obj: Product, payload: dict) -> None:
    if "name" in payload:
        name = _s(payload.get("name"))
        if not name:
            raise ValueError("物料名称不能为空")
        if len(name) > 128:
            raise ValueError("物料名称最多 128 字")
        obj.name = name
    for field in ("spec", "brand", "barcode", "remark"):
        if field in payload:
            setattr(obj, field, _opt(payload.get(field)))
    if "product_type_id" in payload:
        obj.product_type_id = assert_leaf_enabled(db, int(payload.get("product_type_id") or 0)).id
    if "uom_id" in payload:
        uom = get_uom(db, int(payload.get("uom_id") or 0))
        if not uom.enabled:
            raise ValueError(f"计量单位「{uom.name}」已停用")
        obj.uom_id = uom.id
    if "default_price" in payload:
        price = _dec(payload.get("default_price"), "默认单价", Decimal("0"))
        if price is not None and price < 0:
            raise ValueError("默认单价不能为负数")
        obj.default_price = price if price is not None else Decimal("0")
    if "safety_stock" in payload:
        stock = _dec(payload.get("safety_stock"), "安全库存")
        if stock is not None and stock < 0:
            raise ValueError("安全库存不能为负数")
        obj.safety_stock = stock
    if "status" in payload:
        obj.status = "enabled" if payload.get("status") == "enabled" else "disabled"


def create_product(db: Session, payload: dict, user=None) -> Product:
    if not _s(payload.get("name")):
        raise ValueError("物料名称不能为空")
    if payload.get("product_type_id") in (None, ""):
        raise ValueError("请选择商品类型")
    if payload.get("uom_id") in (None, ""):
        raise ValueError("请选择计量单位")
    type_id = int(payload.get("product_type_id"))

    def _build():
        ptype = assert_leaf_enabled(db, type_id)
        code = _s(payload.get("code")).upper() or numbering_service.next_product_code(db, ptype)
        if db.query(Product).filter(Product.code == code).first() is not None:
            raise ValueError(f"物料编码已存在：{code}")
        obj = Product(code=code, name=_s(payload.get("name")), status="enabled",
                      product_type_id=ptype.id, uom_id=int(payload.get("uom_id")),
                      created_by=getattr(user, "id", None))
        _apply_product_fields(db, obj, payload)
        db.add(obj)
        db.commit()
        db.refresh(obj)
        return obj

    return numbering_service.retry_on_conflict(db, _build)


def update_product(db: Session, obj: Product, payload: dict) -> Product:
    if "code" in payload and _s(payload.get("code")):
        code = _s(payload.get("code")).upper()
        dup = db.query(Product).filter(Product.code == code, Product.id != obj.id).first()
        if dup is not None:
            raise ValueError(f"物料编码已存在：{code}")
        obj.code = code
    _apply_product_fields(db, obj, payload)
    db.commit()
    db.refresh(obj)
    return obj


def set_product_status(db: Session, obj: Product, enabled: bool) -> Product:
    obj.status = "enabled" if enabled else "disabled"
    db.commit()
    db.refresh(obj)
    return obj


def delete_product(db: Session, obj: Product) -> None:
    if count_refs(db, "product", obj.id) > 0:
        raise ValueError("该物料已存在库存或单据记录，不能删除，请改为停用")
    db.delete(obj)
    db.commit()


def product_options(db: Session, keyword: str | None = None, product_type_id: int | None = None,
                    limit: int = 50) -> list[dict]:
    """轻量下拉数据（单据行项选择物料用）：仅启用物料。"""
    data = list_products(db, keyword=keyword, product_type_id=product_type_id,
                         status="enabled", page=1, page_size=limit)
    return [{"id": i["id"], "code": i["code"], "name": i["name"], "spec": i["spec"],
             "uom_id": i["uom_id"], "uom_name": i["uom_name"],
             "uom_decimals": i["uom_decimals"], "default_price": i["default_price"],
             "safety_stock": i["safety_stock"], "product_type_name": i["product_type_name"]}
            for i in data["items"]]


def warehouse_options(db: Session, keyword: str | None = None, limit: int = 50) -> list[dict]:
    query = db.query(Warehouse).filter(Warehouse.enabled == True)  # noqa: E712
    kw = _s(keyword)
    if kw:
        like = f"%{kw}%"
        query = query.filter(or_(Warehouse.name.like(like), Warehouse.code.like(like)))
    rows = query.order_by(Warehouse.id.asc()).limit(max(1, min(200, limit))).all()
    return [{"id": w.id, "code": w.code, "name": w.name} for w in rows]


def uom_options(db: Session, limit: int = 200) -> list[dict]:
    rows = db.query(Uom).filter(Uom.enabled == True).order_by(Uom.id.asc()).limit(limit).all()  # noqa: E712
    return [{"id": u.id, "code": u.code, "name": u.name, "decimals": u.decimals} for u in rows]


def org_options(db: Session, keyword: str | None = None, limit: int = 200) -> list[dict]:
    """组织节点下拉（部门选择用；登录即可，供单据表单选择申请/采购部门）。"""
    from ..models_auth import OrgUnit

    query = db.query(OrgUnit).filter(OrgUnit.enabled == True)  # noqa: E712
    kw = _s(keyword)
    if kw:
        like = f"%{kw}%"
        query = query.filter(or_(OrgUnit.name.like(like), OrgUnit.code.like(like)))
    rows = query.order_by(OrgUnit.path.asc()).limit(max(1, min(500, limit))).all()
    return [{"id": o.id, "name": o.name, "code": o.code, "path": o.path,
             "level": o.level, "unit_type": o.unit_type} for o in rows]


def options(db: Session, kind: str, keyword: str | None = None,
            product_type_id: int | None = None) -> list[dict]:
    """`/api/master/options/{kind}` 统一入口。"""
    kind = (kind or "").strip().lower()
    if kind in ("customer", "customers"):
        return party_options(db, "customer", keyword)
    if kind in ("supplier", "suppliers"):
        return party_options(db, "supplier", keyword)
    if kind in ("product", "products"):
        return product_options(db, keyword, product_type_id)
    if kind in ("product-type", "product_type", "product-types"):
        return product_type_options(db, keyword)
    if kind in ("uom", "uoms"):
        return uom_options(db)
    if kind in ("org", "orgs", "org-unit", "org-units", "department", "dept"):
        return org_options(db, keyword)
    if kind in ("warehouse", "warehouses"):
        return warehouse_options(db, keyword)
    raise ValueError(f"未知下拉类别：{kind}")


def meta(db: Session) -> dict:
    """主数据页面所需枚举。"""
    return {
        "party_statuses": PARTY_STATUSES,
        "customer_levels": CUSTOMER_LEVELS,
        "uom_decimals_range": list(UOM_DECIMALS_RANGE),
        "max_type_level": MAX_TYPE_LEVEL,
        "product_statuses": PARTY_STATUSES,
    }


# 供路由复用的引用统计（T-V2-16 回归与前端提示用）
def usage_of(db: Session, kind: str, obj_id: int) -> int:
    return count_refs(db, kind, obj_id)


# 兼容：合同模块引用校验用（避免路由层重复实现）
def contract_party_refs(db: Session, kind: str, obj_id: int) -> int:
    column = Contract.customer_id if kind == "customer" else Contract.supplier_id
    return int(db.query(Contract).filter(column == obj_id).count() or 0)
