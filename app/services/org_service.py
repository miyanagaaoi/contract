"""组织架构服务（T-V2-03）：树维护、层级路径与删除校验。

物化路径约定（见 `12-erp-system-design.md` §3.5）：
- 顶级节点 `path = "/1/"`；子节点 `"/1/5/"`；孙节点 `"/1/5/12/"`
- "本部门及下级"的数据范围查询 = `path LIKE '/1/5/%'`（含自身）
  → 由 `permission_service.descendant_org_ids()` 使用

业务约束（PRD BR-V2-10）：
- 删除前必须**无下级且无归属账号**，否则只能停用；
- 最多 5 级；不能把节点移动到自己的下级（防环）。
"""
from __future__ import annotations

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models_auth import OrgUnit, User

UNIT_TYPES = ["公司", "部门", "岗位"]
MAX_LEVEL = 5


# ---------- 查询 ----------

def get_unit(db: Session, unit_id: int) -> OrgUnit:
    node = db.get(OrgUnit, unit_id)
    if node is None:
        raise ValueError("组织节点不存在")
    return node


def _count_users(db: Session, unit_id: int) -> int:
    return int(db.query(func.count(User.id)).filter(User.org_id == unit_id).scalar() or 0)


def _fmt(node: OrgUnit, user_count: int = 0) -> dict:
    return {
        "id": node.id,
        "parent_id": node.parent_id,
        "name": node.name,
        "code": node.code,
        "unit_type": node.unit_type,
        "leader_user_id": node.leader_user_id,
        "phone": node.phone,
        "path": node.path,
        "level": node.level,
        "sort": node.sort,
        "enabled": node.enabled,
        "user_count": user_count,
    }


def fmt_unit(db: Session, node: OrgUnit) -> dict:
    return _fmt(node, _count_users(db, node.id))


def build_tree(items: list[dict]) -> list[dict]:
    """扁平节点 → 嵌套树；父节点不在集合中时（如关键字过滤后）作为根节点。"""
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


def list_units(db: Session, keyword: str | None = None,
               include_disabled: bool = True) -> dict:
    query = db.query(OrgUnit)
    if not include_disabled:
        query = query.filter(OrgUnit.enabled == True)  # noqa: E712
    nodes = query.order_by(OrgUnit.sort.asc(), OrgUnit.id.asc()).all()

    counts = dict(db.query(User.org_id, func.count(User.id)).group_by(User.org_id).all())
    items = [_fmt(n, counts.get(n.id, 0)) for n in nodes]

    if keyword:
        kw = keyword.strip()
        if kw:
            items = [i for i in items
                     if kw in i["name"] or (i["code"] and kw in i["code"])]

    return {"items": items, "tree": build_tree(items), "total": len(items)}


# ---------- 校验 ----------

def _norm_name(value) -> str:
    name = str(value or "").strip()
    if not name:
        raise ValueError("节点名称不能为空")
    if len(name) > 64:
        raise ValueError("节点名称最多 64 字")
    return name


def _norm_type(value) -> str:
    unit_type = str(value or "").strip() or "部门"
    if unit_type not in UNIT_TYPES:
        raise ValueError(f"节点类型只能是：{' / '.join(UNIT_TYPES)}")
    return unit_type


def _norm_parent_id(value) -> int | None:
    if value in (None, "", 0, "0"):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError("上级节点非法")


def _assert_sibling_name_unique(db: Session, parent_id: int | None, name: str,
                                exclude_id: int | None = None) -> None:
    query = db.query(OrgUnit).filter(OrgUnit.parent_id == parent_id, OrgUnit.name == name)
    if exclude_id:
        query = query.filter(OrgUnit.id != exclude_id)
    if query.first() is not None:
        raise ValueError("同级下已存在同名节点")


