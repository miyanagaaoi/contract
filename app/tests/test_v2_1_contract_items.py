"""V2.1 / T-V2.1-02：合同行项绑定系统物料档案（AC-V2.1-04）。

对应规格：
- `22-v2.1-requirements.md` BR-V2.1-02：合同行项**必须**绑定物料（新建/编辑/导入强制）；
- `22-v2.1-requirements.md` AC-V2.1-04：未选物料即保存被拒；选择后快照正确显示；
- `23-v2.1-system-design.md` §2.1 / §10：快照回填，且 `_sig()` 必须纳入 `product_id`。

⚠️ 最后一条尤其关键：`_apply_items` 用 `old_sig == new_sig` 短路"无变化"的编辑。
若签名漏掉 `product_id`，"**仅改了物料绑定**"的保存会被**静默丢弃**（接口返回成功但
数据没变）——这是最难靠人工发现的一类缺陷，故此处用白盒方式直接断言。
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.init_db import ADMIN_INIT_PASSWORD, ADMIN_USERNAME
from app.main import app
from app.models import Contract
from app.models_master import Product
from app.routers.contracts import _apply_items

MASTER = "/api/master"
CONTRACTS = "/api/contracts"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def h(client):
    resp = client.post("/api/auth/login",
                       json={"username": ADMIN_USERNAME, "password": ADMIN_INIT_PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['token']}"}


@pytest.fixture(scope="module")
def _type_uom(client, h) -> tuple[int, int]:
    """建一个商品类型 + 一个计量单位，供后续物料复用。"""
    ptype = client.post(f"{MASTER}/product-types", headers=h,
                        json={"name": f"V21类型_{uuid.uuid4().hex[:6]}"})
    assert ptype.status_code == 200, ptype.text
    uom = client.post(f"{MASTER}/uoms", headers=h,
                      json={"code": f"V{uuid.uuid4().hex[:4].upper()}",
                            "name": f"个{uuid.uuid4().hex[:4]}", "decimals": 0})
    assert uom.status_code == 200, uom.text
    return ptype.json()["id"], uom.json()["id"]


def _mk_product(client, h, ids: tuple[int, int], **extra) -> dict:
    ptype_id, uom_id = ids
    resp = client.post(f"{MASTER}/products", headers=h,
                       json={"name": f"V21物料_{uuid.uuid4().hex[:6]}", "spec": "规格A",
                             "product_type_id": ptype_id, "uom_id": uom_id, **extra})
    assert resp.status_code == 200, resp.text
    return resp.json()


def _mk_contract(client, h, items):
    return client.post(CONTRACTS, headers=h, json={
        "name": f"V21合同_{uuid.uuid4().hex[:6]}", "type": "PUR",
        "subject_code": "ZC", "amount": 100, "items": items,
    })


# ---------------------------------------------------------------- 强制绑定

def test_行项未选物料被拒(client, h):
    """AC-V2.1-04：未绑定物料的行项不允许保存。"""
    resp = _mk_contract(client, h, items=[{"name": "无物料行", "qty": 1, "unit_price": 2}])
    assert resp.status_code == 422, resp.text
    assert "必须选择物料档案" in resp.text


def test_行项物料不存在被拒(client, h):
    resp = _mk_contract(client, h, items=[{"product_id": 99_999_999, "qty": 1, "unit_price": 1}])
    assert resp.status_code == 422, resp.text
    assert "物料不存在" in resp.text


def test_行项物料非数字被拒(client, h):
    resp = _mk_contract(client, h, items=[{"product_id": "abc", "qty": 1, "unit_price": 1}])
    assert resp.status_code == 422, resp.text
    assert "物料编号非法" in resp.text


# ---------------------------------------------------------------- 正常路径与快照

def test_绑定物料成功并回填快照(client, h, _type_uom):
    """AC-V2.1-04：物料信息（编码/名称/规格）正确落库；金额=Σ行项总价。"""
    product = _mk_product(client, h, _type_uom)
    resp = _mk_contract(client, h, items=[{"product_id": product["id"], "qty": 3, "unit_price": 5}])
    assert resp.status_code == 200, resp.text
    cid = resp.json()["id"]

    detail = client.get(f"{CONTRACTS}/{cid}", headers=h).json()
    item = detail["items"][0]
    assert item["product_id"] == product["id"]
    assert item["product_code"] == product["code"]
    assert item["product_name"] == product["name"]
    # 未显式传 name/spec 时，默认取物料档案（用户仍可覆盖）
    assert item["name"] == product["name"]
    assert item["spec"] == product["spec"]
    assert float(detail["amount"]) == 15.0


def test_显式传入的名称可覆盖物料默认值(client, h, _type_uom):
    product = _mk_product(client, h, _type_uom)
    resp = _mk_contract(client, h, items=[{
        "product_id": product["id"], "name": "自定义名称", "spec": "自定义规格",
        "qty": 1, "unit_price": 1,
    }])
    assert resp.status_code == 200, resp.text
    item = client.get(f"{CONTRACTS}/{resp.json()['id']}", headers=h).json()["items"][0]
    assert item["name"] == "自定义名称"
    assert item["spec"] == "自定义规格"
    assert item["product_code"] == product["code"]   # 快照仍记录所绑物料


def test_停用物料被拒(client, h, _type_uom):
    """停用物料不可再被新行项选用（下拉隐藏，服务端兜底）。"""
    product = _mk_product(client, h, _type_uom)
    with SessionLocal() as db:
        row = db.get(Product, product["id"])
        row.status = "disabled"
        db.commit()

    resp = _mk_contract(client, h, items=[{"product_id": product["id"], "qty": 1, "unit_price": 1}])
    assert resp.status_code == 422, resp.text
    assert "已停用" in resp.text


# ---------------------------------------------------------------- _sig 回归防线

def test_仅变更物料绑定不被静默丢弃(client, h, _type_uom):
    """`_sig()` 必须包含 product_id。

    `_apply_items` 在 `old_sig == new_sig` 时**直接 return**。若签名漏掉 `product_id`，
    那么"只把行项从物料 A 换成物料 B（名称/数量/单价都不动）"的保存会返回成功但
    **数据毫无变化**——静默丢数据。此处直接断言数据确实被更新。
    """
    product_a = _mk_product(client, h, _type_uom)
    product_b = _mk_product(client, h, _type_uom)

    resp = _mk_contract(client, h, items=[{
        "product_id": product_a["id"], "name": product_a["name"],
        "spec": product_a["spec"], "qty": 1, "unit_price": 1,
    }])
    assert resp.status_code == 200, resp.text
    cid = resp.json()["id"]

    # 白盒：仅替换 product_id，其余字段保持完全一致
    with SessionLocal() as db:
        contract = db.get(Contract, cid)
        _apply_items(db, contract, [{
            "product_id": product_b["id"], "name": product_a["name"],
            "spec": product_a["spec"], "qty": "1", "unit_price": "1",
        }])
        db.commit()
        db.refresh(contract)
        assert contract.items[0].product_id == product_b["id"], (
            "仅变更物料绑定被静默丢弃——请检查 routers/contracts.py::_apply_items 的 _sig() "
            "是否遗漏 product_id"
        )
        assert contract.items[0].product_code == product_b["code"]
        assert contract.items[0].product_name == product_b["name"]
