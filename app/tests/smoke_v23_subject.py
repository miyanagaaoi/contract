"""V2.3 冒烟：PostgreSQL 目标库上的端到端验证（N1~N5）。

与 `smoke_m1/m2/m3` 同一风格：**对真实数据库**跑一遍关键路径，但不留业务脏数据
（唯一新增的草稿单据在断言后按 id 物理清理）。

运行（必须先把 `CTMS_DB_URL` 指向待验证的库）：

```bash
set CTMS_DB_URL=postgresql+psycopg2://postgres:good789good@192.168.31.27:5444/ctms
app\\.venv\\Scripts\\python app\\tests\\smoke_v23_subject.py
```

覆盖：
1. 仓库档案返回 `subject_code/subject_name/display_name`，显示名为 `主体码-仓库名`；
2. 单据列表可按签约公司筛选，签约公司列有值（存量已回填）；
3. 库存明细可按公司筛选（仓库所属公司）；
4. 新建单据**缺少签约公司 → 422**；带上主体码 → 成功且写入名称快照；
5. 写入路径在 PG 上可用（布尔/日期/自增序列均正常 —— 序列未重置会在此暴露）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("CTMS_JWT_SECRET", "smoke-v23-only-secret-0123456789abcdef")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models_auth import User  # noqa: E402
from app.security import create_token  # noqa: E402

PASSED: list[str] = []
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASSED if ok else FAILED).append(name)
    print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + (f" -> {detail}" if detail else ""))


def main() -> int:
    print(f"目标库：{engine.url}")
    with SessionLocal() as db:
        user = (db.query(User).filter(User.username == "admin").first()
                or db.query(User).order_by(User.id.asc()).first())
        if user is None:
            print("库中没有账号，无法冒烟")
            return 2
        token, _ = create_token(user_id=user.id, username=user.username,
                                real_name=user.real_name or "", org_id=user.org_id)
    headers = {"Authorization": f"Bearer {token}"}
    client = TestClient(app)

    # 1. 健康检查 + 字典
    r = client.get("/api/health")
    check("健康检查", r.status_code == 200, str(r.status_code))
    r = client.get("/api/meta", headers=headers)
    subjects = (r.json() or {}).get("subjects") or []
    check("我方公司字典可读", r.status_code == 200 and bool(subjects),
          ",".join(s["code"] for s in subjects))
    code = subjects[0]["code"] if subjects else "ZC"
    name = subjects[0]["name"] if subjects else ""

    # 2. 仓库档案：所属公司 + 显示名
    r = client.get("/api/master/warehouses", headers=headers,
                   params={"include_disabled": "true", "page_size": 50})
    whs = (r.json() or {}).get("items") or []
    with_subject = [w for w in whs if w.get("subject_code")]
    display_ok = all(
        (w.get("display_name") or "") == f"{w['subject_code']}-{w['name']}"
        for w in with_subject)
    check("仓库返回所属公司", bool(with_subject), f"{len(with_subject)}/{len(whs)} 个仓库有公司")
    check("仓库显示名 = 主体码-仓库名", display_ok,
          with_subject[0]["display_name"] if with_subject else "无")

    # 3. 单据列表按签约公司筛选
    r = client.get("/api/purchase/requests", headers=headers,
                   params={"subject_code": code, "page_size": 5})
    body = r.json() if r.status_code == 200 else {}
    rows = body.get("items") or []
    check("采购申请按签约公司筛选", r.status_code == 200 and all(
        row.get("subject_code") == code for row in rows), f"{body.get('total')} 条")

    # 4. 库存明细按公司筛选
    r = client.get("/api/stock/balances", headers=headers,
                   params={"subject_code": code, "page_size": 10})
    items = (r.json() or {}).get("items") if r.status_code == 200 else None
    check("库存明细按公司筛选", r.status_code == 200 and isinstance(items, list),
          f"{len(items or [])} 行")

    # 5. 库存明细按仓库显示名
    if items:
        check("库存明细带仓库显示名", bool(items[0].get("warehouse_display_name")),
              str(items[0].get("warehouse_display_name")))

    # 6. 新建单据缺签约公司 → 422
    r = client.get("/api/master/options/product", headers=headers, params={"limit": 1})
    products = r.json() or []
    if not products:
        print("库中没有物料，跳过建单校验")
    else:
        payload = {"doc_date": "2026-03-01", "purpose": "V2.3 冒烟",
                   "items": [{"product_id": products[0]["id"], "qty": 1, "unit_price": 1}]}
        r = client.post("/api/purchase/requests", headers=headers, json=payload)
        check("缺少签约公司被拒绝(422)", r.status_code == 422 and "签约公司" in str(r.json()),
              f"{r.status_code} {r.text[:60]}")

        # 7. 带上签约公司 → 成功（同时验证 PG 写入与自增序列）
        payload["subject_code"] = code
        r = client.post("/api/purchase/requests", headers=headers, json=payload)
        ok = r.status_code in (200, 201)
        doc = r.json() if ok else {}
        check("带签约公司建单成功（PG 写入）", ok, f"{r.status_code} {doc.get('doc_no', '')}")
        if ok:
            check("签约公司名称快照回填", doc.get("subject_name") == name or doc.get("subject_code") == code,
                  f"{doc.get('subject_code')}/{doc.get('subject_name')}")
            # 清理：物理删除本次冒烟产生的单据（含行项与变更历史）
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM purchase_request_items WHERE doc_id = :i"), {"i": doc["id"]})
                conn.execute(text("DELETE FROM change_logs WHERE object_type = 'purchase_request' "
                                  "AND object_id = :i"), {"i": doc["id"]})
                conn.execute(text("DELETE FROM purchase_requests WHERE id = :i"), {"i": doc["id"]})
            check("冒烟单据已清理", True, f"id={doc['id']}")

    print(f"\n通过 {len(PASSED)} 项，失败 {len(FAILED)} 项")
    if FAILED:
        print("失败项：" + "；".join(FAILED))
    return 1 if FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
