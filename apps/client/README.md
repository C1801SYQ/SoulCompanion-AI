# 予怀 · shared client

更新：2026-10-09，范围 PC01。

Taro 4 / React 18 / TypeScript 客户端，微信小程序优先，H5 用于共享界面、开发预览和浏览器测试。PC01 默认入口为社区，主导航为社区、育儿知识、成长记录、我的。服务 0～18 岁儿童家庭，用户为成年家长/监护人。

社区帖子都是明确标注的合成示例。年龄/话题可组合筛选，详情使用页面栈并恢复筛选和滚动。投稿仅当前应用内存预览，刷新/身份变化后清空；不写云端或浏览器存储。真实发布、评论、收藏、审核、知识文章和手动成长记录存储尚未实现。

## Run and verify

使用 Node.js 24、Python 3.12，从仓库根目录运行：

```sh
npm ci --ignore-scripts
npm --prefix apps/client ci --ignore-scripts
npm run client:typecheck
npm run client:test
npm run client:audit
npm run client:build:h5
npm run client:test:e2e
npm run client:test:media
npm run client:test:community
npm run client:build:weapp
```

浏览器测试需要 Playwright Chromium。旧 E2E/media 还需要 requirements-web.txt，可通过 SOULCOMPANION_PYTHON 指定解释器；它们创建独立合成数据库和虚拟设备，不使用物理摄像头。社区测试运行独立静态服务器，阻止并检查 API、外部网络、写入、权限和存储请求。证据分别位于忽略的 .test-artifacts/v2-client-acceptance/、v2-media-acceptance/ 和 community-acceptance/。

开发执行 npm --prefix apps/client run dev:h5 并打开 loopback 根 URL。公共社区无需后端或登录；旧真实模式家庭工具需要同源 V1 后端，或明确配置既有 V2 云端。测试旧工具时使用 /#/home，默认根入口现在是社区。

## Configuration and boundaries

- PUBLIC_API_URL：Legacy V1 API origin 或 /api/v1 base；为空表示同源。
- PUBLIC_API_BASE_URL：独立 V2 HTTPS origin，不带 /api/v2；为空关闭云账户。
- PUBLIC_CLOUDBASE_ENV_ID、PUBLIC_CLOUDBASE_REGION、PUBLIC_WECHAT_APP_ID：公开环境配置，不是凭据。
- PUBLIC_DEMO_ONLY=true：禁用真实云账户与 Legacy REAL；旧情绪页显示明确合成内容。用户仍可主动开启本地设备预览。
- CF_PAGES=1：始终强制 DEMO_ONLY。CI 对此构建执行旧 E2E/media 和新社区测试。

公共路由暂停 CloudStore 私有读取，退出/账户变化清理继续有效。公开作者仅合成昵称，不使用内部 UID/OpenID 或儿童档案。不要将密钥、令牌、真实儿童信息、原始附件或媒体写入代码和产物。

Home、Session、Insights、Reports、Settings 保留原路径，在“成长记录”/“我的”中显式进入。媒体 Start 才申请 Camera/Mic；Stop、导航和后台释放设备，返回不自动重启。原始音视频不上传、不用于伪造 AI 结果。微信临时媒体由既有适配器清理。

## Navigation and platforms

共享 [navigation.ts](src/navigation.ts) 定义四主入口。主切换 reLaunch；详情/投稿 navigateTo/navigateBack；旧家庭工具之间 redirectTo，进入/退出工具使用页面栈。当前沿用 AppShell 自绘主导航，不叠加原生 TabBar，也不将普通详情配置为 Tab 页。

Cloudflare Preview 保留根目录 apps/client、命令 npm ci --ignore-scripts && npm run build:h5、输出 dist、Node.js 24 与 DEMO_ONLY，不调整 Production 设置。微信产物 dist-weapp 可供有权限的用户导入 DevTools；DevTools、微信登录及真机设备仍 NOT TESTED。Android APK 和实体机器人不属于 PC01。

参见 [PC01 产品规格](../../docs/parent-community/01-product-spec.md)、[交付报告](../../docs/parent-community/PC01_DELIVERY_REPORT.md)、[Phase 04](../../docs/v2/PHASE04_DELIVERY_REPORT.md)、[微信人工步骤](../../docs/v2/MANUAL_ACTIONS.md) 和 [媒体隐私](../../docs/v2/MEDIA_PRIVACY.md)。依赖保持锁定，不添加新框架或远端安装脚本。
