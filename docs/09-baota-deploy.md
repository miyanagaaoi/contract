# 09. 宝塔面板（BT Panel）部署步骤 —— CTMS 合同管理与跟踪系统

> 目标：把 CTMS 以"正式版候选（1.0.0-rc1）"部署到**安装了宝塔面板的 Linux 服务器**。
> 架构：`Nginx(托管前端 + 反代 /api) ← uvicorn(FastAPI :8000) + SQLite(默认) / 可选 MySQL/PostgreSQL`
> 数据量（3~4 人、数百~千级合同）下 **SQLite 即可**，无需装数据库；下文同时给出可选的数据库方案。

---

## 0. 前置约定与检查

| 项 | 要求 |
|---|---|
| 系统 | Ubuntu 20.04+/Debian 11+ 或 CentOS 7+（已装宝塔 7.x+） |
| Python | **≥ 3.10**（建议 3.11/3.12）；可用宝塔软件商店的 Python 或 `apt/python3.11` |
| Node | ≥ 18（仅构建前端时用，可在装完后删除） |
| 代码目录 | 示例用 `/www/wwwroot/contract`（下文全部按此目录写，可换） |
| 端口 | 后端内网 `127.0.0.1:8000`（不对外开放）；前端对外 `80/8080`（按站点配置） |

远程仓库：`https://github.com/miyanagaaoi/contract.git`（若为私有仓库需在服务器配置凭据/令牌，见 3.2）。

---

## 1. 安装运行环境（宝塔软件商店）

1. 登录宝塔面板 → **软件商店** 安装：
   - **Nginx**（已有则跳过）
   - **Python 项目管理器**（若商店仅有"Python项目"也适用）—— 或直接用系统 Python：`apt install -y python3.11 python3.11-venv`（Ubuntu）；确认版本 `python3.11 --version`
   - **Node.js 版本管理器**（用于前端构建，构建完可不管）
2. 安装 **进程守护管理器（Supervisor）**——用于把后端做成常驻服务（也支持开机自启/崩溃重启）。

> 命令行入口：宝塔面板有"终端"功能；下文 shell 命令可在面板终端或 SSH 中执行。

---

## 2. 放行端口与安全组（先做，避免后面访问不通）

- 宝塔面板 → **安全** → 放行你将使用的站点端口（如 `8080`）；后端 `8000` 仅本机调用，**不要对外放行**。
- 云服务器（阿里云/腾讯云等）→ 控制台 **安全组** 同步放行该端口。

---

## 3. 上传/获取代码到服务器

### 3.1 方式 A：git clone（推荐，方便升级）

在服务器终端：

```bash
cd /www/wwwroot
git clone https://github.com/miyanagaaoi/contract.git contract
```

- 私有仓库请先配置凭据（二选一）：
  - SSH：把服务器公钥加入 GitHub → 改用 `git clone git@github.com:miyanagaaoi/contract.git`；
  - Token：`git clone https://<用户名>:<PAT>@github.com/miyanagaaoi/contract.git`（PAT 需 `repo` 权限，之后建议把凭据写入 `~/.git-credentials` 并 `git config --global credential.helper store`）。
- 若本机已配代理且服务器网络受限，可在服务器上 `git config --global http.proxy http://127.0.0.1:7897`（仅当服务器有类似代理时）。

### 3.2 方式 B：本机打包上传（无 git 也可）

1. 本机执行：`git archive --format=zip HEAD -o ctms.zip`（只含纳入版本库的文件，干净）；
2. 宝塔 **文件** → 上传到 `/www/wwwroot/` 并解压，得到 `/www/wwwroot/contract`；
3. 升级时重复本步骤即可。

### 3.3 目录归属与权限

```bash
chown -R www:www /www/wwwroot/contract
```

> 后端运行用户统一用 `www`（与 Nginx/进程守护默认一致），可避免写权限问题。

---

## 4. 前端：安装依赖并构建静态文件

```bash
cd /www/wwwroot/contract/web
npm config set registry https://registry.npmmirror.com   # 国内源，可选
npm install
npm run build        # 生成 dist/ 静态产物，作为 Nginx 站点根目录
chown -R www:www /www/wwwroot/contract/web/dist
```

> 生产环境不需要 `npm run dev`。构建产物目录：`/www/wwwroot/contract/web/dist`。

---

## 5. 后端：Python 虚拟环境、依赖、数据库

