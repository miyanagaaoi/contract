# 合同管理与跟踪系统（CTMS）— 文档索引

> 内网版合同台账与履约跟踪系统：采购 / 财务 / 项目管理 3~4 人使用。
> 开发方法：SDD（Specification-Driven Development，规格驱动开发）。
> 当前阶段：**V2.0（ERP 进销存改造）M1 权限与主数据地基、M2 采购线与库存过账均已交付**
> （M1：`pytest` + 冒烟 15/15；M2：冒烟 11/11、全量测试 232 passed；
> 见 [13-m1-acceptance.md](docs/13-m1-acceptance.md)、[14-m2-acceptance.md](docs/14-m2-acceptance.md)）；
> 下一步：M3 销售前端与导出 → M4 打印/看板/UAT。

## 文档导航

| 文档 | 内容 | 读者 |
|---|---|---|
| [00-sdd-process.md](docs/00-sdd-process.md) | SDD 流程说明：规格先行 → 实现 → 按验收场景验证 | 全体 |
| [01-requirements.md](docs/01-requirements.md) | **需求规格说明书**：功能/业务规则 BR/验收场景 AC/遗留问题 | 需求方、开发 |
| [02-system-design.md](docs/02-system-design.md) | **系统设计**：架构、ER 图、状态机、页面、API、备份 | 开发 |
| [03-development-plan.md](docs/03-development-plan.md) | **开发计划**：里程碑、任务分解、甘特、风险 | 项目经理、开发 |
| [04-tech-route.md](docs/04-tech-route.md) | **技术路线推介**：选型论证、部署两方案、演进路线 | 决策人 |
| [05-prototype-acceptance.md](docs/05-prototype-acceptance.md) | **原型验收报告**：AC-01~AC-11 全绿、复现命令、演示建议 | 全体 |
| [06-mvp2-adjustments.md](docs/06-mvp2-adjustments.md) | **MVP2 调整记录**：行项/导入/导出配置/框架标签/框架树的口径、实现与验收要点 | 全体 |
| [07-mvp3-adjustments.md](docs/07-mvp3-adjustments.md) | **MVP3 迭代记录**：自动编号/类型与主体字典/类型标签/系统设置页 | 全体 |
| [08-deployment.md](docs/08-deployment.md) | **正式版部署手册**：Linux Docker / Windows NSSM、PostgreSQL 切换、备份恢复演练 | 运维、决策人 |
| [09-baota-deploy.md](docs/09-baota-deploy.md) | **宝塔面板部署步骤**：环境/代码/前端构建/Supervisor/Nginx 反代/HTTPS/计划任务备份/升级 | 运维、决策人 |
| [10-docker-single.md](docs/10-docker-single.md) | **单容器 Docker**：build/save 成单个 tar → load 启动；/data 持久化与升级 | 运维、决策人 |
| [11-erp-requirements.md](docs/11-erp-requirements.md) | **V2.0 需求规格（ERP 进销存）**：账号角色权限、采购/销售/库存、盘点、验收场景 AC-V2-01~42 | 全体 |
| [12-erp-system-design.md](docs/12-erp-system-design.md) | **V2.0 详细设计**：权限模型、数据模型、过账与下推服务、接口清单、前端结构 | 开发 |
| [13-m1-acceptance.md](docs/13-m1-acceptance.md) | **V2.0 · M1 验收报告**：任务完成情况、交付物、验收证据、缺陷修复、人工验收清单 | 全体 |
| [14-m2-acceptance.md](docs/14-m2-acceptance.md) | **V2.0 · M2 验收报告**：采购线与库存过账（单据/下推/过账/盘点）的验收证据与清单 | 全体 |

## 关键决策记录（本轮已确认）

1. **SDD 定义**：Specification-Driven Development——行为规格化为开发与验收唯一依据。
2. **交付形态**：先做原型验证（P0 闭环），再决定正式路线；而非一步到位。
3. **部署**：公司内网单服务器、纯内网使用；服务器 OS 未定 → 提供 Linux/Docker 与 Windows 两套方案。
4. **附件**：初版仅上传/下载/预览，不做 OCR 与正文检索。
5. **进度**：经办人手动更新状态 + 全程留变更历史，不做审批流。
6. **框架合同**：一对多，1 框架挂 N 子合同。
7. **质保金**：跟踪生效日期、期限与到期提醒（站内看板），不跟踪释放审批。
8. **提醒**：站内首页看板（即将到期/已到期），不做邮件/IM 推送。
9. ~~**登录与角色**：不做登录功能、不区分角色（纯内网信任模型，打开即用）~~ → **V2.0 已推翻**：
   引入账号 + 角色 + 菜单/按钮权限 + 数据范围（见 `11`/`12`，M1 已交付）。
