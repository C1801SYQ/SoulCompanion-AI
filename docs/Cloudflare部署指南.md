# SoulCompanion 看板 · Cloudflare Pages 部署指南

本指南教你把这套「小予情绪智能仪表板」部署成一个**可独立访问的静态网站**。

> ⚠️ **重要说明（部署前必读）**
> 静态站点**没有后端**，看板会自动切换到 **演示模式**，展示的是**程序合成的演示数据**，
> 页头会显示醒目的 **`⚠️ 演示数据（后端未连接）`** 徽章。
> 请勿把它当作真实儿童数据来源；对外分享时请保留该徽章。

---

## 0. 前置准备

| 需要什么 | 说明 |
| --- | --- |
| Python 3.10+ | 用于本地构建（脚本只用标准库，无需额外安装） |
| Node.js（可选） | 用于 `wrangler` API Token 部署方式 |
| Cloudflare 账号 | 免费注册：https://dash.cloudflare.com/sign-up |

所有命令均在**项目根目录**执行（`D:\SoulCompanion_AI`）。

先构建一次静态产物：

```bash
python scripts/build_site.py
```

成功后会生成 `dist-site/` 目录：

```
dist-site/
├── index.html        # 看板入口（由 web/templates/dashboard.html 转换而来）
├── static/
│   ├── style.css
│   ├── app.js        # 双模式前端逻辑
│   └── demo-data.js  # 纯前端演示数据引擎
├── _headers          # 安全响应头 + 缓存策略
├── robots.txt        # 合成数据站，建议禁止抓取
└── 404.html          # 中文 404 页面
```

---

## 方式 A：手动上传（最简单，适合首次体验）

1. 本地执行构建：
   ```bash
   python scripts/build_site.py
   ```
2. 登录 **Cloudflare Dashboard** → 左侧 **Workers & Pages**。
3. 点击 **Create** → 选择 **Pages** 标签 → **Upload assets**（Direct Upload）。
4. 项目名填 `soulcompanion-dashboard`（可自定义）。
5. 把本地 `dist-site/` 目录**整个拖拽**到上传区（或点选文件夹）。
6. 点击 **Deploy site**，等待几十秒即可拿到形如
   `https://soulcompanion-dashboard.pages.dev` 的访问地址。
7. 打开地址，确认页头出现 **`⚠️ 演示数据（后端未连接）`** 徽章即表示部署成功。

> 手动上传的缺点：每次更新都要重新拖拽。频繁更新请用方式 B。

---

## 方式 B：用 API Token + wrangler（推荐，可重复部署）

### B1. 申请 API Token

1. 打开 Cloudflare → 右上角头像 → **My Profile**。
2. 左侧 **API Tokens** → **Create Token**。
3. 选择 **Custom token**（自定义令牌），权限按如下配置：
   - **Permissions**：`Account` → `Cloudflare Pages` → **Edit**
     （即 "Cloudflare Pages:Edit" 权限）
   - **Account Resources**：选择你的账号
4. 创建后**复制 token**（只显示一次，请妥善保存）。

### B2. 拿到 Account ID

Cloudflare Dashboard → **Workers & Pages** 右侧栏，或任意域名概览页右下角，
可看到 **Account ID**（一串 32 位十六进制字符）。

### B3. 部署

在项目根目录执行：

```bash
export CLOUDFLARE_API_TOKEN=<你的 token>
export CLOUDFLARE_ACCOUNT_ID=<你的 account id>

# 确保已构建
python scripts/build_site.py

npx wrangler pages deploy dist-site --project-name=soulcompanion-dashboard
```

说明：
- **首次部署**：`wrangler` 会提示项目不存在，**自动创建**项目 `soulcompanion-dashboard`，
  然后完成上传，无需先去 Dashboard 手动建项目。
- 之后每次更新，重复执行 `build` + `deploy` 两条命令即可。
- 输出末尾会给出本次部署的预览地址与生产地址。

> Windows 用户若使用 PowerShell，把 `export X=Y` 换成 `$env:X="Y"`。

---

## 方式 C：本地预览（部署前自检）

无需联网，用 Python 自带服务器预览：

```bash
python scripts/build_site.py && python -m http.server 8080 --directory dist-site
```

然后浏览器打开 **http://localhost:8080/** 。
此时因为连不上 `/api/*`，看板会自动进入演示模式并显示徽章——
这正是静态托管上的真实表现。

> 验证完成后记得按 `Ctrl+C` 关闭服务器。
> 想临时关闭回退（看到空白即为"没有后端"）：访问 `http://localhost:8080/?nodemo=1`；
> 想强制演示：`http://localhost:8080/?demo=1`。

---

## URL 参数速查

| 参数 | 作用 |
| --- | --- |
| `?demo=1` | 强制演示模式（无视后端） |
| `?nodemo=1` | 关闭演示回退（后端不可用则留空） |
| 无参数 | 优先连后端，失败则**自动**回退到演示模式并显示徽章 |

---

## 附加操作

### 绑定自定义域名

1. Cloudflare Dashboard → **Workers & Pages** → 选中 `soulcompanion-dashboard`。
2. **Custom domains** → **Set up a custom domain**。
3. 输入你的域名（如 `dashboard.example.com`），按提示完成 DNS 解析
   （域名需托管在 Cloudflare，或按提示添加 CNAME）。
4. 生效后即可用自定义域名访问。

### 回滚到历史版本

1. 进入项目 → **Deployments** 标签页。
2. 找到想要恢复的历史部署，点击其右侧 **⋯** → **Rollback to this deployment**。
3. 生产地址会立即切回该版本（无需重新构建）。

### 更新流程（日常）

```bash
# 1. 修改前端（web/templates、web/static）
# 2. 重新构建
python scripts/build_site.py
# 3. 部署
npx wrangler pages deploy dist-site --project-name=soulcompanion-dashboard
```

若采用"方式 A 手动上传"，则第 3 步改为在 Dashboard 里重新拖拽 `dist-site/`。

---

## 常见问题

| 现象 | 原因 / 处理 |
| --- | --- |
| 页面空白，无徽章 | 未加载 `demo-data.js`。确认 `dist-site/static/demo-data.js` 存在且 `index.html` 中它在 `app.js` **之前**。 |
| 显示徽章但图表空 | 属正常首帧；约 1 秒后趋势图/分布会渲染出 30 天合成数据。 |
| 想改端口 | 换掉 `--directory` 前的 `8080` 即可。 |
| `wrangler` 报鉴权失败 | 检查 `CLOUDFLARE_API_TOKEN` 是否含 **Cloudflare Pages:Edit** 权限、`CLOUDFLARE_ACCOUNT_ID` 是否正确。 |
| 更新后页面没变 | 入口 `index.html` 已设 `no-cache`；若仍看到旧版，强制刷新（Ctrl+F5）。 |

---

## 安全与隐私备注

- `_headers` 已设置 `X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、
  `Referrer-Policy: no-referrer`，并对 `/static/*` 设 7 天长缓存、对 `/` 设 `no-cache`。
- `robots.txt` 设为 `Disallow: /`，因本站为**合成数据演示站**，不建议被搜索引擎收录。
- 静态站**不包含任何真实儿童数据**，也不与后端通信；所有数据在浏览器内即时合成。
