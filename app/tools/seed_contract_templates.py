"""内置合同模板种子（CR-045）：以业务提供的《购销服务合同》为参考。

- 仅当 `contract_templates` **没有任何模板**时插入（幂等，不覆盖管理员已改内容）；
- 正文为 HTML，字段占位符 `{{key}}`；产品明细引用系统合同行项（模板内不重复表格）；
- 字段可在「合同管理 → 合同模板」里由管理员修改（CR-045）。
"""
from __future__ import annotations

import json
from datetime import datetime

from ..database import SessionLocal
from ..models_contract_body import ContractTemplate

TEMPLATE_NAME = "购销服务合同（标准）"

FIELDS: list[dict] = [
    {"key": "contract_no", "label": "合同编号", "type": "text", "required": False},
    {"key": "sign_place", "label": "签订地点", "type": "text", "required": True,
     "placeholder": "如：山西省太原市"},
    {"key": "party_a", "label": "甲方（购货方）", "type": "text", "required": True},
    {"key": "party_b", "label": "乙方（销货方）", "type": "text", "required": True},
    {"key": "sign_date", "label": "签订日期", "type": "date", "required": True},
    {"key": "total_amount", "label": "合同总金额（元）", "type": "number", "required": True},
    {"key": "delivery_address", "label": "交货地址", "type": "text", "required": True},
    {"key": "receiver", "label": "收货人", "type": "text", "required": True},
    {"key": "receiver_phone", "label": "收货联系电话", "type": "text", "required": True},
    {"key": "prepay_ratio", "label": "预付款比例(%)", "type": "number", "required": True},
    {"key": "balance_ratio", "label": "发货前付款比例(%)", "type": "number", "required": True},
    {"key": "invoice_days", "label": "发票开具期限（工作日）", "type": "number", "required": True},
    {"key": "warranty_years", "label": "质保期（年）", "type": "number", "required": True},
    {"key": "penalty_rate", "label": "逾期违约金比例(%/日)", "type": "number", "required": True},
    {"key": "penalty_days", "label": "逾期赔偿触发天数", "type": "number", "required": True},
    {"key": "copies_a", "label": "甲方执合同份数", "type": "text", "required": True},
    {"key": "copies_b", "label": "乙方执合同份数", "type": "text", "required": True},
    {"key": "arbitration_place", "label": "仲裁/诉讼地", "type": "text", "required": True},
]

