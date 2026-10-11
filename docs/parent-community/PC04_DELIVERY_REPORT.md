# PC04_DELIVERY_REPORT

更新：2026-10-12。**可执行软件验收通过，真实云实施等待独立授权，尚未最终交付。** 本报告区分已经取得的证据和待执行项，不将本地 Fake、构建或截图计为完整真实云/微信验收。

## 基线与 Git

开始时工作区干净；核对后的 PC03 本地/远端 SHA 均为 `c0098ae538128bff6d8f76a20ec8c6a2d52fcb64`。当前分支 `pc-04-community-integration`，从该基线创建。已提交软件 `833767272abf4046067f5c6e3473d12e6d64a8df` 与测试工具 `b59a70ad4dfd4f6e86aa189599e20ec6341550da`；本报告随独立文档提交保存。本轮远端推送及 GitHub Actions 正在收尾，尚不计通过。master、历史分支、schema 001/002/003 与原成果保留。

## 已实现的软件

- 专用社区 DTO、严格请求/响应验证、受控 transport、API 和有界内存 store；共用现有官方 CloudBase auth，不重复认证。公共 GET 无 token，私有请求受 subject/auth epoch 保护，旧 401 或迟到响应不影响新账户。
- REAL/DEMO 显式分离；REAL 空库/错误不切示例。Cloudflare Pages 保持 DEMO_ONLY，未改生产配置。
- 真实列表、六年龄/七话题 AND 筛选、倒序、cursor、加载更多、刷新和竞态隔离。REAL 返回列表保留筛选并明确重新验证、回到顶部；DEMO 保留旧滚动恢复。
- 真实详情、待审投稿/一级评论、本人投稿/评论/收藏、当前版本反馈、版本化编辑与撤回、点赞收藏确认和举报。纯文本展示，无假计数；503 保留原输入和动作键，不显示假成功。
- 独立 `pages/ops/index` / H5 `#/ops`，普通主导航不显示管理入口。服务端核验角色；全文、当前 revision、理由、人审提醒、通过/拒绝/隐藏、举报独立处理与回执。403 清空受保护界面，旧详情在切 Tab、筛选、刷新和身份变化后失效。
- 公开昵称 Hook 独立实例请求槽，避免缓存页面互相取消；返回重新读取，账号作用域操作锁。社区不读取儿童档案/报告，不自动采集或上传媒体。
- 普通微信分包：Home/Session/Insights/Reports/Settings/ops；主包保留四入口、详情、投稿和本人页面。原路径不变，共享认证，`lazyCodeLoading:requiredComponents`。

主要文件位于 `apps/client/src/community/`、`state/CommunityProvider.tsx`、社区/我的/运营页面、AppShell、navigation 和 app 配置。新增 API 仅两个认证只读 GET，见 [最小契约扩展](PC04_API_EXTENSION.md)；未更新真实云函数。

## 已取得自动证据

| 项目 | 实际结果 |
| --- | --- |
| TypeScript | PASS；最终普通 UI 及 ops 修复后独立复核通过 |
| 前端单测 | PASS，25 suites / 512 tests；保留旧私有 getter 陷阱及导航断言 |
| 完整 Python | PASS，最新全量 1545 tests / 0 fail / 0 error / 0 skip / 269.810s；包含当时 19 项验收工具测试，后续追加令牌/迟到写入用专门回归另行记录 |
| 只读 API 新增回归 | PASS，47 项；原社区 domain/API/transport 408 项保留通过 |
| 部署工具新旧回归 | PASS，82 项（旧 77 + 新 5） |
| 默认 H5 build | PASS，1791 modules，20 files / 1,201,704 bytes；此快照云 SDK 未启用 |
| 默认及真实 SDK weapp build | PASS；均 22 WXSS guards / 3 generated styles 官方编译器语法 PASS |
| 包体回归 | PASS，8 项；最终真实 SDK main 1,751,999 / total 1,831,370 bytes |
| PC01 DEMO community 浏览器 | PASS，11 行为组、42 AND 组合、响应式、键盘/存储/设备边界 |
| 媒体浏览器 | PASS，15 行为组；离开媒体页释放设备，回到社区不重启 |
| PC04 本地 Fake 集成 | PASS，最终连续 3 次，每次 23 行为组、42 筛选组合、7 viewport、分页及完整人审闭环；随后按最终 npm 脚本再次通过 |
| 旧家庭 E2E | 初轮焦点断言失败；定位器限制当前站定页面后完整回归 PASS，14 行为组/30 响应式检查，焦点 solid 3px、78×44px；保留离线恢复、65 历史和无 DEMO 断言，无新增固定 sleep |
| client:audit | 策略 PASS，11 守卫；仍有 36 finding（1 critical/29 high/6 moderate），不是零漏洞 |
| 真实 UI 验收工具离线回归 | PASS，28 Python Fake 测试及 12 Node 边界检查；官方 SDK 独立 H5 构建与源码快照核验通过，没有真实云调用 |
| Ruff / 新 CJS syntax | 最终工具和浏览器夹具检查 PASS |
| git diff --check | 当前检查 PASS；提交前还须核对全部最终文件 |
| GitHub Actions | NOT TESTED，待本轮软件/文档推送后核验 |