def _apply_path(db: Session, node: OrgUnit, new_parent_id: int | None) -> None:
    """设置或重算自身与全部子孙的 `path` / `level`。

    `node.path` 为空字符串表示**新建**（此时不进入子孙重算分支）。
    """
    old_prefix = node.path or ""
    parent = db.get(OrgUnit, new_parent_id) if new_parent_id else None
    if new_parent_id and parent is None:
        raise ValueError("上级节点不存在")

    base = parent.path if parent else "/"
    new_prefix = f"{base}{node.id}/"
    new_level = new_prefix.count("/") - 1
    if new_level > MAX_LEVEL:
        raise ValueError(f"组织层级最多 {MAX_LEVEL} 级")
    if parent is not None and old_prefix and parent.path.startswith(old_prefix):
        raise ValueError("不能把节点移动到它自己的下级")

    if old_prefix and old_prefix != new_prefix:
        # 移动节点：整棵子树换前缀
        descendants = db.query(OrgUnit).filter(OrgUnit.path.like(old_prefix + "%")).all()
        for child in descendants:
            child.path = new_prefix + child.path[len(old_prefix):]
            child.level = child.path.count("/") - 1
    else:
        node.path = new_prefix
        node.level = new_level
    node.parent_id = new_parent_id


# ---------- 写操作 ----------

def create_unit(db: Session, payload: dict) -> OrgUnit:
    name = _norm_name(payload.get("name"))
    unit_type = _norm_type(payload.get("unit_type"))
    parent_id = _norm_parent_id(payload.get("parent_id"))

    if parent_id is not None:
        parent = db.get(OrgUnit, parent_id)
        if parent is None:
            raise ValueError("上级节点不存在")
        if parent.level >= MAX_LEVEL:
            raise ValueError(f"组织层级最多 {MAX_LEVEL} 级")
    _assert_sibling_name_unique(db, parent_id, name)

    node = OrgUnit(
        parent_id=parent_id,
        name=name,
        unit_type=unit_type,
        code=(str(payload.get("code") or "").strip() or None),
        phone=(str(payload.get("phone") or "").strip() or None),
        leader_user_id=(payload.get("leader_user_id") or None),
        sort=int(payload.get("sort") or 0),
        enabled=bool(payload.get("enabled", True)),
        path="",          # 由 _apply_path 计算
        level=1,
    )
    db.add(node)
    db.flush()            # 先取 id，才能算 path
    _apply_path(db, node, parent_id)
    db.commit()
    return node


def update_unit(db: Session, node: OrgUnit, payload: dict) -> OrgUnit:
    new_parent_id = node.parent_id
    if "parent_id" in payload:
        new_parent_id = _norm_parent_id(payload.get("parent_id"))

    if "name" in payload:
        node.name = _norm_name(payload["name"])
    if "unit_type" in payload:
        node.unit_type = _norm_type(payload["unit_type"])
    if "code" in payload:
        node.code = str(payload.get("code") or "").strip() or None
    if "phone" in payload:
        node.phone = str(payload.get("phone") or "").strip() or None
    if "leader_user_id" in payload:
        node.leader_user_id = payload.get("leader_user_id") or None
    if "sort" in payload:
        node.sort = int(payload.get("sort") or 0)
    if "enabled" in payload:
        node.enabled = bool(payload["enabled"])

    if new_parent_id != node.parent_id:
        if new_parent_id is not None:
            parent = db.get(OrgUnit, new_parent_id)
            if parent is None:
                raise ValueError("上级节点不存在")
            if parent.level >= MAX_LEVEL:
                raise ValueError(f"组织层级最多 {MAX_LEVEL} 级")
        _apply_path(db, node, new_parent_id)

    _assert_sibling_name_unique(db, node.parent_id, node.name, exclude_id=node.id)
    db.commit()
    return node


def set_enabled(db: Session, node: OrgUnit, enabled: bool) -> OrgUnit:
    node.enabled = bool(enabled)
    db.commit()
    return node


def delete_unit(db: Session, node: OrgUnit) -> None:
    if db.query(OrgUnit.id).filter(OrgUnit.parent_id == node.id).first() is not None:
        raise ValueError("该节点下存在子节点，请先处理子节点，或改为停用")
    if db.query(User.id).filter(User.org_id == node.id).first() is not None:
        raise ValueError("该节点下存在账号，不能删除，请改为停用")
    db.delete(node)
    db.commit()
