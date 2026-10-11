"""V2.4 飞书接入测试：免登、绑定、outbox 幂等与发送退避。

覆盖 `docs/27-feishu-integration-plan.md` §6 的验收场景：

| 用例类 | 覆盖 |
|---|---|
| `TestGating` | AC-FS-09 默认关闭时对既有行为零影响 |
| `TestState` | AC-FS-03 `state` 防重放/防篡改/超时 |
| `TestBinding` | 绑定、幂等、跨账号冲突、换绑、解绑（AC-FS-04） |
| `TestLoginByCode` | AC-FS-01 未绑定拒绝、AC-FS-02 免登签发本系统 JWT |
| `TestOutbox` | AC-FS-06 失败不影响业务、AC-FS-07 幂等、退避与原子抢占 |
| `TestDigest` | AC-FS-08 每日摘要去重与"无内容不打扰" |

飞书侧 API **全部 mock**：不访问外网、不需要真实 app_id，因此在无网环境可稳定运行。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app import config
from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models_auth import OperationLog, Role, User, UserIdentity
from app.models_notify import Notification
from app.permissions import DOC_APPROVE_PERM, PERM_CODES
from app.security import decode_token, hash_password
from app.services.feishu import card as card_mod
from app.services.feishu import client as feishu_client
from app.services.feishu import identity_service, notify_service
from app.services.permission_service import collect_perms, data_scope_of
from app.tools import feishu_digest


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:      # 触发 lifespan（默认飞书关闭 → 不启动发送线程）
        yield c


@pytest.fixture(autouse=True)
def clean_outbox():
    """每个用例从**空 outbox** 开始：`send_pending` 按 id 顺序取记录，
    若留着上一条用例的 pending，断言就会打到别人的记录上。"""
    with SessionLocal() as db:
        db.query(Notification).delete()
        db.commit()
    yield


@pytest.fixture
def feishu_on(monkeypatch):
    """把飞书配置临时置为"已启用"（不外网：调用方仍需 mock 具体接口）。"""
    monkeypatch.setattr(config, "FEISHU_ENABLED", True)
    monkeypatch.setattr(config, "FEISHU_APP_ID", "cli_test_app")
    monkeypatch.setattr(config, "FEISHU_APP_SECRET", "test-secret")
    monkeypatch.setattr(config, "FEISHU_REDIRECT_URI", "http://127.0.0.1:5173/feishu/callback")
    monkeypatch.setattr(config, "FEISHU_BASE_URL", "http://127.0.0.1:5173")
    monkeypatch.setattr(config, "FEISHU_SEND_INTERVAL_MS", 0)
    # 线程不在测试里跑：发送逻辑由 send_pending 直接驱动，才能断言每一步结果
    monkeypatch.setattr(notify_service, "start_worker", lambda: False)
    assert config.feishu_ready() is True
    yield


def _mk_user(*, status: str = "enabled", real_name: str = "飞书测试账号") -> int:
    username = f"feishu_{uuid.uuid4().hex[:8]}"
    with SessionLocal() as db:
        user = User(username=username, real_name=real_name,
                    password_hash=hash_password("init12345"), status=status)
        db.add(user)
        db.commit()
        return user.id


def _drop_user(uid: int) -> None:
    with SessionLocal() as db:
        db.query(UserIdentity).filter(UserIdentity.user_id == uid).delete()
        db.query(Notification).filter(Notification.recipient_user_id == uid).delete()
        db.query(OperationLog).filter(OperationLog.user_id == uid).delete()
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def _bind(uid: int, open_id: str | None = None) -> str:
    open_id = open_id or f"ou_{uuid.uuid4().hex[:10]}"
    with SessionLocal() as db:
        user = db.get(User, uid)
        identity_service.bind(db, user=user, open_id=open_id, display_name="张三")
        db.commit()
    return open_id


def _sign_state(ts: int, nonce: str, scene: str = "login") -> str:
    """按 identity_service 的算法手工签名（用于构造超时 / 篡改场景的 state）。"""
    raw = f"{ts}.{nonce}.{scene}"
    sig = hmac.new(config.get_jwt_secret().encode("utf-8"), raw.encode("ascii"),
                   hashlib.sha256).digest()
    return f"{raw}.{base64.urlsafe_b64encode(sig).rstrip(b'=').decode('ascii')}"


class _FakeDoc:
    """用于卡片/结果通知的轻量单据替身（card 模块逐字段 getattr 容错）。"""

    def __init__(self, **kw):
        self.__dict__.update(kw)


# ===================== AC-FS-09：默认关闭时的降级 =====================

class TestGating:
    def test_default_disabled(self):
        """仓库默认 FEISHU_ENABLED=0：未启用时整体不可用。"""
        assert config.FEISHU_ENABLED is False
        assert config.feishu_ready() is False

    def test_login_page_hides_entry(self, client):
        resp = client.get("/api/auth/feishu/config")
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    def test_login_without_state_rejected(self, client):
        """未启用时也不会 500：state 校验先失败，给出可读的 400。"""
        resp = client.post("/api/auth/feishu/login", json={"code": "x", "state": ""})
        assert resp.status_code == 400

    def test_password_login_still_works(self, client):
        """既有密码登录不受影响（回归防线）。"""
        resp = client.post("/api/auth/login",
                           json={"username": ADMIN_USERNAME, "password": ADMIN_INIT_PASSWORD})
        assert resp.status_code == 200
        assert resp.json()["token"]

    def test_admin_config_requires_auth(self, client):
        assert client.get("/api/system/feishu/config").status_code == 401

    def test_new_permissions_registered(self):
        assert "system.feishu.view" in PERM_CODES
        assert "system.feishu.edit" in PERM_CODES

    def test_sysadmin_gets_new_permissions(self):
        """sysadmin 语义是"全部权限"：新增权限点必须自动补齐，否则管理员会莫名 403。"""
        with SessionLocal() as db:
            role = db.query(Role).filter(Role.code == "sysadmin").first()
            assert role is not None
            assert {"system.feishu.view", "system.feishu.edit"} <= set(role.perm_codes)


# ===================== AC-FS-03：state 防重放 =====================

class TestState:
    def test_valid_state_passes(self):
        identity_service.verify_state(identity_service.make_state())

    def test_tampered_state_rejected(self):
        state = identity_service.make_state()
        with pytest.raises(identity_service.IdentityError):
            identity_service.verify_state(state[:-4] + "AAAA")

    def test_malformed_state_rejected(self):
        with pytest.raises(identity_service.IdentityError):
            identity_service.verify_state("not-a-state")

    def test_expired_state_rejected(self):
        """超过 10 分钟的 state 即使签名正确也必须拒绝（防重放）。"""
        expired = _sign_state(int(time.time()) - 700, "nonce123")
        with pytest.raises(identity_service.IdentityError):
            identity_service.verify_state(expired)

    def test_state_is_unique(self):
        assert identity_service.make_state() != identity_service.make_state()

    def test_state_carries_scene(self):
        """场景签在 state 里：回调页据此选「免登」还是「自助绑定」。

        这样就不依赖 sessionStorage —— 它按 origin 隔离，从 localhost 跳回内网 IP 时会丢，
        会把自助绑定误当成免登（表现为"刚绑定完又提示未绑定"）。
        """
        assert identity_service.verify_state(identity_service.make_state("bind")) == "bind"
        assert identity_service.verify_state(identity_service.make_state("login")) == "login"
        assert identity_service.verify_state(identity_service.make_state()) == "login"

    def test_unknown_scene_falls_back_to_login(self):
        assert identity_service.verify_state(identity_service.make_state("evil")) == "login"

    def test_scene_tamper_breaks_signature(self):
        """改场景而不重签 → 签名校验必须失败（场景受签名保护）。"""
        ts, nonce, _scene, sig = identity_service.make_state("login").split(".")
        with pytest.raises(identity_service.IdentityError):
            identity_service.verify_state(f"{ts}.{nonce}.bind.{sig}")


# ===================== 绑定（AC-FS-04 相关） =====================

class TestBinding:
    def test_bind_and_unbind(self):
        uid = _mk_user()
        try:
            open_id = _bind(uid)
            with SessionLocal() as db:
                assert identity_service.identity_of(db, uid).open_id == open_id
                assert identity_service.bound_open_id(db, uid) == open_id
            with SessionLocal() as db:
                assert identity_service.unbind(db, uid) is True
                db.commit()
                assert identity_service.identity_of(db, uid) is None
        finally:
            _drop_user(uid)

    def test_rebind_same_pair_is_idempotent(self):
        uid = _mk_user()
        try:
            open_id = _bind(uid)
            with SessionLocal() as db:
                user = db.get(User, uid)
                first = identity_service.bind(db, user=user, open_id=open_id)
                again = identity_service.bind(db, user=user, open_id=open_id)
                assert first.id == again.id
                assert (db.query(UserIdentity)
                        .filter(UserIdentity.open_id == open_id).count()) == 1
        finally:
            _drop_user(uid)

    def test_open_id_cannot_bind_two_accounts(self):
        """一个飞书身份只能绑一个系统账号（防冒用/串号）。"""
        uid_a, uid_b = _mk_user(), _mk_user()
        try:
            open_id = _bind(uid_a)
            with SessionLocal() as db:
                user_b = db.get(User, uid_b)
                with pytest.raises(identity_service.IdentityError) as exc:
                    identity_service.bind(db, user=user_b, open_id=open_id)
                assert exc.value.status == 409
        finally:
            _drop_user(uid_a)
            _drop_user(uid_b)

    def test_one_account_keeps_single_identity(self):
        """换绑：同一账号只保留一个飞书身份。"""
        uid = _mk_user()
        try:
            first = _bind(uid)
            second = _bind(uid)
            assert first != second
            with SessionLocal() as db:
                rows = db.query(UserIdentity).filter(UserIdentity.user_id == uid).all()
                assert len(rows) == 1
                assert rows[0].open_id == second
        finally:
            _drop_user(uid)

    def test_disabled_account_gets_no_open_id(self):
        """停用账号不投递（与登录态"停用立即失效"口径一致）。"""
        uid = _mk_user()
        try:
            _bind(uid)
            with SessionLocal() as db:
                user = db.get(User, uid)
                user.status = "disabled"
                db.commit()
                assert identity_service.bound_open_id(db, uid) is None
        finally:
            _drop_user(uid)


# ===================== AC-FS-01/02：免登（含自动建号） =====================

# 飞书 `authen/v1/user_info` 的典型返回（字段名取自官方文档）
LOGIN_INFO = {"open_id": "ou_login_case", "name": "李四", "union_id": "on_union_1",
              "tenant_key": "tk_1", "email": "lisi@corp.com", "mobile": "13800000000",
              "employee_no": ""}
API_INFO = dict(LOGIN_INFO, open_id="ou_api_case", email="apiuser@corp.com")


def _drop_by_open_id(*open_ids: str) -> None:
    """清掉某 open_id 对应的（自动建号）账号、绑定与日志。

    自动建号的账号不是用例自己建的，必须按 **open_id** 反查清理；
    审计日志里建号那条的 `user_id` 为空（动作发生在登录前），所以还要按 object_no 兜底。
    """
    with SessionLocal() as db:
        idents = db.query(UserIdentity).filter(UserIdentity.open_id.in_(list(open_ids))).all()
        user_ids = [i.user_id for i in idents]
        usernames = ([u.username for u in db.query(User).filter(User.id.in_(user_ids)).all()]
                     if user_ids else [])
        # 全部走批量删除：先删绑定再删账号（避免 ORM 单行删除与外键级联撞车）
        db.query(UserIdentity).filter(
            UserIdentity.open_id.in_(list(open_ids))).delete(synchronize_session=False)
        if user_ids:
            db.query(Notification).filter(
                Notification.recipient_user_id.in_(user_ids)).delete(synchronize_session=False)
            db.query(OperationLog).filter(
                OperationLog.user_id.in_(user_ids)).delete(synchronize_session=False)
            db.query(User).filter(User.id.in_(user_ids)).delete(synchronize_session=False)
            if usernames:
                db.query(OperationLog).filter(
                    OperationLog.object_no.in_(usernames)).delete(synchronize_session=False)
        db.query(OperationLog).filter(
            OperationLog.object_no.in_(list(open_ids))).delete(synchronize_session=False)
        db.commit()


@pytest.fixture
def feishu_user_info(monkeypatch):
    """mock 飞书两个出网接口（换令牌 + 取用户信息）。"""
    monkeypatch.setattr(feishu_client, "oauth_exchange_code", lambda code: "u-token")
    monkeypatch.setattr(feishu_client, "get_user_info", lambda token: dict(LOGIN_INFO))
    yield


class TestLoginByCode:
    @pytest.fixture(autouse=True)
    def cleanup(self):
        """每个用例前后都清掉自动建号的账号，避免用例之间互相"已绑定"。"""
        _drop_by_open_id("ou_login_case", "ou_api_case")
        yield
        _drop_by_open_id("ou_login_case", "ou_api_case")

    @pytest.fixture
    def mock_feishu(self, feishu_on, feishu_user_info):
        yield

    def test_unbound_auto_provisions_account(self, mock_feishu):
        """AC-FS-01B：未绑定的飞书账号 → **自动建号**，签发本系统 JWT，且零角色。"""
        with SessionLocal() as db:
            result = identity_service.login_by_code(db, code="c",
                                                    state=identity_service.make_state())
            assert result["token"]
            assert result["auto_provisioned"] is True
            assert result["pending_roles"] is True        # 没有角色 → 前端送「待分配角色」页
            uid = result["user_id"]

        with SessionLocal() as db:
            user = db.get(User, uid)
            # 账号资料取自飞书返回值（登录名优先用邮箱前缀，管理员一眼认得出是谁）
            assert user.username == "lisi"
            assert user.real_name == "李四"
            assert user.email == "lisi@corp.com"
            assert user.phone == "13800000000"
            assert user.status == "enabled"
            assert user.is_superadmin is False
            assert user.created_by is None
            # 零权限：建号不等于授权，角色必须由管理员分配
            assert list(user.roles) == []
            assert collect_perms(db, user) == set()
            assert data_scope_of(user) == "SELF"
            # 绑定同时建立，下次登录不再建号
            ident = identity_service.identity_of(db, uid)
            assert ident is not None and ident.open_id == "ou_login_case"
            assert int(decode_token(result["token"])["sub"]) == uid
            # 建号留痕：管理员能查到"这是扫码自动建的、还没分配角色"
            signup = (db.query(OperationLog)
                      .filter(OperationLog.action == "feishu_signup").first())
            assert signup is not None and signup.object_no == user.username
            assert "未分配角色" in (signup.detail or "")

    def test_second_login_reuses_account(self, mock_feishu):
        """同一飞书身份再次扫码：复用同一个账号，不重复建号。"""
        with SessionLocal() as db:
            first = identity_service.login_by_code(db, code="c",
                                                   state=identity_service.make_state())
        with SessionLocal() as db:
            second = identity_service.login_by_code(db, code="c",
                                                    state=identity_service.make_state())
        assert second["user_id"] == first["user_id"]
        assert second["auto_provisioned"] is False
        with SessionLocal() as db:
            assert db.query(UserIdentity).filter(
                UserIdentity.open_id == "ou_login_case").count() == 1
            assert db.query(OperationLog).filter(
                OperationLog.action == "feishu_signup").count() == 1

    def test_unbound_rejected_when_auto_provision_disabled(self, mock_feishu, monkeypatch):
        """`CTMS_FEISHU_AUTO_PROVISION=0` 时退回旧口径：未绑定一律 401，不建号。"""
        monkeypatch.setattr(config, "FEISHU_AUTO_PROVISION", False)
        with SessionLocal() as db:
            before = int(db.query(User).count() or 0)
            with pytest.raises(identity_service.IdentityError) as exc:
                identity_service.login_by_code(db, code="c",
                                               state=identity_service.make_state())
            assert exc.value.status == 401
            assert "未绑定" in str(exc.value)
            assert int(db.query(User).count() or 0) == before
        with SessionLocal() as db:
            row = (db.query(OperationLog)
                   .filter(OperationLog.action == "feishu_login",
                           OperationLog.object_no == "ou_login_case",
                           OperationLog.result == "fail")
                   .order_by(OperationLog.id.desc()).first())
            assert row is not None

    def test_auto_provision_does_not_take_over_existing_username(self, mock_feishu):
        """登录名撞车（邮箱前缀已被占用）时加后缀，**绝不**顶替既有账号。"""
        existing_id = None
        with SessionLocal() as db:
            other = User(username="lisi", real_name="真实李四",
                         password_hash=hash_password("init12345"), status="enabled")
            db.add(other)
            db.commit()
            existing_id = other.id
        try:
            with SessionLocal() as db:
                result = identity_service.login_by_code(
                    db, code="c", state=identity_service.make_state())
                uid = result["user_id"]
            with SessionLocal() as db:
                assert db.get(User, uid).username == "lisi_2"
                # 既有账号原封不动（仍能用原密码登录，绑定关系不受影响）
                kept = db.get(User, existing_id)
                assert kept.username == "lisi" and kept.status == "enabled"
                assert identity_service.identity_of(db, existing_id) is None
        finally:
            if existing_id:
                _drop_user(existing_id)

    def test_concurrent_provision_conflict_recovers(self, mock_feishu, monkeypatch):
        """并发扫码（两个标签页）：唯一约束冲突后按 open_id 复用对方建好的账号，不冒 500。"""
        real = identity_service.provision_user_from_feishu

        def _race(db, *, info, request=None):
            real(db, info=info, request=request)      # 对方先建好并提交
            db.commit()
            raise IntegrityError("INSERT INTO user_identities", {}, Exception("UNIQUE failed"))

        monkeypatch.setattr(identity_service, "provision_user_from_feishu", _race)
        with SessionLocal() as db:
            result = identity_service.login_by_code(db, code="c",
                                                    state=identity_service.make_state())
        assert result["auto_provisioned"] is False      # 复用了对方创建的账号
        assert result["pending_roles"] is True
        with SessionLocal() as db:
            assert db.query(UserIdentity).filter(
                UserIdentity.open_id == "ou_login_case").count() == 1

    def test_disabled_account_rejected(self, mock_feishu):
        uid = _mk_user(status="disabled")
        try:
            _bind(uid, open_id="ou_login_case")
            with SessionLocal() as db:
                with pytest.raises(identity_service.IdentityError) as exc:
                    identity_service.login_by_code(db, code="c",
                                                  state=identity_service.make_state())
                assert exc.value.status == 403
        finally:
            _drop_user(uid)

    def test_bad_state_never_calls_feishu(self, feishu_on, monkeypatch):
        """state 校验必须在调用飞书**之前**完成，否则等于开放重放。"""
        called = {"n": 0}

        def _record(code):
            called["n"] += 1
            return "u-token"

        monkeypatch.setattr(feishu_client, "oauth_exchange_code", _record)
        with SessionLocal() as db:
            with pytest.raises(identity_service.IdentityError):
                identity_service.login_by_code(db, code="c", state="bad.state.value")
        assert called["n"] == 0


# ===================== 自动建号：接口层与管理员可见性 =====================

class TestAutoProvisionApi:
    @pytest.fixture(autouse=True)
    def cleanup(self):
        _drop_by_open_id("ou_api_case")
        yield
        _drop_by_open_id("ou_api_case")

    def _login(self, client, monkeypatch):
        monkeypatch.setattr(feishu_client, "oauth_exchange_code", lambda code: "u-token")
        monkeypatch.setattr(feishu_client, "get_user_info",
                            lambda token: dict(API_INFO))
        resp = client.post("/api/auth/feishu/login",
                           json={"code": "c", "state": identity_service.make_state()})
        assert resp.status_code == 200, resp.text
        return resp.json()

    def test_login_response_flags_and_me_pending(self, client, feishu_on, monkeypatch):
        """接口层：`auto_provisioned` / `pending_roles` 必须成套返回，
        `/auth/me` 也报 pending（路由守卫靠它把人送到待分配页）。"""
        body = self._login(client, monkeypatch)
        assert body["auto_provisioned"] is True
        assert body["pending_roles"] is True
        assert body["roles"] == []
        assert body["user"]["username"] == "apiuser"

        me = client.get("/api/auth/me",
                        headers={"Authorization": f"Bearer {body['token']}"})
        assert me.status_code == 200
        payload = me.json()
        assert payload["pending_roles"] is True
        assert payload["perms"] == [] and payload["menus"] == []

    def test_admin_can_find_pending_account(self, client, feishu_on, monkeypatch):
        """管理员侧：飞书接入页与账号管理页都能看到"待分配角色"的自动建号账号。"""
        body = self._login(client, monkeypatch)
        uid = body["user"]["id"]
        admin = client.post("/api/auth/login",
                            json={"username": ADMIN_USERNAME,
                                  "password": ADMIN_INIT_PASSWORD}).json()["token"]
        headers = {"Authorization": f"Bearer {admin}"}

        cfg = client.get("/api/system/feishu/config", headers=headers)
        assert cfg.status_code == 200
        assert cfg.json()["auto_provision"] is True
        pending_ids = [u["id"] for u in cfg.json()["pending_role_users"]]
        assert uid in pending_ids
        assert cfg.json()["pending_role_total"] >= 1

        users = client.get("/api/system/users",
                           params={"awaiting_role": True}, headers=headers)
        assert users.status_code == 200
        row = next((u for u in users.json()["items"] if u["id"] == uid), None)
        assert row is not None and row["awaiting_role"] is True

    def test_assigning_role_clears_pending(self, client, feishu_on, monkeypatch):
        """管理员分配角色后：`/auth/me` 不再是待分配状态，权限点随之生效。"""
        body = self._login(client, monkeypatch)
        uid = body["user"]["id"]
        admin = client.post("/api/auth/login",
                            json={"username": ADMIN_USERNAME,
                                  "password": ADMIN_INIT_PASSWORD}).json()["token"]
        headers = {"Authorization": f"Bearer {admin}"}
        role_id = next(r["id"] for r in client.get("/api/system/roles", headers=headers)
                       .json()["items"] if r["code"] != "sysadmin")

        resp = client.put(f"/api/system/users/{uid}", json={"role_ids": [role_id]},
                          headers=headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["awaiting_role"] is False
        assert resp.json()["role_names"]

        me = client.get("/api/auth/me",
                        headers={"Authorization": f"Bearer {body['token']}"})
        assert me.json()["pending_roles"] is False
        assert me.json()["perms"]


# ===================== AC-FS-06/07：outbox =====================

class TestOutbox:
    def test_skips_unbound_recipient(self, feishu_on):
        uid = _mk_user()
        try:
            with SessionLocal() as db:
                row = notify_service.enqueue(db, event_key=f"t:{uuid.uuid4()}",
                                             category="test", recipient_user_id=uid,
                                             card_obj={"schema": "2.0"})
                assert row is None
        finally:
            _drop_user(uid)

    def test_event_key_is_idempotent(self, feishu_on):
        """AC-FS-07：同一 event_key 只入队一次（重试/重复触发都不重复打扰）。"""
        uid = _mk_user()
        try:
            _bind(uid)
            key = f"t:{uuid.uuid4()}"
            with SessionLocal() as db:
                first = notify_service.enqueue(db, event_key=key, category="test",
                                               recipient_user_id=uid,
                                               card_obj={"schema": "2.0"})
                db.commit()
                assert first is not None
                second = notify_service.enqueue(db, event_key=key, category="test",
                                                recipient_user_id=uid,
                                                card_obj={"schema": "2.0"})
                db.commit()
                assert second is None
                assert db.query(Notification).filter(Notification.event_key == key).count() == 1
        finally:
            _drop_user(uid)

    def test_enqueue_conflict_does_not_break_business_transaction(self, feishu_on):
        """AC-FS-06（核心）：入队撞唯一键**不能**污染调用方的业务事务。

        同一事务内：入队 → 用同 key 再入队（必冲突）→ 再写一条业务数据 → 提交。
        三者都应成功，证明 `begin_nested()`（savepoint）隔离生效。
        """
        uid = _mk_user()
        other_id = None
        try:
            _bind(uid)
            key = f"t:{uuid.uuid4()}"
            with SessionLocal() as db:
                assert notify_service.enqueue(db, event_key=key, category="test",
                                              recipient_user_id=uid,
                                              card_obj={"schema": "2.0"}) is not None
                # 第二次必然撞唯一约束，但必须只回滚这一条 savepoint
                assert notify_service.enqueue(db, event_key=key, category="test",
                                              recipient_user_id=uid,
                                              card_obj={"schema": "2.0"}) is None
                other = User(username=f"feishu_{uuid.uuid4().hex[:8]}", real_name="事务测试",
                             password_hash=hash_password("x12345"), status="enabled")
                db.add(other)
                db.commit()          # 业务写入与入队一起提交成功
                other_id = other.id  # 必须在 session 关闭前取：commit 会让属性过期
                assert other_id is not None
        finally:
            _drop_user(uid)
            if other_id:
                _drop_user(other_id)

    def test_doc_result_requires_bound_recipient(self, feishu_on):
        uid = _mk_user()
        try:
            doc = _FakeDoc(id=1, doc_no="PR-1", doc_date=date.today(),
                           total_amount=100, created_by=uid, submitted_by=uid)
            with SessionLocal() as db:
                assert notify_service.enqueue_doc_result(
                    db, doc=doc, kind="purchase_request", kind_label="采购申请单",
                    result="approved", operator="王五") == 0     # 未绑定 → 不入队

            _bind(uid)
            with SessionLocal() as db:
                assert notify_service.enqueue_doc_result(
                    db, doc=doc, kind="purchase_request", kind_label="采购申请单",
                    result="approved", operator="王五") == 1
                db.commit()
                row = (db.query(Notification)
                       .filter(Notification.recipient_user_id == uid).first())
                assert row is not None
                assert row.category == "doc_approved"
                assert "已审核通过" in row.payload
                assert row.recipient_open_id          # 收件人 open_id 快照
        finally:
            _drop_user(uid)

    def test_send_success_marks_sent(self, feishu_on, monkeypatch):
        uid = _mk_user()
        try:
            _bind(uid)
            sent: list[dict] = []
            monkeypatch.setattr(feishu_client, "send_message",
                                lambda **kw: sent.append(kw) or {"code": 0})
            with SessionLocal() as db:
                notify_service.enqueue(db, event_key=f"t:{uuid.uuid4()}", category="test",
                                       recipient_user_id=uid, card_obj={"schema": "2.0"})
                db.commit()
                result = notify_service.send_pending(db, limit=50)
                assert result["sent"] >= 1 and result["failed"] == 0
                row = db.query(Notification).filter(Notification.recipient_user_id == uid).first()
                assert row.status == "sent" and row.sent_at is not None
                assert sent and sent[0]["receive_id"] == row.recipient_open_id
                # 飞书侧去重用标准 UUID（由 event_key 派生），不是任意字符串
                assert uuid.UUID(sent[0]["uuid"])
        finally:
            _drop_user(uid)

    def test_send_failure_backs_off_then_fails(self, feishu_on, monkeypatch):
        """失败退避：未达上限回到 pending 并设 next_retry_at；达上限转 failed。"""
        uid = _mk_user()
        try:
            _bind(uid)

            def _fail(**_kw):
                raise feishu_client.FeishuError("模拟限流", code=99991400)

            monkeypatch.setattr(feishu_client, "send_message", _fail)
            with SessionLocal() as db:
                notify_service.enqueue(db, event_key=f"t:{uuid.uuid4()}", category="test",
                                       recipient_user_id=uid, card_obj={"schema": "2.0"})
                db.commit()
                notify_service.send_pending(db, limit=1)
                row = db.query(Notification).filter(Notification.recipient_user_id == uid).first()
                assert row.status == "pending"
                assert row.attempts == 1
                assert row.next_retry_at is not None        # 退避：短期内不再试
                assert "模拟限流" in (row.last_error or "")

                row.attempts = config.FEISHU_MAX_ATTEMPTS  # 顶到上限
                row.next_retry_at = None
                db.commit()
                notify_service.send_pending(db, limit=1)
                db.refresh(row)
                assert row.status == "failed"
        finally:
            _drop_user(uid)

    def test_sending_rows_are_not_resent(self, feishu_on, monkeypatch):
        """原子抢占：已处于 sending 的记录不会被第二个执行者重复发送。"""
        uid = _mk_user()
        try:
            _bind(uid)
            calls = {"n": 0}
            monkeypatch.setattr(feishu_client, "send_message",
                                lambda **kw: calls.__setitem__("n", calls["n"] + 1) or {"code": 0})
            with SessionLocal() as db:
                notify_service.enqueue(db, event_key=f"t:{uuid.uuid4()}", category="test",
                                       recipient_user_id=uid, card_obj={"schema": "2.0"})
                db.commit()
                db.query(Notification).filter(Notification.recipient_user_id == uid) \
                    .update({"status": "sending"})
                db.commit()
                result = notify_service.send_pending(db, limit=50)
                assert result["sent"] == 0 and calls["n"] == 0
        finally:
            _drop_user(uid)

    def test_retry_failed_resets_state(self, feishu_on):
        uid = _mk_user()
        try:
            _bind(uid)
            with SessionLocal() as db:
                notify_service.enqueue(db, event_key=f"t:{uuid.uuid4()}", category="test",
                                       recipient_user_id=uid, card_obj={"schema": "2.0"})
                db.commit()
                db.query(Notification).filter(Notification.recipient_user_id == uid) \
                    .update({"status": "failed", "attempts": 5, "last_error": "x"})
                db.commit()
                assert notify_service.retry_failed(db) >= 1
                row = db.query(Notification).filter(Notification.recipient_user_id == uid).first()
                assert row.status == "pending" and row.attempts == 0
        finally:
            _drop_user(uid)

    def test_outbox_stats_shape(self, feishu_on):
        with SessionLocal() as db:
            stats = notify_service.outbox_stats(db)
            assert {"pending", "failed", "sent_today", "worker_running"} <= set(stats)


# ===================== AC-FS-08：每日摘要 =====================

class TestDigest:
    def test_markdown_lists_all_sections(self):
        markdown, count = feishu_digest.build_markdown(
            today=date(2026, 8, 19),
            todos=[{"label": "采购单", "doc_no": "PO-1", "party": "供应商A", "amount": 1200.0}],
            todos_total=3,
            warranty=[{"contract_no": "HT-1", "name": "框架合同",
                       "warranty_end": "2026-08-25", "days_left": 6}],
            warranty_total=1,
            stock=[{"warehouse_name": "ZC-主仓", "product_name": "物料A",
                    "qty": 3.0, "safety_stock": 10.0}],
            stock_total=1)
        assert "待我审核：3 张" in markdown
        assert "PO-1" in markdown
        assert "质保即将到期：1 项" in markdown
        assert "库存预警：1 项" in markdown
        assert count == 5

    def test_empty_digest_has_zero_count(self):
        """没有任何内容时 count=0 → 调用方不发空消息（不打扰）。"""
        _markdown, count = feishu_digest.build_markdown(
            today=date(2026, 8, 19), todos=[], todos_total=0,
            warranty=[], warranty_total=0, stock=[], stock_total=0)
        assert count == 0

    def test_digest_event_key_dedupes_same_day(self, feishu_on):
        uid = _mk_user()
        try:
            _bind(uid)
            key = f"digest:{date.today().isoformat()}:u{uid}"
            with SessionLocal() as db:
                first = notify_service.enqueue(db, event_key=key, category="todo",
                                               recipient_user_id=uid,
                                               card_obj={"schema": "2.0"})
                db.commit()
                second = notify_service.enqueue(db, event_key=key, category="todo",
                                                recipient_user_id=uid,
                                                card_obj={"schema": "2.0"})
                assert first is not None and second is None
        finally:
            _drop_user(uid)

    def test_dry_run_writes_nothing(self, feishu_on, capsys):
        with SessionLocal() as db:
            before = int(db.query(Notification).count() or 0)
        assert feishu_digest.main(["--dry-run"]) == 0
        capsys.readouterr()
        with SessionLocal() as db:
            after = int(db.query(Notification).count() or 0)
        assert after == before

    def test_disabled_returns_zero_without_sending(self, monkeypatch):
        monkeypatch.setattr(config, "FEISHU_ENABLED", False)
        assert feishu_digest.main([]) == 0


# ===================== 卡片与链接 =====================

class TestCard:
    def test_todo_card_contains_doc_and_button(self, monkeypatch):
        monkeypatch.setattr(config, "FEISHU_BASE_URL", "http://ctms.local")
        doc = _FakeDoc(id=7, doc_no="PO-7", doc_date=date(2026, 8, 19), total_amount=88.5,
                       supplier_name="供应商B", handler_name="王五", remark="急件")
        card, _ = card_mod.build_doc_todo_card(doc, kind="purchase_order", kind_label="采购单",
                                              actor_name="李四")
        text = json.dumps(card, ensure_ascii=False)
        assert card["schema"] == "2.0"
        assert "PO-7" in text and "供应商B" in text
        assert "http://ctms.local/purchase/orders/7" in text

    def test_no_button_without_base_url(self, monkeypatch):
        monkeypatch.setattr(config, "FEISHU_BASE_URL", "")
        assert card_mod.doc_url("purchase_order", 7) is None
        card, _ = card_mod.build_doc_todo_card(_FakeDoc(id=7, doc_no="PO-7"),
                                              kind="purchase_order", kind_label="采购单")
        assert all(el.get("tag") != "button" for el in card["body"]["elements"])

    def test_result_card_labels(self):
        card, _ = card_mod.build_doc_result_card(_FakeDoc(id=3, doc_no="SO-3"),
                                                kind="sales_order", kind_label="销售订单",
                                                result="rejected", reason="价格不对",
                                                operator="主管")
        text = json.dumps(card, ensure_ascii=False)
        assert "已驳回" in text and "价格不对" in text

    def test_doc_paths_cover_all_approvable_kinds(self):
        """推送用到的单据类型都必须有前端路径映射，否则卡片按钮会静默消失。"""
        assert set(DOC_APPROVE_PERM) <= set(card_mod.DOC_PATHS)


# ===================== 权限点映射一致性 =====================

class TestPermissionMap:
    def test_approve_map_codes_exist(self):
        for kind, code in DOC_APPROVE_PERM.items():
            assert code in PERM_CODES, f"{kind} 的审核权限点 {code} 不在权限点清单里"
