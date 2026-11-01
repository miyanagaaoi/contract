# CTMS · 合同管理与跟踪系统

内网合同台账 + 采购/销售/库存/财务的轻量 ERP。后端 FastAPI + SQLAlchemy（SQLite / PostgreSQL），
前端 Vue3 + Element Plus，单容器 Docker 部署。

## 当前状态

- **版本**：`2.6.7`（`app/config.py: APP_VERSION`；含 CR-025 行项修正、CR-026 发票上传识别、CR-028 白屏修复、CR-029 库存总额度口径、
  CR-031 单价可改、CR-032 金额增量列与发票方向识别）
- **质量基线**：`pytest` **538 passed**；前端 `vite build` 通过
- **开发库数据**：已全量清空业务数据（保留账号/角色/字典），仅含 `DEMO27` 10 批次演示数据；
  清理工具 `python -m app.tools.purge_business_data --yes`（自动备份到 `app/backups/`）
- **部署**：Docker 单容器，外部 PostgreSQL（`192.168.81.50:5432/ctms`），群晖 Container Manager；端口 9000；
  全量部署模板 `deploy/docker-compose.full.yml`（核心镜像）/ `full-with-db.yml`（含内置 PG）
- **在跑的能力**：合同台账与履约、采购/销售/库存过账、财务（付款/收款/发票）、
  发票上传识别（单张 PDF / ZIP，自动入库并挂原始文件）、批次配对报表（正常匹配 / 红冲 / 无批次出库分类）、
  全单据行项物料树形选择（含悬停档案信息）、出库单退库、打印与电子签名；
  库存明细金额列「当前库存总额度」= FIFO 批次剩余金额（与批次配对报表同源）；
  入库/出库/调拨单行项单价可手工修改（金额自动重算，审核后锁定）；
  批次报表默认本月 + 导出超限提示 + 读路径缓存；采购退货单 / 销售退货单（关联原单、回冲收发货进度）；库存成本口径可切换 FIFO / 移动加权；发票支持自动匹配采购单核销；附件内容去重；`/api/health` 含 DB 延迟/磁盘/运行时长
- **本机脚本**：`setup.bat`（`check`/`demo`）、`start-all.bat`（`--rebuild`/`--no-open`）、
  `scripts/restart-backend.bat`、`scripts/stop-backend.bat`（仅操作 CTMS，拒绝误杀其它程序）；
  演示数据 `python -m app.tools.seed_stock_demo [--report|--purge]`

## 已知问题

- 发票同步通道已**移除**（CR-026）：只保留上传识别，不再需要 Playwright/浏览器插件；
  浏览器桥插件（CR-015）与分包交付（CR-007）随之停用
- 飞书 App Secret、PG 密码曾进 git 历史（已清理）→ **待轮换**（TODO-002）
- 群晖等面板只能导入镜像、不能从 Git build → 用 `deploy/docker-compose.synology.yml`（TODO-003）
- 库存金额为「剩余数量 × 批次入库单价」的近似口径，非移动加权成本（见 PRD CR-011）

## 下一步

1. 轮换 PG 密码与飞书 App Secret，并同步群晖 `.env`（TODO-002）
2. 群晖上完成 2.6.2 部署验证：`/api/health` 返回 `2.6.2`、发票上传识别与批次报表可用
   （批次报表可先用 `seed_stock_demo` 造数据验收，见 PRD CR-017）
4. 待确认想法：物料拼音搜索（TODO-004）、批次报表按出库单汇总打印（TODO-005）
5. 验证上传识别：单张数电票 PDF 的字段解析准确率（不同版式/扫描件）
6. 打包发版：镜像随改动自动构建（当前 `ctms:2.6.6`），等你确认后导出发布包
   （`scripts\export-docker.bat 2.6.6`）
7. 业务闭环（CR-034/037/038：退货、成本口径、发票自动匹配已完成）：下一步 审批/盘点/预警；
   体验改进见 CR-035；CI 完善（e2e/vue-tsc）待排

## 文档入口

| 文档 | 用途 |
|---|---|
| [docs/PRD.md](docs/PRD.md) | 现行需求、口径、变更状态（`CR-xxx`）——**唯一真源** |
| [TODO.md](TODO.md) | 新想法、暂缓事项、已知限制（`TODO-xxx`） |
| [AGENTS.md](AGENTS.md) | AI/协作规则：信息地图、工作流、收尾规矩 |
| [docs/](docs/) | 历史规格与验收证据（**已冻结**，仅溯源） |
| [docs/39-v2.6-deploy.md](docs/39-v2.6-deploy.md) | 部署与发布包（核心包 / 同步镜像 / 离线组装） |
