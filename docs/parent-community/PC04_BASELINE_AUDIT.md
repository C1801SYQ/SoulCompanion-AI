# PC04_BASELINE_AUDIT

日期：2026-10-11。审计依据实际代码、[PC03 契约](PC03_API_CONTRACT.md)、[PC03 架构](PC03_ARCHITECTURE.md)、[PC03 交付](PC03_DELIVERY_REPORT.md)、[PC02 交付](PC02_DELIVERY_REPORT.md)及[产品规格](01-product-spec.md)。

## Git 与复用边界

开始时 `pc-03-community-backend` 工作区干净，本地与 fetch 后远端均为 `c0098ae538128bff6d8f76a20ec8c6a2d52fcb64`。没有 PC04 分支或未提交成果；从该有效提交创建 `pc-04-community-integration`。保留 master、历史提交及全部旧功能。

复用 Taro 4.3 / React 18 / TypeScript、既有设计 tokens、AccessibleButton、Primitives、AppShell、六年龄/七话题枚举、合成 fixtures、内存草稿和页面滚动恢复。没有新建 UI 或身份体系。

## 页面、认证与隐私

`app.config.ts` 默认社区，四主入口及详情、投稿、五个家庭工具共 11 页。`navigation.ts` 区分主入口 reLaunch 和普通 navigateTo/navigateBack；H5 hash 路由与小程序页面共用业务代码。运营应为独立普通路由，不进入主导航。

CloudProvider 创建唯一官方 SDK adapter，CloudStore 公共页面 `setPageScope(false,false)`。社区不得调用 `CloudStore.refresh()` 读取昵称：该调用开启家庭 scope 时会请求 me/children/报告。只复用同一 auth 和单独 parentProfile API。私人社区请求必须同步校验 auth epoch + subject，并在退出、切换或失效时取消和清空。

Session hide/unmount 已释放设备；SessionProvider 在身份或档案变化时 stop + clearPrivate。新社区不得导入捕获授权，不读取儿童、会话、情绪或私有报告，不上传媒体。001/002/003 marker、集合、索引、网关、费用设置不改。

## API 差异与最小兼容方案

PC03 已有公开浏览、投稿、本人内容、评论、关系写入、收藏页、举报及运营队列/审核。真实分页为 items/limit/next_cursor；没有 total/offset/count。DELETE 版本在 query。审核回执必须同时检查当前 status/revision，不能只凭 action_applied 推断当前公开。

现有 family transport 仅允许旧私有路由、string/null body 和 2048 字符；不能承担匿名读取、长社区正文、数字 revision 和幂等头。新增专用社区 transport，继续使用同一 auth、安全 origin、受控 Taro wire 和取消机制，保持旧 transport 不变。

审计发现两个真实契约缺口；先提出本地增量兼容方案，再实现安全回归：

1. `GET /api/v2/me/community/posts/{post_id}/relations`：`{post_id,liked,bookmarked}`。从服务端验证身份派生关系键，公开父帖前后复核，不读取他人关系、不新增集合/索引、不写入。
2. `GET /api/v2/me/community/{posts|comments}/{id}/feedback`：`{target_type,target_id,content_revision,status,feedback}`，feedback 仅当前正文版本最近一次 approve/reject/hide 的 action/reason/at/content_revision。先所有权校验；不返回 actor、hash 或完整 audit。pending 新版本不展示旧版反馈。旧 Owned DTO 精确安全字段保持不变。

安全回归必须覆盖匿名拒绝、跨用户 404、隐藏父帖拒绝关系读取、关系字段完整性、旧版本反馈隔离、公开 DTO 不变及全部 PC03 测试。真实 sc-v2-api 更新需要 PC04 独立授权；本地实现不代表已部署。

## 数据模式

社区独立 REAL/DEMO，与旧情绪数据 source 解耦。合法真实配置采用 API，公开 GET 无 token；健康错误显示真实错误，不降级 fixtures。DEMO_ONLY 仅合成预览，不进行社区云写入。Cloudflare Pages 的 CF_PAGES 强制 DEMO_ONLY 保持。列表、草稿、本人、运营状态不混用缓存；所有相关页面可见模式。

## 测试与包体基线

既有客户端 404 单测、社区/媒体/旧 E2E、22 WXSS guards；PC03 Python 全量 1474 项通过。保留原断言，增加 REAL Fake 全链路、请求竞态与安全回归。构建不等于开发者工具或真机通过。

当前默认 weapp 产物：48 文件，主包/总包均 832,560 bytes，SDK 未启用；低频旧页面资产 62,081 bytes。正式配置构建后重新计量，评估普通分包和 requiredComponents 按需注入，保留原路径。体积优化不删除功能。

依赖复查：36 包级 finding（1 critical /29 high /6 moderate），对应 10 advisory/7 vulnerable leaf 包。critical decompress 处于 CLI 模板下载/解压链；其余受影响版本定位于构建/模板/缓存/glob。用户 H5 query-string 使用已修复 decode-uri-component 0.5.0；受影响 0.2.2 位于 normalize-url 的工具链。仍存在工具链风险，策略 PASS 不代表零漏洞。见 [decompress 公告](https://github.com/advisories/GHSA-mp2f-45pm-3cg9)。

## 云与人工门槛

PC03 的已授权真实成果可读取参考，但旧授权不覆盖 PC04 写入、函数部署或角色授予。本阶段先完成可审查的软件与 Fake 闭环，再提供有界合成验收、回滚和清理计划，等待独立授权。真实微信登录、DevTools 新页面及手机均尚未验证。
