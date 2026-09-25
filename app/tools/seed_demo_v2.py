"""V2.0 UAT / 演示数据一键初始化（幂等）。

用途：让三类用户拿到一套"可立刻点验"的环境，覆盖 UAT 清单（`docs/17-uat-plan.md` §4）所需的
组织、账号（8 类内置角色）、主数据（客户/供应商/商品类型/单位/物料/仓库）与演示合同。

用法：
    app\\.venv\\Scripts\\python.exe app\\tools\\seed_demo_v2.py                 # 账号首次登录需改密（推荐）
    app\\.venv\\Scripts\\python.exe app\\tools\\seed_demo_v2.py --no-force-change # 演示用：不强制改密

幂等：全部按"不存在才创建"处理，重复执行安全；不会覆盖或删除既有数据。
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import Session  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.dicts import DEFAULT_CONTRACT_TYPES, DEFAULT_SUBJECTS, get_enabled_contract_types  # noqa: E402
from app.init_db import seed_auth, seed_dicts  # noqa: E402
from app.models import Contract, Tag  # noqa: E402
from app.models_auth import OrgUnit, Role, User  # noqa: E402
from app.models_master import Customer, Product, ProductType, Supplier, Uom, Warehouse  # noqa: E402
from app.security import hash_password  # noqa: E402

DEMO_PASSWORD = "ctms2026"          # 满足默认密码最小长度 8 且含字母与数字

# 演示账号：(登录名, 姓名, 角色 code, 所属部门名)
DEMO_USERS: list[tuple[str, str, str, str]] = [
    ("pm01", "采购主管·王采购", "purchase_manager", "采购部"),
    ("buyer01", "采购员·李小采", "buyer", "采购部"),
    ("sm01", "销售主管·赵销售", "sales_manager", "销售部"),
    ("seller01", "销售员·钱小售", "seller", "销售部"),
    ("wh01", "仓管员·孙小仓", "keeper", "仓储部"),
    ("fin01", "财务·周小财", "finance", "财务部"),
    ("view01", "管理层·吴总", "viewer", "总经办"),
]

# 组织：总公司 → 各部门
DEPARTMENTS = ["采购部", "销售部", "仓储部", "财务部", "总经办"]

# 商品类型：父类型 → 叶子（叶子类型带 code，物料编码即"叶子码 + 4 位序号"，便于演示 AC-V2-10）
PRODUCT_TYPES: list[tuple[str, str | None, str | None]] = [
    ("原材料", "RAW", None),
    ("钢材", "STL", "原材料"),
    ("办公用品", "OFF", None),
    ("纸张", "PPR", "办公用品"),
    ("设备", "EQP", None),
    ("检测设备", "DET", "设备"),
]

UOMS: list[tuple[str, str, int]] = [("PCS", "个", 0), ("KG", "千克", 3), ("BOX", "箱", 0), ("SET", "套", 0)]

PRODUCTS: list[tuple[str, str, str, str, float, float | None]] = [
    # (名称, 规格, 叶子类型, 单位, 默认单价, 安全库存)
    ("热轧钢板", "Q235 3mm", "钢材", "KG", 5.2, 500),
    ("A4 复印纸", "70g 500张/包", "纸张", "BOX", 128.0, 20),
    ("便携式测厚仪", "TT-100", "检测设备", "SET", 3600.0, 2),
]

WAREHOUSES: list[tuple[str, str]] = [("WH01", "主仓"), ("WH02", "备件仓")]
CUSTOMERS: list[tuple[str, str]] = [("华东机械制造有限公司", "华东机械"), ("南方电子科技股份有限公司", "南方电子")]
SUPPLIERS: list[tuple[str, str]] = [("宝钢金属材料有限公司", "宝钢金属"), ("晨光文具有限公司", "晨光文具")]

SUMMARY: dict[str, list[str]] = {k: [] for k in
                                 ("orgs", "users", "types", "uoms", "products", "warehouses",
                                  "customers", "suppliers", "contracts", "skipped")}


def _get_or_create_org(db: Session, name: str, parent: OrgUnit | None, unit_type: str = "部门") -> OrgUnit:
    node = db.query(OrgUnit).filter(OrgUnit.name == name,
                                    OrgUnit.parent_id == (parent.id if parent else None)).first()
    if node is not None:
        SUMMARY["skipped"].append(f"组织 {name}")
        return node
    node = OrgUnit(name=name, parent_id=parent.id if parent else None, unit_type=unit_type, path="", level=1)
    db.add(node)
    db.flush()
    base = parent.path if parent else "/"
    node.path = f"{base}{node.id}/"
    node.level = node.path.count("/") - 1
    SUMMARY["orgs"].append(name)
    return node


def _get_or_create_user(db: Session, username: str, real_name: str, role_code: str,
                        org: OrgUnit | None, force_change: bool) -> User | None:
    role = db.query(Role).filter(Role.code == role_code).first()
    if role is None:
        print(f"  [WARN] 角色 {role_code} 不存在，跳过账号 {username}")
        return None
    existing = db.query(User).filter(User.username == username).first()
    if existing is not None:
        SUMMARY["skipped"].append(f"账号 {username}")
        return existing
    user = User(username=username, real_name=real_name,
                password_hash=hash_password(DEMO_PASSWORD), status="enabled",
                org_id=org.id if org else None, must_change_pwd=force_change,
                remark="演示/验收账号（seed_demo_v2 创建）")
    user.roles.append(role)
    db.add(user)
    db.flush()
    SUMMARY["users"].append(f"{username}（{real_name}·{role.name}）")
    return user


def _get_or_create_type(db: Session, name: str, code: str | None, parent_name: str | None) -> ProductType:
    parent = None
    if parent_name:
        parent = db.query(ProductType).filter(ProductType.name == parent_name).first()
    existing = db.query(ProductType).filter(ProductType.name == name).first()
    if existing is not None:
        SUMMARY["skipped"].append(f"商品类型 {name}")
        return existing
    node = ProductType(name=name, code=code, parent_id=parent.id if parent else None, path="", level=1)
    db.add(node)
    db.flush()
    base = parent.path if parent else "/"
    node.path = f"{base}{node.id}/"
    node.level = node.path.count("/") - 1
    SUMMARY["types"].append(name)
    return node


def _get_or_create_uom(db: Session, code: str, name: str, decimals: int) -> Uom:
    existing = db.query(Uom).filter(Uom.code == code).first()
    if existing is not None:
        SUMMARY["skipped"].append(f"单位 {code}")
        return existing
    uom = Uom(code=code, name=name, decimals=decimals)
    db.add(uom)
    db.flush()
    SUMMARY["uoms"].append(f"{code}/{name}")
    return uom


def _get_or_create_warehouse(db: Session, code: str, name: str) -> Warehouse:
    existing = db.query(Warehouse).filter(Warehouse.code == code).first()
    if existing is not None:
        SUMMARY["skipped"].append(f"仓库 {code}")
        return existing
    wh = Warehouse(code=code, name=name)
    db.add(wh)
    db.flush()
    SUMMARY["warehouses"].append(f"{code}/{name}")
    return wh


def _get_or_create_party(db: Session, model, name: str, short: str, kind: str) -> object:
    existing = db.query(model).filter(model.name == name).first()
    if existing is not None:
        SUMMARY["skipped"].append(f"{kind} {name}")
        return existing
    prefix = "CUS" if kind == "客户" else "SUP"
    seq = db.query(model).count() + 1
    obj = model(code=f"{prefix}{seq:04d}", name=name, short_name=short)
    db.add(obj)
    db.flush()
    SUMMARY[kind == "客户" and "customers" or "suppliers"].append(name)
    return obj


def _get_or_create_product(db: Session, name: str, spec: str, type_name: str, uom_code: str,
                           price: float, safety: float | None) -> Product:
    existing = db.query(Product).filter(Product.name == name).first()
    if existing is not None:
        SUMMARY["skipped"].append(f"物料 {name}")
        return existing
    ptype = db.query(ProductType).filter(ProductType.name == type_name).first()
    uom = db.query(Uom).filter(Uom.code == uom_code).first()
    assert ptype is not None and uom is not None, f"物料 {name} 的类型或单位缺失"
    prefix = ptype.code or f"PT{ptype.id}"
    same = db.query(Product).filter(Product.code.like(f"{prefix}%")).count()
    product = Product(code=f"{prefix}{same + 1:04d}", name=name, spec=spec,
                      product_type_id=ptype.id, uom_id=uom.id,
                      default_price=Decimal(str(price)),
                      safety_stock=Decimal(str(safety)) if safety is not None else None)
    db.add(product)
    db.flush()
    SUMMARY["products"].append(f"{product.code} {name}")
    return product


def _ensure_contracts(db: Session, depts: dict[str, OrgUnit],
                      users: dict[str, User]) -> None:
    """演示合同：按方向归属组织（采购→采购部、销售→销售部）并记录创建人。

    这一点很关键：数据范围（本人/本部门及下级）按 `org_id` + `created_by` 过滤，
    若不设置，业务账号登录后看不到演示合同（AC-V2-04/05 的演示就会失败）。
    """
    tags = {t.name: t for t in db.query(Tag).all()}
    subject = DEFAULT_SUBJECTS[0]["code"]
    types = {t["code"]: t["label"] for t in get_enabled_contract_types(db)}
    today = date.today()

    def add(contract_no: str, name: str, type_code: str, party_a: str, party_b: str,
            amount: float, paid: float, status: str, *, is_framework: bool = False,
            owner: str = "pm01", warranty: bool = False, arrival: str = "未到货") -> Contract | None:
        org = depts.get("采购部") if type_code == "PUR" else depts.get("销售部")
        creator = users.get(owner)
        existing = db.query(Contract).filter(Contract.contract_no == contract_no).first()
        if existing is not None:
            # 幂等补齐：早期版本创建的演示合同可能没有归属组织，导致业务账号看不到
            if existing.org_id is None and org is not None:
                existing.org_id = org.id
                existing.created_by = creator.id if creator else None
                SUMMARY["contracts"].append(f"{contract_no}（补齐归属：{org.name}）")
            else:
                SUMMARY["skipped"].append(f"合同 {contract_no}")
            return existing
        contract = Contract(
            contract_no=contract_no, name=name, type=types.get(type_code, type_code),
            party_a=party_a, party_b=party_b, subject_code=subject,
            sign_date=today - timedelta(days=60), amount=Decimal(str(amount)),
            paid_amount=Decimal(str(paid)), status=status, is_framework=is_framework,
            has_warranty=warranty, arrival_status=arrival,
            owner_name=(creator.real_name if creator else "王采购"),
            org_id=org.id if org else None,
            created_by=creator.id if creator else None,
        )
        if warranty:
            contract.warranty_rate = Decimal("5")
            contract.warranty_amount = (Decimal(str(amount)) * Decimal("5") / Decimal("100"))
            contract.warranty_start = today - timedelta(days=20)
            contract.warranty_months = 12
            from app.models import compute_warranty_end

            contract.warranty_end = compute_warranty_end(contract.warranty_start, 12)
        contract.tags = [t for t in (tags.get("采购"),) if t]
        db.add(contract)
        db.flush()
        SUMMARY["contracts"].append(f"{contract_no} {name}")
        return contract

    framework = add("F-DEMO-2026-001", "2026 年度钢材框架采购合同", "PUR", "智澈公司",
                    "宝钢金属材料有限公司", 500000, 0, "已签订", is_framework=True)
    sub = add("PUR-DEMO-2026-001", "一期钢板采购（框架下）", "PUR", "智澈公司",
              "宝钢金属材料有限公司", 120000, 60000, "付款中", warranty=True, arrival="部分到货")
    if sub is not None and sub.parent_id is None and framework is not None:
        sub.parent_id = framework.id
    add("PUR-DEMO-2026-002", "办公耗材年度采购", "PUR", "智澈公司", "晨光文具有限公司",
        30000, 30000, "到货", arrival="已到货")
    add("SAL-DEMO-2026-001", "华东机械设备销售合同", "SAL", "华东机械制造有限公司", "智澈公司",
        86000, 20000, "付款中", owner="sm01", warranty=True, arrival="已到货")


def main() -> int:
    parser = argparse.ArgumentParser(description="V2.0 UAT/演示数据初始化（幂等）")
    parser.add_argument("--no-force-change", action="store_true",
                        help="账号首次登录不强制改密（演示用；默认强制改密）")
    args = parser.parse_args()
    force_change = not args.no_force_change

    Base.metadata.create_all(bind=engine)
    import app.models_auth  # noqa: F401
    import app.models_doc  # noqa: F401
    import app.models_master  # noqa: F401
    import app.models_stock  # noqa: F401
    from app.db_migrate import ensure_schema_upgrades

    Base.metadata.create_all(bind=engine)
    ensure_schema_upgrades()

    with SessionLocal() as db:
        seed_dicts(db)
        auth = seed_auth(db)          # 内置角色 + 超管 + 系统参数
        company = _get_or_create_org(db, "智澈公司（演示）", None, unit_type="公司")
        depts = {name: _get_or_create_org(db, name, company) for name in DEPARTMENTS}
        db.commit()

        users: dict[str, User] = {}
        for username, real_name, role_code, dept in DEMO_USERS:
            created = _get_or_create_user(db, username, real_name, role_code,
                                          depts.get(dept), force_change)
            if created is not None:
                users[username] = created
        db.commit()

        for name, code, parent in PRODUCT_TYPES:
            _get_or_create_type(db, name, code, parent)
        for code, name, decimals in UOMS:
            _get_or_create_uom(db, code, name, decimals)
        for code, name in WAREHOUSES:
            _get_or_create_warehouse(db, code, name)
        db.commit()

        for name, short in CUSTOMERS:
            _get_or_create_party(db, Customer, name, short, "客户")
        for name, short in SUPPLIERS:
            _get_or_create_party(db, Supplier, name, short, "供应商")
        db.commit()

        for name, spec, type_name, uom_code, price, safety in PRODUCTS:
            _get_or_create_product(db, name, spec, type_name, uom_code, price, safety)
        db.commit()

        _ensure_contracts(db, depts, users)
        db.commit()

    print("\n===== V2.0 演示数据初始化完成 =====")
    for key, label in (("orgs", "新增组织"), ("users", "新增账号"), ("types", "新增商品类型"),
                       ("uoms", "新增计量单位"), ("products", "新增物料"), ("warehouses", "新增仓库"),
                       ("customers", "新增客户"), ("suppliers", "新增供应商"),
                       ("contracts", "新增合同")):
        values = SUMMARY[key]
        print(f"{label}（{len(values)}）：{'、'.join(values) if values else '—'}")
    print(f"跳过（已存在）：{len(SUMMARY['skipped'])} 项")
    print("\n登录信息：")
    print(f"  管理员：admin / {'admin12345' if auth.get('admin_created') else '（沿用既有密码）'}")
    print(f"  业务账号：{', '.join(u.split('（')[0] for u in SUMMARY['users']) or '（本次未新建）'}"
          f" / 密码 {DEMO_PASSWORD}")
    if force_change:
        print("  提示：业务账号首次登录需改密（如需免改密，加 --no-force-change 重新执行不会覆盖密码，"
              "请改用管理员重置密码）")
    print("  角色对应：pm01 采购主管、buyer01 采购员、sm01 销售主管、seller01 销售员、"
          "wh01 仓管员、fin01 财务、view01 管理层")
    print("\n提示：本脚本只新增、不删除。若当前库中已有历史测试数据（名称带随机后缀的物料/类型/单据），"
          "正式演示建议使用全新库：停服 → 备份并移走 app/data/ctms.db → 重跑 init_db 与本脚本。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
