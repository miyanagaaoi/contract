# 05. 原型验收报告（P1 · AC-01~AC-11）

> 依据 `01-requirements.md` 第 7 节验收场景与 `00-sdd-process.md` DoD（场景全绿 + Git 提交）。
> 方法：后端真实 HTTP 接口冒烟（`app/tests/smoke_p0.py`，可重复执行）+ 前端生产构建。

## 1. 结果总览

| 验收场景 | 内容 | 结果 | 对应功能(提交) |
|---|---|---|---|
| AC-01 | 新增合同（默认状态/比例 0%/详情可开） | ✅ | T3 `f182f7a` |
| AC-02 | 合同编号重复 → 409 提示 | ✅ | T3 `f182f7a` |
| AC-03 | 已付联动付款比例（50%） | ✅ | T3 `f182f7a` |
| AC-04 | 状态流转 + 备注历史 | ✅ | T6 `14e6a01` |
| AC-05 | 多标签挂载/替换（同合同多标签） | ✅ | T4 `8bd53f3` |
| AC-06 | 组合搜索（关键词+签订区间+标签交集） | ✅ | T5 `974bd3d` |
| AC-07 | 框架合同一对多绑定与金额汇总 | ✅ | T8 `0d941c4` |
| AC-08 | 质保到期看板提醒（即将/已到期）与释放 | ✅ | T9 `ab7ca82` |
| AC-09 | 附件上传/下载/删除留痕 | ✅ | T7 `069901f` |
| AC-10 | 免登录直开 + 停用(必填原因)/30 天内恢复 | ✅ | T3 `f182f7a` |
| AC-11 | 导出 Excel = 当前筛选（行列一致） | ✅ | T10 `d1bbce8` |
| （基础） | 前端 `npm run build` 编译通过 | ✅ | T1~T11 各提交 |

冒烟输出：`ALL P0 ACCEPTANCE PASSED (12 checks)`（见 `app/tests/smoke_p0.py`）。

## 2. 运行环境与复现

- 后端：Python 3.13 + FastAPI + SQLAlchemy + SQLite（`app/data/ctms.db` 已重置为演示数据：4 合同 / 4 预置标签）
- 前端：Vue3 + Vite + Element Plus（`web/dist` 可构建产物）

```bash
# 后端（D:\dsh\hetong 下）
app\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
# 前端
cd web && npm run dev          # http://127.0.0.1:5173（/api 代理到 8000）
# 验收冒烟（另开终端，服务在跑）
app\.venv\Scripts\python app\tests\smoke_p0.py
```

## 3. Git 版本纪律达成情况（每功能一次提交）

```
68868db docs: 需求规格 V1.0（文档体系基线）
18029d7 feat: [T1][T2] 脚手架 + 数据模型与种子
f182f7a feat: [AC-01][AC-02][AC-10][AC-15] T3 合同 CRUD
8bd53f3 feat: [AC-05][AC-13] T4 标签体系
974bd3d feat: [AC-06] T5 组合搜索筛选
14e6a01 feat: [AC-04][AC-12] T6 状态流转与变更历史
069901f feat: [AC-09] T7 附件上传/下载/预览
0d941c4 feat: [AC-07] T8 框架合同绑定与汇总
ab7ca82 feat: [AC-08][AC-14] T9 质保到期与首页看板
d1bbce8 feat: [AC-11] T10 Excel 导出（当前筛选）
<本次>     feat: [P0] T11 打磨与总冒烟（验收脚本/报告）
```

## 4. 已知事项（非阻断）

- Vite 产物单 chunk 略大（Element Plus 全量引入），内网使用无影响；如需可后续做按需引入；
- 本机 node v21.5.0 与 vite@6 存在 EBADENGINE 提示，构建实测通过（vite 需 ≥20/22，建议后续升级 node 或降 vite ^5）；
- 无登录/无角色按规格实现，操作追溯依赖"经办人"字段 + 变更历史（时间/前后值）。

## 5. 演示建议（P2 决策会）

1. 打开首页看板：演示质保提醒（演示数据含：到期于 2026-05-31 的已到期单、20 天后到期的即将到期单）；
2. 合同台账：用真实合同现场新增 1 单（标签、金额、已付→看比例）、组合搜索、导出 Excel；
3. 打开框架合同 F-2025-001：看 2 份子合同与金额汇总；
4. 变更历史时间线、附件上传预览、停用/恢复各演示一次。

## 6. 结论与下一步

P0 验收场景 **11/11 全绿**（12 项检查），原型可演示。进入 P2：三类用户（采购/财务/项目管理）演示 → Go/No-Go 决策；
若 Go，按 `03-development-plan.md` P3 推进正式版 M0（PostgreSQL、备份、部署手册、自动化测试）。
