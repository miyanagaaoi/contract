# 合同管理与跟踪系统（CTMS）— 文档索引

> 内网版合同台账与履约跟踪系统：采购 / 财务 / 项目管理 3~4 人使用。
> 开发方法：SDD（Specification-Driven Development，规格驱动开发）。
> 当前阶段：需求规格 **V1.0 已冻结**（Q1~Q8 已按默认值确认）。下一步：P1 原型开发。

## 文档导航

| 文档 | 内容 | 读者 |
|---|---|---|
| [00-sdd-process.md](docs/00-sdd-process.md) | SDD 流程说明：规格先行 → 实现 → 按验收场景验证 | 全体 |
| [01-requirements.md](docs/01-requirements.md) | **需求规格说明书**：功能/业务规则 BR/验收场景 AC/遗留问题 | 需求方、开发 |
| [02-system-design.md](docs/02-system-design.md) | **系统设计**：架构、ER 图、状态机、页面、API、备份 | 开发 |
| [03-development-plan.md](docs/03-development-plan.md) | **开发计划**：里程碑、任务分解、甘特、风险 | 项目经理、开发 |
| [04-tech-route.md](docs/04-tech-route.md) | **技术路线推介**：选型论证、部署两方案、演进路线 | 决策人 |

## 关键决策记录（本轮已确认）

1. **SDD 定义**：Specification-Driven Development——行为规格化为开发与验收唯一依据。
2. **交付形态**：先做原型验证（P0 闭环），再决定正式路线；而非一步到位。
3. **部署**：公司内网单服务器、纯内网使用；服务器 OS 未定 → 提供 Linux/Docker 与 Windows 两套方案。
4. **附件**：初版仅上传/下载/预览，不做 OCR 与正文检索。
5. **进度**：经办人手动更新状态 + 全程留变更历史，不做审批流。
6. **框架合同**：一对多，1 框架挂 N 子合同。
7. **质保金**：跟踪生效日期、期限与到期提醒（站内看板），不跟踪释放审批。
8. **提醒**：站内首页看板（即将到期/已到期），不做邮件/IM 推送。
9. **登录与角色**：不做登录功能、不区分角色（纯内网信任模型，打开即用）；操作追溯由"经办人"字段 + 变更历史（时间/前后值）承担。
10. **存量**：从零录入，不做历史批量迁移。
11. **导出**：支持将当前筛选结果导出 Excel。
12. **付款**：仅维护"累计已付"单一字段，付款比例自动计算。
13. **版本纪律**：每完成一个功能（对应验收场景全绿）保存一次 Git 版本（见 `03-development-plan.md` §3.1）。
14. **业务口径**：Q1~Q8 全部按默认值确认并冻结 V1.0（付款比例=已付/合同金额、质保到期取当月最后一天、增加"已终止"状态、软删除+30 天内可恢复等，明细见 `01-requirements.md` §9）。

## 下一步（建议顺序）

1. （已完成）需求规格 **V1.0 冻结**：Q1~Q8 按默认值确认（见 `01-requirements.md` §9 决策记录）；
2. 建议做一次 30~60 分钟规格评审（按 `00-sdd-process.md` 4.1），与采购/财务/项目管理对齐口径理解；
3. 按 `03-development-plan.md` P1 开始原型开发（T1 Git 初始化 → T2 数据模型 → …）；
4. 原型完成后按 `01-requirements.md` §8 标准组织三类用户演示，形成 Go/No-Go 决策。

## 开发快速开始（原型阶段）

```bash
# 1) 后端（FastAPI + SQLite）
cd app
python -m venv .venv                 # 首次
.venv\Scripts\python -m pip install -r requirements.txt   # 首次
.venv\Scripts\python -m app.init_db --demo   # 建表 + 字典种子 + 演示数据
.venv\Scripts\python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
#   → API 文档 http://127.0.0.1:8000/docs  健康检查 /api/health

# 2) 前端（Vue3 + Vite + Element Plus）
cd web
npm install                          # 首次
npm run dev                          # → http://127.0.0.1:5173（/api 已代理到 8000）
```

- 代码位置：`app/`（后端）、`web/`（前端）；数据文件 `app/data/ctms.db`、附件 `app/uploads/`（均已 gitignore）；
- **版本纪律**：每完成一个功能（验收场景全绿）提交一次 Git，格式 `feat: [AC-xx] 功能名`（见 `docs/03-development-plan.md` §3.1）；
- 无登录/无角色：纯内网使用，打开即用。

## 目录结构

```
D:\dsh\hetong\
├── README.md
├── prompt.txt              (空，需求来源占位)
├── docs\
│   ├── 00-sdd-process.md
│   ├── 01-requirements.md
│   ├── 02-system-design.md
│   ├── 03-development-plan.md
│   └── 04-tech-route.md
├── app\                    (后端 FastAPI；.venv/data/uploads 不入库)
│   ├── main.py  config.py  database.py  models.py  init_db.py
│   └── routers\health.py
└── web\                    (前端 Vue3 + Vite + Element Plus)
    ├── package.json  vite.config.ts  index.html
    └── src\main.ts  App.vue  router\  views\
```

> 代码随规格演进：完成的功能对应一次 Git 提交，规格文档变更同步提交。
