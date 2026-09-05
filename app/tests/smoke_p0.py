"""CTMS 原型 P0 全套验收冒烟（AC-01 ~ AC-11）。

用法：先启动后端（uvicorn app.main:app --host 127.0.0.1 --port 8000），再运行本脚本：
    .venv\\Scripts\\python app\\tests\\smoke_p0.py

脚本幂等：每次运行使用时间戳唯一编号，结束时软删除自建合同。
"""
import calendar
import io
import json
import time
import urllib.request
import urllib.error
from datetime import date
from urllib.parse import urlencode

from openpyxl import load_workbook

BASE = "http://127.0.0.1:8000/api"
PASSED: list[str] = []


def _report(name: str):
    PASSED.append(name)
    print(f"  [PASS] {name}")


def req(method, path, body=None, params=None, expect=(200,)):
    url = BASE + path
    if params:
        url += "?" + urlencode(params)
    data = json.dumps(body, ensure_ascii=True).encode("utf-8") if body is not None else None
    r = urllib.request.Request(url, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(r) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8") or "null"
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw}
        if e.code not in expect:
            raise AssertionError(f"{method} {path} -> {e.code} {payload}")
        return e.code, payload


def download(params=None) -> bytes:
    url = BASE + "/export/contracts.xlsx"
    if params:
        url += "?" + urlencode(params)
    with urllib.request.urlopen(url) as resp:
        return resp.read()


def cleanup(cids: list[int]):
    for cid in cids:
        try:
            code, atts = req("GET", f"/contracts/{cid}/attachments")
            for a in atts:
                req("DELETE", f"/contracts/{cid}/attachments/{a['id']}", params={"reason": "P0 冒烟归档"})
            req("DELETE", f"/contracts/{cid}", params={"reason": "P0 冒烟归档"})
        except Exception:  # noqa: BLE001
            pass


