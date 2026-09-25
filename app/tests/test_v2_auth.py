"""T-V2-01 / T-V2-02 自动化测试：安全基础、权限清单、系统参数、权限种子。

覆盖对应 PRD 条目：
- BR-V2-08 权限三层（清单/菜单裁剪/数据范围取最宽）
- BR-V2-09/10 角色与账号唯一性、内置角色
- BR-V2-11 密码策略与哈希存储
- §3.1 令牌签发/校验/过期/防篡改
- §4.6 系统参数与编号规则字典

运行：app\\.venv\\Scripts\\python -m pytest app\\tests -q
"""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app import models, models_auth  # noqa: F401  导入以注册全部表
from app.database import Base
from app.dicts import (
    DEFAULT_NUMBER_RULES,
    DEFAULT_SYS_PARAMS,
    get_number_rules,
    get_sys_params,
    set_number_rules,
    set_sys_params,
)
from app.permissions import (
    DATA_SCOPE_CODES,
    MENUS,
    PERM_CODES,
    ROLE_PRESETS,
    expand_perms,
    menu_tree_for,
    perm_tree,
    widest_scope,
)
from app.security import (
    TokenError,
    check_password_strength,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)


@pytest.fixture()
def db():
    """独立内存库：每个用例一套干净表结构。"""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()


# ===================== 密码 =====================

class TestPassword:
    def test_hash_roundtrip(self):
        stored = hash_password("abc12345")
        assert stored.startswith("pbkdf2_sha256$")
        assert verify_password("abc12345", stored) is True
        assert verify_password("abc12346", stored) is False

    def test_same_password_different_hash(self):
        # 每次使用随机盐 → 相同明文不得产生相同哈希
        assert hash_password("abc12345") != hash_password("abc12345")

    def test_verify_rejects_garbage(self):
        assert verify_password("x", "") is False
        assert verify_password("x", "not-a-hash") is False
        assert verify_password("x", "md5$1$aaa$bbb") is False

    def test_strength_rules(self):
        assert check_password_strength("abc12345") is None
        assert "长度" in check_password_strength("abc1")
        assert "字母与数字" in check_password_strength("abcdefgh")
        assert "字母与数字" in check_password_strength("12345678")


# ===================== JWT =====================

class TestToken:
    def test_roundtrip(self):
        token, exp = create_token(user_id=7, username="buyer01", real_name="张三", org_id=3)
        payload = decode_token(token)
        assert payload["sub"] == "7"
        assert payload["username"] == "buyer01"
        assert payload["name"] == "张三"
        assert payload["org_id"] == 3
        assert exp > payload["iat"]

    def test_rejects_tampered_signature(self):
        token, _ = create_token(user_id=1, username="u", real_name="n")
        head, body, sig = token.split(".")
        with pytest.raises(TokenError):
            decode_token(f"{head}.{body}.{sig[:-2]}xy")

    def test_rejects_tampered_payload(self):
        token, _ = create_token(user_id=1, username="u", real_name="n")
        head, body, sig = token.split(".")
        with pytest.raises(TokenError):
            decode_token(f"{head}.{body[:-2]}AA.{sig}")

    def test_rejects_expired(self):
        token, _ = create_token(user_id=1, username="u", real_name="n", hours=-1)
        with pytest.raises(TokenError) as err:
            decode_token(token)
        assert "过期" in str(err.value)

    def test_rejects_malformed(self):
        for bad in ("", "abc", "a.b", "a.b.c.d"):
            with pytest.raises(TokenError):
                decode_token(bad)


# ===================== 权限清单 =====================

