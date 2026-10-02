# Cloudflare 静态合成演示

更新：2026-10-02。

静态产物由构建时明确设置为 **DEMO-only**：所有数据在浏览器内合成，无 Python 后端、无真实儿童数据库、零 API 请求。不是网络故障后的自动回退。

## 构建与本机预览

在仓库根目录运行（Python 3.12，脚本只用标准库）：

```powershell
python scripts/build_site.py --out .test-artifacts/site
python -m http.server 8080 --bind 127.0.0.1 --directory .test-artifacts/site
```

打开 http://127.0.0.1:8080 。页头必须显示 `DEMO DATA · 合成演示数据`，真实模式按钮禁用；即使 `?nodemo=1` 也不会访问后端。历史、趋势、分页和报告导出都是合成内容，Markdown 同样标注 DEMO DATA。

输出包含 index.html、static/app.js、static/demo-data.js、static/style.css、安全头、robots.txt、404.html 和构建标记。构建会拒绝非空未标记目录或源码/链接路径；旧 dist-site 若无标记请选择新的空目录，不要删除已有用户文件。

## 发布范围

将 `.test-artifacts/site` 的静态文件通过 Cloudflare Pages 的静态上传流程发布，保留 DEMO 徽章与安全头。不要上传仓库根目录、data、数据库、备份、导出、模型、.env、测试截图或日志。此文档不执行上传，也未在本轮创建或更新外部网站。

公开静态站不要接入真实 `/api` 代理，不提供远程家长数据访问。真实看板仅在本机运行；未来远程产品须先实现身份认证、授权与 HTTPS。

## URL 行为

| 入口 | 行为 |
| --- | --- |
| 静态产物，无参数 | 固定合成 DEMO |
| 静态产物，?demo=1 | 固定合成 DEMO |
| 静态产物，?nodemo=1 | 仍固定 DEMO，真实模式禁用 |
| 本机 FastAPI，?demo=1 | 用户明确选择浏览器合成展示；不会停止后台真实采集 |
| 本机 FastAPI，无参数 | 按启动配置；真实后端失败显示 OFFLINE/ERROR，不自动演示 |

## 验证

`node scripts/verify_demo.js` 保留旧合成引擎自测；`npm test` 覆盖新 v1 合成契约与模式；`npm run test:e2e` 实际打开构建产物并检查零 API 请求、明确 DEMO 和禁止切换真实模式。

若出现空白或 ERROR，检查静态资源是否齐全及 demo-data.js 是否在 app.js 前加载，不用隐藏错误或移除徽章。更新后重新构建并上传静态产物，必要时强制刷新浏览器。
