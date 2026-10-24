"""开发环境：清空全部**业务数据**（保留账号/角色/权限/组织/字典/系统设置）。

用法：
    python -m app.tools.purge_business_data              # 清空业务数据（会先自动备份 SQLite 文件）
    python -m app.tools.purge_business_data --yes        # 跳过交互确认
    python -m app.tools.purge_business_data --keep-master  # 保留物料/供应商/客户/仓库等主数据

清理范围（业务表）：
  合同：contracts / contract_items / contract_tag / tags / attachments / change_logs
  采购：purchase_requests(+items) / purchase_orders(+items)
  销售：sales_requests(+items) / sales_orders(+items)
  库存：stock_in_orders(+items) / stock_out_orders(+items) / stock_takes(+items)
        / stock_transfers(+items) / stock_ledger / stocks
  财务：payment_orders(+alloc) / receipt_orders(+alloc) / invoices(+alloc) / invoice_sync_logs
  其他：notifications / operation_logs / party_drafts
保留：users / roles / role_permissions / user_identities / user_roles / org_units /
      kv_settings / print_templates /（可选）主数据：products / product_types / uoms /
      suppliers / customers / warehouses

⚠️ 只用于开发/演示环境；生产库请勿执行。
"""
from __future__ import annotations

import shutil
import sys
import time
from pathlib import Path

from sqlalchemy import delete, text

from app import config
from app.database import SessionLocal, engine
from app.models import Attachment, ChangeLog, Contract, ContractItem, Tag
from app.models_doc import (
    Invoice, InvoiceAllocation, InvoiceSyncLog, PaymentAllocation, PaymentOrder,
    PurchaseOrder, PurchaseOrderItem, PurchaseRequest, PurchaseRequestItem,
    ReceiptAllocation, ReceiptOrder, SalesOrder, SalesOrderItem, SalesRequest,
    SalesRequestItem, StockInOrder, StockInOrderItem, StockOutOrder, StockOutOrderItem,
    StockTake, StockTakeItem, StockTransfer, StockTransferItem,
)
from app.models_master import Customer, Product, ProductType, Supplier, Uom, Warehouse
from app.models_notify import Notification
from app.models_stock import Stock, StockLedger

# 删除顺序：先子表（含核销/行项），后主表；关联表单独处理
ORDER = [
    ("invoice_allocations", InvoiceAllocation),
    ("payment_allocations", PaymentAllocation),
    ("receipt_allocations", ReceiptAllocation),
    ("invoices", Invoice),
    ("invoice_sync_logs", InvoiceSyncLog),
    ("payment_orders", PaymentOrder),
    ("receipt_orders", ReceiptOrder),
    ("stock_in_order_items", StockInOrderItem),
    ("stock_out_order_items", StockOutOrderItem),
    ("stock_take_items", StockTakeItem),
    ("stock_transfer_items", StockTransferItem),
    ("purchase_order_items", PurchaseOrderItem),
    ("purchase_request_items", PurchaseRequestItem),
    ("sales_order_items", SalesOrderItem),
    ("sales_request_items", SalesRequestItem),
    ("stock_in_orders", StockInOrder),
    ("stock_out_orders", StockOutOrder),
    ("stock_takes", StockTake),
    ("stock_transfers", StockTransfer),
    ("purchase_orders", PurchaseOrder),
    ("purchase_requests", PurchaseRequest),
    ("sales_orders", SalesOrder),
    ("sales_requests", SalesRequest),
    ("stock_ledger", StockLedger),
    ("stocks", Stock),
    ("contract_items", ContractItem),
    ("contracts", Contract),
    ("attachments", Attachment),
    ("change_logs", ChangeLog),
    ("notifications", Notification),
]
MASTERS = [("products", Product), ("product_types", ProductType), ("uoms", Uom),
           ("suppliers", Supplier), ("customers", Customer), ("warehouses", Warehouse)]
# 关联表 / 杂项（用原生 SQL，避免 ORM 表对象差异）
RAW = ["contract_tag", "tags", "party_drafts", "operation_logs"]


def _backup_sqlite() -> Path | None:
    """SQLite 直接复制文件；非 SQLite 返回 None（由调用方确认已有备份）。"""
    if not config.is_sqlite():
        return None
    src = Path(config.DB_FILE)
    if not src.is_file():
        return None
    dest_dir = Path(config.BASE_DIR) / "backups"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"ctms_before_purge_{time.strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(src, dest)
    return dest


def purge(keep_master: bool = False) -> dict:
    """逐表小事务删除（避免 SQLite 大事务临时文件/锁问题）。"""
    removed: dict[str, int] = {}
    with SessionLocal() as db:
        # SQLite：临时表放内存、设置 busy 等待，避免 "unable to open database file"
        try:
            db.execute(text("PRAGMA temp_store=MEMORY"))
            db.execute(text("PRAGMA busy_timeout=10000"))
        except Exception:
            pass
        db.commit()
        for name, model in ORDER:
            try:
                removed[name] = int(db.execute(delete(model)).rowcount or 0)
                db.commit()
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                removed[f"ERR:{name}"] = 1
                print(f"[WARN] 清理 {name} 失败: {exc}")
        for table in RAW:
            try:
                removed[table] = int(db.execute(text(f"DELETE FROM {table}")).rowcount or 0)
                db.commit()
            except Exception:
                db.rollback()
        if not keep_master:
            for name, model in MASTERS:
                try:
                    removed[name] = int(db.execute(delete(model)).rowcount or 0)
                    db.commit()
                except Exception as exc:  # noqa: BLE001
                    db.rollback()
                    print(f"[WARN] 清理主数据 {name} 失败: {exc}")
        try:
            db.execute(text("VACUUM"))
        except Exception:
            pass
    # 附件文件清掉（仅 uploads 下，保留目录）
    upload_dir = Path(config.UPLOAD_DIR)
    files = 0
    if upload_dir.is_dir():
        for p in upload_dir.rglob("*"):
            if p.is_file():
                try:
                    p.unlink()
                    files += 1
                except OSError:
                    pass
    removed["_upload_files"] = files
    return removed


def main() -> None:
    if "--yes" not in sys.argv:
        print("将清空业务数据（保留账号/角色/字典/系统设置）。开发环境专用。")
        answer = input("输入 YES 继续: ").strip()
        if answer != "YES":
            print("已取消。")
            return
    backup = _backup_sqlite()
    print("数据库备份:", backup or "（非 SQLite，未自动备份）")
    removed = purge(keep_master="--keep-master" in sys.argv)
    total = sum(v for k, v in removed.items() if not k.startswith("_"))
    print("删除行数合计:", total, "| 附件文件:", removed.get("_upload_files", 0))
    detail = {k: v for k, v in removed.items() if v and not k.startswith("_")}
    for k in sorted(detail):
        print(f"  {k:26s} {detail[k]}")


if __name__ == "__main__":
    main()