class TestPermissions:
    def test_expand_wildcard_module(self):
        codes = expand_perms(["purchase.*"])
        assert codes, "purchase.* 应展开出权限点"
        assert all(c.startswith("purchase.") for c in codes)
        assert "purchase.order.approve" in codes
        assert "purchase.request.create" in codes

    def test_expand_star_returns_all(self):
        assert set(expand_perms(["*"])) == PERM_CODES

    def test_expand_ignores_unknown_and_empty(self):
        assert expand_perms(["no.such.perm"]) == []
        assert expand_perms(None) == []
        assert expand_perms([]) == []

    def test_expand_keeps_definition_order(self):
        assert expand_perms(["contract.view", "dashboard.view"]) == ["dashboard.view", "contract.view"]

    def test_widest_scope(self):
        assert widest_scope(["SELF", "DEPT_SUB"]) == "DEPT_SUB"
        assert widest_scope(["ALL", "SELF"]) == "ALL"
        assert widest_scope([]) == "SELF"
        assert widest_scope(["BOGUS"]) == "SELF"

    def test_menu_filter_by_perm(self):
        assert [n["key"] for n in menu_tree_for({"dashboard.view"})] == ["dashboard"]

    def test_menu_keeps_parent_of_visible_child(self):
        # 只有采购单查看权限时：父菜单「采购管理」保留，且只含采购单子项
        tree = menu_tree_for({"purchase.order.view"})
        purchase = next(n for n in tree if n["key"] == "purchase")
        assert [c["key"] for c in purchase["children"]] == ["purchase-order"]

    def test_menu_nested_three_levels(self):
        # 基础信息下的三级菜单可按权限裁剪
        tree = menu_tree_for({"master.uom.view"})
        master = next(n for n in tree if n["key"] == "master")
        base = next(c for c in master["children"] if c["key"] == "m-base")
        assert [c["key"] for c in base["children"]] == ["m-uom"]

    def test_menu_superadmin_returns_all(self):
        assert menu_tree_for(set(), is_superadmin=True) == MENUS

    def test_perm_tree_is_complete(self):
        tree = perm_tree()
        modules = {g["module"] for g in tree}
        assert {"dashboard", "contract", "purchase", "sales", "stock", "master", "system"} <= modules
        assert sum(len(g["perms"]) for g in tree) == len(PERM_CODES)

    def test_role_presets_are_valid(self):
        codes = {p["code"] for p in ROLE_PRESETS}
        assert codes == {"sysadmin", "purchase_manager", "buyer", "sales_manager",
                         "seller", "keeper", "finance", "viewer"}
        for preset in ROLE_PRESETS:
            assert preset["data_scope"] in DATA_SCOPE_CODES, preset["code"]
            expanded = expand_perms(preset["perms"])
            assert expanded, preset["code"]
            assert set(expanded) <= PERM_CODES

    def test_role_presets_do_not_let_buyer_approve(self):
        # 权限矩阵关键约束：采购员不可审核（11 §3.4）
        buyer = next(p for p in ROLE_PRESETS if p["code"] == "buyer")
        codes = set(expand_perms(buyer["perms"]))
        assert "purchase.order.submit" in codes
        assert "purchase.order.approve" not in codes

    def test_role_presets_keeper_owns_stock_approve(self):
        keeper = next(p for p in ROLE_PRESETS if p["code"] == "keeper")
        codes = set(expand_perms(keeper["perms"]))
        assert {"stock.in.approve", "stock.out.approve", "stock.take.approve"} <= codes


# ===================== 系统参数 / 编号规则 =====================

class TestSysParams:
    def test_defaults_persisted_on_first_read(self, db):
        assert get_sys_params(db) == DEFAULT_SYS_PARAMS
        assert get_sys_params(db) == DEFAULT_SYS_PARAMS   # 二次读取稳定
        assert db.get(models.KVSetting, "sys_params") is not None

    def test_defaults_match_decision_baseline(self, db):
        params = get_sys_params(db)
        assert params["allow_negative_stock"] is False    # O1
        assert params["allow_self_approve"] is False      # O6
        assert params["warranty_window_days"] == 30

    def test_set_coerces_and_ignores_unknown(self, db):
        out = set_sys_params(db, {"allow_negative_stock": "true", "warranty_window_days": "15",
                                  "unknown_key": 1})
        assert out["allow_negative_stock"] is True
        assert out["warranty_window_days"] == 15
        assert "unknown_key" not in out
        assert get_sys_params(db)["allow_negative_stock"] is True

    def test_set_rejects_bad_value(self, db):
        with pytest.raises(ValueError):
            set_sys_params(db, {"warranty_window_days": "abc"})
        with pytest.raises(ValueError):
            set_sys_params(db, {"pwd_min_length": 4})