10. **存量**：从零录入，不做历史批量迁移。
11. **导出**：支持将当前筛选结果导出 Excel。
12. **付款**：仅维护"累计已付"单一字段，付款比例自动计算。
13. **版本纪律**：每完成一个功能（对应验收场景全绿）保存一次 Git 版本（见 `03-development-plan.md` §3.1）。
14. **业务口径**：Q1~Q8 全部按默认值确认并冻结 V1.0（付款比例=已付/合同金额、质保到期取当月最后一天、增加"已终止"状态、软删除+30 天内可恢复等，明细见 `01-requirements.md` §9）。
15. **术语澄清（prompt0.3）**："交付版本" = 正式版交付（即当前 P3）；"便签管理" = 标签管理（已并入系统设置页）。

## 当前阶段与下一步

1. ✅ 需求规格 V1.0 冻结（Q1~Q8）；P1 原型 MVP（AC-01~AC-11 全绿）；
2. ✅ MVP2 / MVP3 迭代（行项、导入导出、自动编号、类型与主体字典、系统设置页）；
3. ✅ P3 正式版准备（pytest、env 配置、备份脚本、部署手册）、Docker 单容器与宝塔部署文档；
4. ✅ **V2.0 M1（权限与主数据地基，T-V2-01~16）**：登录/令牌/权限/数据范围、组织·角色·账号、
   客户/供应商/商品类型/物料/计量单位/仓库、系统管理整合、合同甲乙方档案化与历史档案迁移；
   验收见 `13-m1-acceptance.md`；
5. ▶ 下一步：① 人工按 `13` §6 清单目视 UI 后打 tag `v2.0-m1`；
   ② 进入 **M2**：单据公共层 → 统一编号 → **库存过账服务** → 采购申请/采购单/入库单 → 库存明细。

## 开发快速开始（原型阶段）

### 方式一：双击脚本（推荐）

| 脚本 | 用途 |
|---|---|
| `setup.bat` | 首次初始化：创建 venv、安装前后端依赖、建库并写入演示数据（可重复执行） |
| `start-all.bat` | 一键启动：后端 `:8000` + 前端 `:5173`（`--host 0.0.0.0`，局域网可访问），随后自动打开浏览器 |

说明：若某端口已被占用（如已有实例在跑），脚本会跳过并直接复用；停止 = 关闭弹出的两个命令行窗口。

### 方式二：命令行（开发调试）

```bash
# 1) 首次（任选）
app\.venv\Scripts\python -m pip install -r app\requirements.txt   # 依赖
app\.venv\Scripts\python -m app.init_db --demo                    # 建库+演示数据（幂等）

# 2) 后端（FastAPI + SQLite）
app\.venv\Scripts\python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
#   → API 文档 http://127.0.0.1:8000/docs  健康检查 /api/health

# 3) 前端（Vue3 + Vite + Element Plus，/api 已代理到 8000）
cd web
npm install                          # 首次
npm run dev -- --host 0.0.0.0        # → http://localhost:5173
```

- 代码位置：`app/`（后端）、`web/`（前端）；数据文件 `app/data/ctms.db`、附件 `app/uploads/`（均已 gitignore）；
- **版本纪律**：每完成一个功能（验收场景全绿）提交一次 Git，格式 `feat: [AC-xx] 功能名`（见 `docs/03-development-plan.md` §3.1）；
- 无登录/无角色：纯内网使用，打开即用。

## 目录结构

```
D:\dsh\hetong\
├── README.md / .env.example / setup.bat / start-all.bat
├── prompt*.txt            (需求补充文件/占位)
├── docs\
│   ├── 00-sdd-process.md  01-requirements.md  02-system-design.md
│   ├── 03-development-plan.md  04-tech-route.md
│   └── 05-prototype-acceptance.md  06-mvp2-adjustments.md
│       07-mvp3-adjustments.md  08-deployment.md
├── app\                    (后端 FastAPI；.venv/data/uploads/backups 不入库)
│   ├── main.py  config.py  database.py  models.py  dicts.py  numbering.py
│   ├── db_migrate.py  init_db.py  tools\build_import_template.py
│   ├── routers\ (health/meta/tags/settings/dashboard/contracts/attachments/export/imports)
│   ├── tests\ (smoke_p0.py P0 冒烟 · test_unit.py pytest 单测)
│   └── requirements.txt  requirements-dev.txt  requirements-pg.txt
├── scripts\backup.ps1     (每日备份: SQLite+uploads, 30天保留)
├── deploy\                (Dockerfile / docker-compose.yml / nginx.conf)
├── import_template\       (导入模板样例.xlsx)
├── preview-mvp2.html      (MVP2 概念预览，可留存参考)
└── web\                    (前端 Vue3 + Vite + Element Plus)
    ├── package.json  vite.config.ts  index.html
    └── src\main.ts  App.vue  router\  api.ts  views\ (含 SettingsView)
```

> 代码随规格演进：完成的功能对应一次 Git 提交，规格文档变更同步提交。
> 生产部署见 `docs/08-deployment.md`；备份见 `scripts/backup.ps1`。