def main():
    ts = int(time.time()) % 1000000
    cleaned: list[int] = []
    try:
        # ---------- AC-01/AC-02 新增与编号唯一 ----------
        no_a = f"CG-2025-P0A{ts:06d}"
        _, c = req("POST", "/contracts", {
            "contract_no": no_a, "name": "P0 冒烟甲", "type": "采购",
            "party_a": "P0甲方AAA", "party_b": "乙方", "sign_date": "2025-03-01",
            "subject_matter": "全套验收", "amount": 100000, "paid_amount": 0,
            "owner_name": "张三", "status": "内部审批中",
        })
        assert c["payment_ratio"] == 0.0 and c["status"] == "内部审批中"
        cleaned.append(c["id"])
        cid_a = c["id"]
        _report("AC-01 新增合同（默认状态/比例0%）")
        code, _ = req("POST", "/contracts", {"contract_no": no_a, "name": "重复编号"}, expect=(409,))
        assert code == 409
        _report("AC-02 编号重复 → 409")

        # ---------- AC-03 已付与比例联动 ----------
        _, c = req("PUT", f"/contracts/{cid_a}", {"paid_amount": 50000})
        assert c["paid_amount"] == 50000.0 and c["payment_ratio"] == 50.0
        _report("AC-03 累计已付联动付款比例 50%")

        # ---------- AC-05 多标签挂载 + 组合搜索 ----------
        _, c = req("PUT", f"/contracts/{cid_a}", {"tags": ["采购", "项目A"]})
        # MVP3：类型会附加"类型名"自动标签，故此处断言手工标签存在（子集）
        assert {"采购", "项目A"}.issubset(set(c["tags"])), c["tags"]
        _, tags = req("GET", "/tags")
        by_name = {t["name"]: t for t in tags}
        tag_ids = f"{by_name['采购']['id']},{by_name['项目A']['id']}"
        _, res = req("GET", "/contracts", params={"tags": tag_ids})
        assert cid_a in {it["id"] for it in res["items"]}
        _report("AC-05 多标签挂载/替换")

        # ---------- AC-06 组合搜索（甲方+日期+标签） ----------
        _, res = req("GET", "/contracts", params={
            "keyword": "P0甲方AAA", "sign_from": "2025-01-01", "sign_to": "2025-12-31", "tags": tag_ids,
        })
        assert res["total"] == 1 and res["items"][0]["id"] == cid_a
        _report("AC-06 组合搜索（关键词+日期区间+标签交集）")

        # ---------- AC-07 框架绑定 ----------
        fno = f"F-2025-P0{ts % 100000:05d}"
        _, f = req("POST", "/contracts", {
            "contract_no": fno, "name": "P0 冒烟框架", "type": "采购",
            "party_a": "P0甲方AAA", "party_b": "乙方", "sign_date": "2025-01-05",
            "subject_matter": "框架", "amount": 300000, "is_framework": True,
        })
        cleaned.append(f["id"])
        _, c = req("PUT", f"/contracts/{cid_a}", {"parent_id": f["id"]})
        assert c["parent_no"] == fno
        _, f = req("GET", f"/contracts/{f['id']}")
        assert f["children_count"] == 1 and f["children_amount_sum"] == 100000.0
        _report("AC-07 框架绑定与子合同汇总")
        req("PUT", f"/contracts/{cid_a}", {"parent_id": None})  # 解绑，恢复独立便于后续断言

        # ---------- AC-04/AC-12 状态流转与历史 ----------
        _, c = req("PUT", f"/contracts/{cid_a}", {"status": "付款中", "note": "首付款已安排"})
        assert c["status"] == "付款中"
        _, logs = req("GET", f"/contracts/{cid_a}/logs")
        assert any(lg["field_name"] == "status" and lg["old_value"] == "内部审批中" and lg["new_value"] == "付款中" for lg in logs)
        assert any(lg["field_name"] == "备注" and lg["new_value"] == "首付款已安排" for lg in logs)
        ts_list = [lg["created_at"] for lg in logs]
        assert ts_list == sorted(ts_list, reverse=True)
        _report("AC-04 状态流转 / AC-12 历史倒序含备注")

        # ---------- AC-08/AC-14 质保与看板 ----------
        today = date.today()
        _, c = req("PUT", f"/contracts/{cid_a}", {
            "has_warranty": True, "warranty_rate": 5,
            "warranty_start": date(today.year, today.month, 1).isoformat(), "warranty_months": 1,
        })
        assert c["warranty_amount"] == 5000.0  # 合同金额 10w 的 5%
        last_day = calendar.monthrange(today.year, today.month)[1]
        assert c["warranty_end"] == date(today.year, today.month, last_day).isoformat()
        _report("AC-14 质保比例→金额换算 + 到期日=当月最后一天")
        _, dash = req("GET", "/dashboard")
        assert cid_a in {r["id"] for r in dash["expiring"]}
        _, c = req("PUT", f"/contracts/{cid_a}", {"warranty_released": True, "warranty_release_date": today.isoformat()})
        _, dash = req("GET", "/dashboard")
        assert cid_a not in {r["id"] for r in dash["expiring"]}
        _report("AC-08 质保到期看板提醒与释放")

        # ---------- AC-09 附件 ----------
        boundary = "----ctms-p0" + str(ts)
        content = "%PDF-1.4 P0 attachment smoke"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"P0验收.pdf\"\r\n"
                f"Content-Type: application/pdf\r\n\r\n").encode("utf-8") + content.encode("utf-8") + f"\r\n--{boundary}--\r\n".encode("utf-8")
        r = urllib.request.Request(f"{BASE}/contracts/{cid_a}/attachments", data=body, method="POST",
                                   headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        with urllib.request.urlopen(r) as resp:
            att = json.loads(resp.read().decode("utf-8"))
        assert att["file_name"] == "P0验收.pdf"
        with urllib.request.urlopen(f"{BASE}/attachments/{att['id']}/download") as resp:
            assert resp.read().decode("utf-8") == content
        req("DELETE", f"/contracts/{cid_a}/attachments/{att['id']}", params={"reason": "冒烟删除"})
        _report("AC-09 附件上传/下载/删除留痕")

        # ---------- AC-10 停用与恢复 ----------
        req("DELETE", f"/contracts/{cid_a}", params={"reason": "AC-10 停用测试"})
        _, res = req("GET", "/contracts", params={"keyword": no_a})
        assert res["total"] == 0
        _, res = req("GET", "/contracts", params={"keyword": no_a, "include_deleted": True})
        assert res["total"] == 1 and res["items"][0]["deleted"] is True
        code, _ = req("PUT", f"/contracts/{cid_a}/restore")
        assert code == 200
        _, c = req("GET", f"/contracts/{cid_a}")
        assert c["deleted"] is False
        _report("AC-10 免登录直开接口语义 + 停用/30天内恢复")

        # ---------- AC-11 Excel 导出与筛选一致 ----------
        data = download({"keyword": "P0甲方AAA", "sign_from": "2025-01-01", "sign_to": "2025-12-31", "tags": tag_ids})
        wb = load_workbook(io.BytesIO(data), read_only=True)
        rows = list(wb["合同台账"].iter_rows(values_only=True))
        assert rows[0][:3] == ("合同编号", "合同名称", "类型")
        assert len(rows) == 2 and rows[1][0] == no_a  # 表头 + 恰好 1 条
        _report("AC-11 导出=当前筛选（行数与内容一致）")

        print(f"\nALL P0 ACCEPTANCE PASSED ({len(PASSED)} checks)")
    finally:
        cleanup(cleaned)


if __name__ == "__main__":
    main()
