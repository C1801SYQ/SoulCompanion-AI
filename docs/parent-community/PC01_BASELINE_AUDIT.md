# PC01_BASELINE_AUDIT

日期：2026-10-09（Asia/Shanghai）。本审计在业务代码变更之前完成。

## Git 与来源

- 当前父分支 `04-cloud-backend`，本地 HEAD 与 fetch 后的 `origin/04-cloud-backend` 都是 `ce95b555bb1667ec653d05960ba2e47210b8b75d`；没有更新提交需要另行继承。
- 唯一未提交文件 `docs/v2/PARENT_COMMUNITY_REPLAN.md` 来自上一轮用户要求的路线计划，属于本阶段参考资料，保留并纳入此次文档交付；不存在其他未提交业务改动。
- 本地及远端此前没有 `pc-01-community-prototype`。从上述基线创建指定分支，不回退、覆盖历史或修改 master。
- 已读取原路线计划；商业策划书和十页 PPT 在上一轮提取及阅读，本轮再次核对文件存在、相关原文与幻灯片内容。它们位于用户提供的仓库外位置，原始附件不加入 Git。
- 未发现适用的 AGENTS.md。没有安装新的框架或执行技能安装脚本。

## 前端入口、路由与导航

`apps/client/src/app.tsx` 是共享入口，Provider 为 AppProvider → ErrorBoundary → CloudProvider → SessionProvider。现有 app.config 注册 home/session/insights/reports/settings 五页，home 是旧默认页面。H5 hash 自定义路由保留 `/home`、`/session`、`/insights`、`/reports`、`/settings`。

AppShell 自绘桌面侧栏和移动底栏，旧导航使用 Taro.reLaunch，移动 CSS 为五列。PC01 新增四个公共入口并将社区注册为默认首项；保留旧五页路径和作为家庭工具的可见入口。详情、投稿和工具进入必须采用页面栈，不能所有跳转使用 reLaunch。

原生 TabBar 可提供平台管理的主入口，但当前 H5 自绘导航与旧页面测试依赖同一 AppShell。PC01 选择共享自绘四入口，不引入第二套 native TabBar；通过统一导航模型区分主切换、详情/投稿压栈、家庭工具压栈/返回。后续真实微信体验可再评估原生 TabBar，不将构建成功当作真机体验通过。

## 设计与能力复用

复用 design/tokens.scss、styles.scss、AccessibleButton、Primitives 的 SectionCard/EmptyState/StatusPill/PrimaryAction、PageHeader 和 AppShell，以及已安装 Taroify 1.0.6。技术栈为 Taro 4.3.0、React 18.3.1、TypeScript 5.9.3。新品牌视觉在既有 token 与独立社区样式上扩展。

AppProvider 构造 V1 API 是惰性的，初始化不请求网络。实际旧轮询由各页 useResource 发起，hide/unmount 会取消。社区不挂载旧 HomePage、useResource、CloudRecords 或 CloudAccount。

CloudBase 使用官方 SDK 3.10.1，SDK 初始化延迟至显式登录；令牌在内存，私有请求在线校验。CloudStore 登录事件会刷新 me/children，已选档案会刷新私有记录。公共路由需要必要的读取暂停边界，取消离开私有页面后的 pending read，同时保留认证对象和退出清理；默认 Store 行为保持已有测试兼容，不重写认证。

SessionProvider 初始化媒体 adapter/controller/bridge 不申请设备权限。Session 页主动 Start，hide/unmount、账户/档案变化和 Provider dispose 会停止采集；本地停止不等待云会话结束。此生命周期、原媒体适配器、终止重试和零上传边界保持。

## 测试、构建与依赖

- Node v24.15.0。本阶段优先使用已验证的 `.test-artifacts/native-env/Scripts/python.exe`（Python 3.12.4）；另有 Python 3.13 测试环境，不混淆版本。
- 已装根 Playwright 1.63.0；本机 Chromium 位于忽略的 `.test-artifacts/playwright-browsers`，测试显式设置 PLAYWRIGHT_BROWSERS_PATH，无须下载。
- 客户端 Vitest 覆盖数据契约、资源循环、键盘、媒体、云认证、状态和 transport；Phase 04 历史记录为客户端 241 个测试，本阶段结果另行记录。
- client_smoke 保留真实隔离的 65 条 SQLite 历史、分页/导出、错误、离线恢复 AUTO_RETRY/MANUAL_RETRY、键盘、触控与响应式断言。
- media_smoke 使用 Chromium 虚拟设备，保留权限拒绝、晚到授权、导航/后台停止、零媒体上传/持久化、合成测试 fixture 清理。它不代表微信或物理设备验收。
- `client:build:h5` → Taro H5，输出 apps/client/dist；`client:build:weapp` → 微信构建，输出 dist-weapp；typecheck、client:test、client:test:e2e、client:test:media 脚本均已存在。
- GitHub Actions 已有普通 H5、CF_PAGES 强制 DEMO H5、weapp 构建及云回归等九个作业。本阶段添加独立社区浏览器测试到两个 H5 作业，不删除旧回归、不部署 CloudBase、不修改 Cloudflare Production。

## 必须保留的边界

保持所有旧路径、真实/DEMO 标签、失败不伪装 DEMO、65 条历史持久化断言、原始媒体不上传、离开媒体页释放设备、官方认证和跨账号清理。不改 cloud/schema/001_metadata.json、云 API、线上权限/集合/函数/网关或 SQLite 数据。

社区示例与家庭数据分开：公共页面不读私有档案/报告，不需要登录、诊断标签、硬件或订阅，不把 UID/OpenID 当公开作者。不把原报告改名为手动观察记录。真实社区发布/审核未实现，微信实际登录/真机仍未验证。
