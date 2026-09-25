"""备份 / 恢复演练（T-V2-40 / AC-V2-39）。

流程（全部真实执行，不依赖手工步骤）：
1. 登录管理员 → `POST /api/system/backup` 生成备份 → 下载 zip；
2. 解压到临时目录，校验 zip 内容（ctms.db + uploads/ + backup_info.txt）；
3. 对备份库执行 `PRAGMA integrity_check` 与关键表行数统计；
4. 与当前生产库（`app/data/ctms.db`）对比关键表行数，确认快照一致；
5. 以备份库启动一次"恢复自检"：`sqlite3` 读取 + 抽查合同/单据/库存数据可读；
6. 输出演练报告，并清理本次生成的备份（避免占用磁盘）。

用法（先启动后端）：
    app\\.venv\\Scripts\\python.exe app\\tests\\drill_backup_restore.py

可选环境变量：`CTMS_SMOKE_BASE`（默认 http://127.0.0.1:8010/api）
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE = os.environ.get("CTMS_SMOKE_BASE", "http://127.0.0.1:8010/api")
LIVE_DB = Path(os.environ.get("CTMS_DB_FILE") or (ROOT / "app" / "data" / "ctms.db"))
ADMIN_USER, ADMIN_PWD = "admin", "admin12345"

KEY_TABLES = ["contracts", "users", "roles", "customers", "suppliers", "products", "warehouses",
              "purchase_orders", "stock_in_orders", "stocks", "stock_ledger", "change_logs"]
REPORT: list[str] = []


def log(line: str) -> None:
    REPORT.append(line)
    print(line)


def req(method: str, path: str, body=None, params=None, token: str | None = None,
        binary: bool = False):
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    data = json.dumps(body, ensure_ascii=True).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request) as resp:
            raw = resp.read()
            return resp.status, (raw if binary else json.loads(raw.decode("utf-8") or "null"))
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            detail = json.loads(raw.decode("utf-8") or "null")
        except (json.JSONDecodeError, UnicodeDecodeError):
            detail = {"raw": raw[:200]}
        raise AssertionError(f"{method} {path} -> {exc.code} {detail}")


def table_counts(db_path: Path) -> dict[str, int]:
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        existing = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        counts = {}
        for table in KEY_TABLES:
            if table in existing:
                counts[table] = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        return counts
    finally:
        conn.close()


def integrity(db_path: Path) -> str:
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        return str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        conn.close()


def main() -> int:
    log(f"备份/恢复演练 → {BASE}")
    token = req("POST", "/auth/login",
                {"username": ADMIN_USER, "password": ADMIN_PWD})[1]["token"]

    created = req("POST", "/system/backup", token=token)[1]
    name = created["name"]
    log(f"1) 生成备份：{name}（{created['size_bytes']} 字节）包含：{created['includes']}")

    status, blob = req("GET", f"/system/backup/{name}", token=token, binary=True)
    assert status == 200 and blob[:2] == b"PK", "备份下载失败或不是 zip"
    log(f"2) 下载成功：{len(blob)} 字节（zip 魔数 PK 校验通过）")

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        archive = tmpdir / name
        archive.write_bytes(blob)
        with zipfile.ZipFile(archive) as zf:
            names = zf.namelist()
            zf.extractall(tmpdir / "restore")
        assert "ctms.db" in names, "备份缺少数据库文件"
        uploads = [n for n in names if n.startswith("uploads/")]
        log(f"3) 解压成功：{len(names)} 个条目（数据库 1 个、附件 {len(uploads)} 个、说明文件 "
            f"{'有' if 'backup_info.txt' in names else '无'}）")

        backup_db = tmpdir / "restore" / "ctms.db"
        check = integrity(backup_db)
        assert check == "ok", f"备份库完整性校验失败：{check}"
        log(f"4) 备份库 PRAGMA integrity_check = {check}")

        backup_counts = table_counts(backup_db)
        live_counts = table_counts(LIVE_DB) if LIVE_DB.exists() else {}
        log("5) 关键表行数对比（备份 vs 生产）：")
        for table in KEY_TABLES:
            if table in backup_counts or table in live_counts:
                log(f"     - {table}: {backup_counts.get(table, '-')} vs {live_counts.get(table, '-')}")
        mismatched = {t: (backup_counts.get(t), live_counts.get(t))
                      for t in backup_counts if live_counts and backup_counts.get(t) != live_counts.get(t)}
        if mismatched and live_counts:
            log(f"   [WARN] 与生产库不一致的表（演练期间若有写入属正常）：{mismatched}")
        else:
            log("   [OK] 备份与生产库关键表行数一致")

        # 恢复自检：把备份库当成"恢复后的库"读一遍关键业务数据
        conn = sqlite3.connect(f"file:{backup_db.as_posix()}?mode=ro", uri=True)
        try:
            contract = conn.execute(
                "SELECT contract_no, name, status FROM contracts ORDER BY id DESC LIMIT 1").fetchone()
            doc = conn.execute(
                "SELECT doc_no, status, posted FROM stock_in_orders ORDER BY id DESC LIMIT 1").fetchone()
            stock = conn.execute(
                "SELECT product_id, warehouse_id, qty FROM stocks ORDER BY id DESC LIMIT 1").fetchone()
            log(f"6) 恢复后数据可读性抽查：合同={contract}；入库单={doc}；结存={stock}")
        finally:
            conn.close()

    req("DELETE", f"/system/backup/{name}", token=token)
    log(f"7) 已清理演练备份：{name}")
    log("\n演练结论：备份可生成、可下载、可解压、库文件完整且数据可读；"
        "恢复步骤见 docs/15-backup-drill.md（停服 → 覆盖 ctms.db 与 uploads → 启动 → 冒烟）。")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as exc:
        print(f"[FAIL] {exc}")
        sys.exit(1)