```bash
cd /www/wwwroot/contract
# 1) 创建虚拟环境（用 python3.11；若只有 python3 且 >=3.10 可替换）
python3.11 -m venv app/.venv

# 2) 安装依赖（国内加速源，可选）
app/.venv/bin/pip install -r app/requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 3) 初始化数据库（生产环境建议【不要】加 --demo；首次部署或想先看演示再加）
app/.venv/bin/python -m app.init_db          # 仅建表+字典种子（幂等）
# app/.venv/bin/python -m app.init_db --demo # 需要演示数据时用

# 4) 目录与权限
chown -R www:www app/data app/uploads app/logs   # 启动时也会自动创建，先授权更稳
```

**可选：改用 MySQL/PostgreSQL（默认 SQLite 无需任何安装）**

- 本项目数据模型用 SQLAlchemy 编写；默认 SQLite。3~4 人规模**建议直接用 SQLite**（零运维、单文件，每日备份即可）。
- 如公司要求走数据库：
  - PostgreSQL：宝塔软件商店装 PostgreSQL，建库建用户后设置环境变量
    `CTMS_DB_URL=postgresql+psycopg2://ctms:密码@127.0.0.1:5432/ctms`，并
    `app/.venv/bin/pip install -r app/requirements-pg.txt`；
  - MySQL：本项目未内置 MySQL 依赖，如需请说明（可加 `pymysql` 后 SQLAlchemy 直连）。

---

## 6. 后端常驻：Supervisor（进程守护管理器）

1. 宝塔软件商店 → **进程守护管理器** → **添加守护进程**，填：
   - 名称：`ctms`
   - 运行目录：`/www/wwwroot/contract`
   - 启动命令：
     ```
     /www/wwwroot/contract/app/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
     ```
   - 运行用户：`www`
   - 开机启动：✔ ；进程数量：1
2. 也可用等价的配置文件 `/www/server/panel/plugin/supervisor/config/ctms.conf`（如以命令行 Supervisor 安装，则放 `/etc/supervisor/conf.d/ctms.conf`）：

```ini
[program:ctms]
directory=/www/wwwroot/contract
command=/www/wwwroot/contract/app/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
user=www
autostart=true
autorestart=true
stopasgroup=true
killasgroup=true
stdout_logfile=/www/wwwroot/contract/app/logs/uvicorn.out.log
stderr_logfile=/www/wwwroot/contract/app/logs/uvicorn.err.log
```

3. 保存后点"启动"，并到 **后端进程 → 日志** 确认无报错；
4. 自检后端（本机）：`curl http://127.0.0.1:8000/api/health` 应返回
   `{"status":"ok","app":"CTMS","version":"1.0.0-rc1","db":true}`。

> 注意：`8000` 只绑 `127.0.0.1`，**不允许**被外网直连（一切访问走 Nginx 反代）。

---

## 7. 建站：Nginx 站点 + 反向代理

### 7.1 添加站点

宝塔 → **网站** → 添加站点：

- 域名：填你的域名（如 `ctms.example.com`）或服务器 IP
- **不需要**创建数据库 / PHP 版本选"纯静态"
- 根目录：留空即可，稍后手动指向 `web/dist`

### 7.2 修改站点配置文件（覆盖如下 server 段）

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name _;                      # 或用你的域名/IP

    root /www/wwwroot/contract/web/dist;
    index index.html;

    client_max_body_size 20m;           # 附件上限，与后端一致

    # API 反向代理到后端
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 120s;
    }

    # 附件/导出文件由后端接口返回，不直接暴露目录

    # SPA 前端路由（历史模式必须）
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

- 若 80 端口已被占用或按端口访问，改用 `listen 8080;` 并在宝塔安全/云安全组放行；
- 保存并 **重载 Nginx**（网站 → 设置 → 重启/重载）。

### 7.3 验证全链路

浏览器访问 `http://<服务器IP或域名>[:端口]`：
1. 应看到登录即用的"首页看板"；
2. 打开浏览器 F12 → Network，请求 `/api/dashboard` 返回 200；
3. 试新增一条合同（自动编号）、上传一个附件。

---

## 8. 安全与 HTTPS（强烈建议）

- 本系统**无登录/无角色**（内网信任模型）。若服务器暴露公网：
  - ① 优先只放内网 IP/专线访问（安全组白名单）；
  - ② 或对站点做 **IP 白名单**（Nginx allow/deny 或云防火墙）；
  - ③ 宝塔 → 站点 → **SSL** → Let's Encrypt 一键证书（需域名并解析到本机），并将 80 跳转 443。