视口：375×812、390×844、430×932、600×900、767×1024、768×1024、1440×900。Fake 集成中家庭私有接口、媒体权限、外网、角色授予 HTTP 与未捕获异常均为 0。实际 FastAPI 路由配 InMemory 仓储/FakeVerifier；FakeAuth 仅写入忽略目录的客户端副本，不修改生产 SDK。

证据保存在忽略目录 `.test-artifacts/pc04-community-integration/`；三次最终运行 `run-a6onlr`、`run-dZVFDD`、`run-ZhUf24`。本地合成 trace、截图、JSON/HTML/JUnit 不包含真实云凭据。真实验收工具禁止捕获这些凭据相关产物。

## 独立审查与未完成项

原只读后端 Python 审查 APPROVE。TS 复审 APPROVE，已修 ops 详情迟到恢复旧对象及多个公开昵称 Hook 竞争两项问题；对应单测及 3 次浏览器回归已通过。

最终通用代码及 Python 工具审查均 APPROVE；Python 独立组合 156 项及最终工具 28 项回归通过，Fake 夹具烟测通过。文档独立复核 APPROVE，8 份文档的 86 个相对链接有效。真实验收工具已修报告回执文案、分页上限和新令牌登记/清理三项缺陷；迟到写入使用原合成输入与原键落定后撤回，未确认的昵称写入清理不冒充通过。2026-10-11 自动审批曾遇到账户额度限制，被拦截动作未执行；10-12 额度窗口更新后正常审批和审查已恢复。尚未获得本轮云实施授权。

## 微信与真实云

| 层次 | 状态 |
| --- | --- |
| AUTOMATED 软件 | PASS；本地可执行验收与独立审查通过，GitHub CI 待推送 |
| PC04 REAL CLOUD | NOT TESTED / AWAITING AUTHORIZATION |
| 官方 WXSS 语法 | PASS，实际调用本机 wcsc；不是整项目运行验收 |
| PC04 WECHAT DEVTOOLS | PARTIAL：用户截图证明 PC04 REAL 社区页渲染；显示连接暂时中断及 1 个控制台错误，四入口/详情/投稿尚未完整验证 |
| CLI 桥接 | BLOCKED：前置读取的 `.ide-status`/`.ide` 文件缺失而报 disabled；本机 GUI 实际存在监听端口，不能据此推断 GUI 未登录或开关实际关闭。未伪造状态文件，用户无需重复登录 |
| PHYSICAL DEVICE | NOT TESTED |
| CloudBase 新资源 | NONE |

只读核验已确认既有环境 `soulcompanion-dev-d0dzo6f2a24211` / 上海、数据库 `tnt-28wj48qn2`、体验版、超额付费和自动续费 false，已有 HTTP 函数 Python3.11/256MB/3s、网关保留。未写集合、索引、marker、身份提供方、费用设置或真实社区数据。候选包、固定 PC03 回滚及有界合成流程见 [独立云计划](PC04_CLOUD_CHANGE_PLAN.md)。PC03 授权不继承。

2026-10-12 不带身份凭据的公开社区 GET 实际返回 HTTP 200、items 0，仅证明该公开端点在本机请求时正常。截图中的微信连接提示仍需对应控制台错误定位，不能据此认为用户未登录，也不能据此宣称微信请求通过。

微信登录开发者工具不等于小程序 CloudBase 登录，也不等于 CLI 服务端口可连接。当前工具无法直接查看/点击原生微信窗口，截图只能证明当时画面。后续按 [微信人工清单](PC04_WECHAT_MANUAL_CHECKLIST.md) 验证，不重复要求用户登录。

## 包体、依赖与费用

第一份真实 SDK 可比快照：main/total 1,829,515 → 分包后 main 1,750,966 / total 1,830,140 bytes；后续源码修补的最终快照另为 1,751,999 / 1,831,370。不混淆 SDK-disabled 与 SDK-enabled 数据；分包节省主要为低频页面，SDK 仍在共享主包。预算为项目守卫，不冒充微信官方当前上传许可或性能验收。

36 项既有依赖 finding 主要定位于 Taro 工具链；源码/版本图证据及未取得完整模块图的限制见 [依赖包体审计](PC04_DEPENDENCY_BUNDLE_AUDIT.md)。未修改 lockfile、禁用审计或 force 升级。体验版有期限和配额，不能称永久免费；没有购买/升级/超额付费/自动续费操作。

## 收尾与停止边界

复核全部独立审查、文档链接、secret 与最终 diff。独立确认 PC04 云计划和临时第二合成账户授权范围后，实施代码更新和真实官方 SDK UI 验收、finally 清理。正常提交/推送当前分支，核对本地远端 SHA 并等待所有 CI；更新本报告实际结果。

长期运营人员、微信真实账户/设备与扫码验收仍需用户准备。未指定真实审核员时不授予长期角色。PC05 需 PC04 完整交付与明确后续授权；当前不创建 PC05、不开发 AI、不发布微信、不切 Cloudflare Production、不合并 master。