BODY_HTML = """<h1>{{contract_no}} 购销服务合同</h1>
<p>签订地点：{{sign_place}}</p>
<p>购货方（甲方）：{{party_a}}</p>
<p>销货方（乙方）：{{party_b}}</p>
<p>为保障买卖双方的合法权益，根据《中华人民共和国民法典》及有关法律法规规定，双方经友好协商达成以下条款，签订本合同。</p>
<h2>第一条 合同标的内容</h2>
<p>产品名称、规格型号、单位、数量、含税单价（到货价）、总金额、供货时间见本合同附表的行项清单；<b>本金额含税含运费</b>，合同总金额：<b>{{total_amount}} 元</b>。</p>
<h2>第二条 产品技术标准及质量保证</h2>
<p>1、符合国标/协议标准。</p>
<p>2、乙方必须保证该产品为原装新产品，不得有瑕疵，否则应予以退货或换货，且要具备完整的产品证书、质检报告等相关文件。到货后由买卖双方按照甲方企业要求标准检验验收。符合附件《技术规范指标》中各项要求。</p>
<h2>第三条 包装、包装物的供应与回收</h2>
<p>/</p>
<h2>第四条 随机的必备品、配件、工具数量及供应办法</h2>
<p>/</p>
<h2>第五条 合理损耗标准及计算办法</h2>
<p>/</p>
<h2>第六条 供货地点及风险转移</h2>
<p>1、供货地点：请严格按收货地点发货。交货地址：{{delivery_address}}（收件人：{{receiver}}，电话：{{receiver_phone}}）。</p>
<p>2、运输方式：送货上门，运费由乙方承担；甲方不承担在供货地点和约定运输方式以外的任何搬运、移动产品的责任，期间所造成的损害与甲方无关。</p>
<p>3、货物风险责任由双方共同验收合格后转移，以验收单签字为准。</p>
<h2>第七条 付款方式以及发货方式</h2>
<p>1、合同签订后甲方支付乙方合同总价款的 {{prepay_ratio}}% 作为预付款，发货前付款 {{balance_ratio}}%。</p>
<h2>第八条 发票出具</h2>
<p>乙方应在甲方支付合同约定的发货款之日起 {{invoice_days}} 个工作日内，无条件给甲方开具全额增值税专用发票，作为甲方结算的依据（开发票时产品的品名、规格必须与合同中产品的品名、规格一致）。</p>
<h2>第九条 质量保证期及售后服务</h2>
<p>1、产品质保期：{{warranty_years}} 年。</p>
<p>2、质保期内售后服务：质保期间出现质量问题，乙方提供换货服务。</p>
<h2>第十条 履约保证</h2>
<p>1、双方约定乙方履约保证金为 / 元，作为双方合作的保障。如合作期内无违约及质量异议，合作期满后 / 个工作日内无息退还。</p>
<p>2、乙方保证向甲方提供产品的质量、规格、数量等符合本合同规定的要求。</p>
<p>3、乙方保证对其所出售的商品拥有合法的权利，不存在任何第三方的权利请求；否则造成的全部损失由乙方承担。</p>
<p>4、乙方交付的产品不符合同规定要求的，甲方有权拒收或退货，由此产生的损失及法律责任由乙方承担。</p>
<p>5、乙方未按约定时间发货，每逾期一日，应向甲方支付合同总价 {{penalty_rate}}% 的违约金；逾期超过 {{penalty_days}} 日，造成损失的，乙方应赔偿相应损失。</p>
<h2>第十一条 不可抗力</h2>
<p>本合同所指的不可抗力是指甲乙双方不能预见、不能避免并不能克服的客观情况。遇到不可抗力的一方应及时书面通知另一方，并提供有关机构关于不可抗力的有效证明，在力所能及的范围内迅速采取措施，尽力减少损失。双方应视不可抗力的影响程度分别处理，所造成的损失各自承担。</p>
<h2>第十二条 争议解决</h2>
<p>本合同在履行过程中出现的争议，甲乙双方应及时协商解决；协商不成时，可向{{arbitration_place}}仲裁委员会申请调解；协商或调解不成的，依法向有管辖权的人民法院起诉。</p>
<h2>第十三条 其他事项</h2>
<p>本合同正本一式两份，甲方执 {{copies_a}} 份，乙方执 {{copies_b}} 份，每份均有同等法律效力。</p>
<p style="text-align:right">签订时间：{{sign_date}}</p>
<p style="margin-top:48px">甲方（盖章）：{{party_a}}　　　乙方（盖章）：{{party_b}}</p>
<p>甲方代表（签字）：　　　　　　　　乙方代表（签字）：</p>
"""


def seed_builtin_templates() -> int:
    """按名称幂等插入内置模板；返回插入条数（已存在则 0）。"""
    with SessionLocal() as db:
        # 按名称幂等：已存在同名模板则跳过（不覆盖管理员修改）
        exists = (db.query(ContractTemplate)
                  .filter(ContractTemplate.name == TEMPLATE_NAME).first())
        if exists is not None:
            return 0
        db.add(ContractTemplate(
            name=TEMPLATE_NAME, contract_type="采购", body_html=BODY_HTML,
            fields_json=json.dumps(FIELDS, ensure_ascii=False),
            created_by_name="系统内置", enabled=True,
            created_at=datetime.now(), updated_at=datetime.now(),
        ))
        db.commit()
        return 1


if __name__ == "__main__":
    print("内置合同模板插入：", seed_builtin_templates())
