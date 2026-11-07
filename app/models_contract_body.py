"""合同模板与正文（CR-045）：富文本正文 + 自定义字段占位符。

口径（PRD CR-045 已确认）：
- 模板正文为 HTML，字段占位符写作 `{{field_key}}`；字段定义 JSON：
  `[{key,label,type,required,placeholder,options}]`，type ∈ text/textarea/number/date/select；
- 生成合同时把字段值代入并**快照**保存到合同（`body_html` + `field_values` + `body_hash`），
  模板后续修改不影响已生成合同；
- 签署：我方在线签（复用账号手写签名）→ 上传对方线下签署扫描件 → 置生效；签署后正文只读。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


class ContractTemplate(Base):
    __tablename__ = "contract_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    contract_type: Mapped[str] = mapped_column(String(16), nullable=False, default="采购")
    body_html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    fields_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False,
                                                 server_default=func.now(), onupdate=func.now())