- 数据库/附件的备份文件不要放网站根目录下可被直接下载的位置。

---

## 9. 每日自动备份（宝塔计划任务）

宝塔 → **计划任务** → 添加 Shell 脚本，周期"每天 02:00"，内容：

```bash
#!/bin/bash
# CTMS 备份：数据库 + 附件，保留 30 天
SRC=/www/wwwroot/contract
DST=/www/backup/ctms
mkdir -p $DST
STAMP=$(date +%Y%m%d_%H%M%S)

# 1) 停写备份更稳：直接复制 SQLite（量小可接受；要更稳先 supervisorctl stop ctms 再 start）
cp $SRC/app/data/ctms.db $DST/ctms_$STAMP.db 2>/dev/null

# 2) 附件
tar czf $DST/uploads_$STAMP.tar.gz -C $SRC/app/uploads . 2>/dev/null

# 3) 清理 30 天前
find $DST -name "*.db" -o -name "*.tar.gz" | while read f; do
  [ "$(stat -c %Y "$f")" -lt "$(date -d '30 days ago' +%s)" ] && rm -f "$f"
done
echo "backup ok: $STAMP"
```

> 更稳妥的在线备份可参考仓库 `scripts/backup.ps1` 的思路（Windows 版）；Linux 版如需 SQLite 的 `backup API` 备份，可让运维加一段 python 在线备份脚本（需要我另出一份也可以）。

**恢复演练（每季度一次）**：
1. `supervisorctl stop ctms`
2. 用备份的 `ctms_日期.db` 覆盖 `app/data/ctms.db`；解压 `uploads_*.tar.gz` 到 `app/uploads`
3. `chown -R www:www app/data app/uploads`；`supervisorctl start ctms`
4. 访问站点确认数据/附件恢复 → 记录演练结果。

---

## 10. 升级发布（以后每次）

```bash
cd /www/wwwroot/contract
git pull                        # 或重新上传替换代码
chown -R www:www .

# 后端重启（自动执行建表/增量迁移）
supervisorctl restart ctms
tail -50 app/logs/uvicorn.err.log   # 观察有无报错

# 前端重新构建
cd web && npm install && npm run build && chown -R www:www dist

# 回归
app/.venv/bin/python -m pytest app/tests -q          # BR 单测
# 接口冒烟（需站点可访问 127.0.0.1:8000）
curl http://127.0.0.1:8000/api/health
```

> 后端每次启动会自动 `create_all` + 轻量增量迁移（`app/db_migrate.py`），无需手工改表。

---

## 11. 常见问题排查

| 现象 | 排查 |
|---|---|
| 打开站点 502 | 后端没起：`supervisorctl status ctms`；看 `app/logs/uvicorn.err.log`；`curl 127.0.0.1:8000/api/health` |
| 静态页 404/刷新白屏 | 确认站点根目录= `web/dist`、且含 `location / { try_files $uri $uri/ /index.html; }` |
| 上传失败/超 20M | nginx `client_max_body_size 20m`；附件接口 413 → 确认代理段也生效 |
| 数据/目录没权限 | `chown -R www:www /www/wwwroot/contract`（含 data/uploads/logs） |
| 前端能开但接口 500/无法保存 | 看后端 err 日志；多为 Python 版本 <3.10 或依赖缺失 → `python3 --version` 确认并重装依赖 |
| 中文文件名乱码 | 确认系统 UTF-8（`locale`），文件名本身按 UTF-8 存储 |

---

## 12. 部署核对清单

- [ ] Python ≥3.10、Nginx、Supervisor 已装
- [ ] 代码在 `/www/wwwroot/contract` 且 `chown www:www`
- [ ] 前端 `npm run build` 成功
- [ ] 后端 `app/init_db` 成功、`/api/health` 返回 ok
- [ ] Supervisor 守护 `ctms` 常驻并开机自启
- [ ] Nginx 站点根目录=dist、`/api/` 反代到 `127.0.0.1:8000`、20m 上传
- [ ] 站点端口在宝塔安全/云安全组放行
- [ ] 计划任务每日备份已建
- [ ] 公网暴露场景已加白名单/HTTPS
- [ ] 跑一次 9 节的恢复演练