class TestNumberRules:
    def test_defaults(self, db):
        rules = get_number_rules(db)
        assert rules["purchase_order"]["prefix"] == "PO"
        assert rules["stock_out"]["prefix"] == "OUT"
        assert rules["customer"]["reset"] == "never"
        assert rules["product"]["prefix"] == ""

    def test_update_prefix_and_seq_len(self, db):
        out = set_number_rules(db, {"purchase_order": {"prefix": "po", "seq_len": 5}})
        assert out["purchase_order"]["prefix"] == "PO"     # 归一为大写
        assert out["purchase_order"]["seq_len"] == 5
        assert get_number_rules(db)["purchase_order"]["seq_len"] == 5

    def test_rejects_bad_input(self, db):
        with pytest.raises(ValueError):
            set_number_rules(db, {"purchase_order": {"prefix": "PO1"}})
        with pytest.raises(ValueError):
            set_number_rules(db, {"purchase_order": {"seq_len": 12}})
        with pytest.raises(ValueError):
            set_number_rules(db, {"purchase_order": {"prefix": "TOOLONG"}})

    def test_ignores_unknown_kind(self, db):
        # 未知单据类型不应被写入
        out = set_number_rules(db, {"not_a_doc": {"prefix": "XX"}})
        assert "not_a_doc" not in out
        assert set(out) == set(DEFAULT_NUMBER_RULES)


# ===================== 模型与权限种子 =====================

class TestAuthSchema:
    def test_tables_created(self, db):
        tables = set(inspect(db.get_bind()).get_table_names())
        for name in ("org_units", "users", "roles", "user_roles",
                     "role_permissions", "operation_logs"):
            assert name in tables

    def test_seed_creates_roles_admin_and_is_idempotent(self, db):
        from app.init_db import ADMIN_USERNAME, seed_auth
        from app.models_auth import Role, User

        first = seed_auth(db)
        assert first["roles_created"] == len(ROLE_PRESETS)
        assert first["admin_created"] is True

        second = seed_auth(db)                 # 幂等：重复执行不重复创建
        assert second["roles_created"] == 0
        assert second["admin_created"] is False

        admin = db.query(User).filter(User.username == ADMIN_USERNAME).one()
        assert admin.is_superadmin is True
        assert admin.must_change_pwd is True   # AC-V2-08 首登强制改密
        assert admin.status == "enabled"
        assert verify_password("admin12345", admin.password_hash) is True

        assert db.query(Role).count() == len(ROLE_PRESETS)

    def test_seeded_roles_have_permissions(self, db):
        from app.init_db import seed_auth
        from app.models_auth import Role

        seed_auth(db)
        for preset in ROLE_PRESETS:
            role = db.query(Role).filter(Role.code == preset["code"]).one()
            assert role.data_scope == preset["data_scope"]
            assert role.builtin is True
            assert role.perm_codes, role.code

        sysadmin = db.query(Role).filter(Role.code == "sysadmin").one()
        assert set(sysadmin.perm_codes) == PERM_CODES

    def test_seed_does_not_overwrite_existing_role_perms(self, db):
        """已存在的角色不被种子覆盖（保护管理员后续调整）。"""
        from app.init_db import seed_auth
        from app.models_auth import Role, RolePermission

        seed_auth(db)
        role = db.query(Role).filter(Role.code == "buyer").one()
        # 模拟管理员调整：清空该角色权限，只留一个
        db.query(RolePermission).filter(RolePermission.role_id == role.id).delete()
        db.add(RolePermission(role_id=role.id, perm_code="dashboard.view"))
        db.commit()
        db.expire_all()          # session 为 expire_on_commit=False，需显式刷新才能看到删除

        seed_auth(db)            # 再次执行种子
        role = db.query(Role).filter(Role.code == "buyer").one()
        assert role.perm_codes == ["dashboard.view"]
