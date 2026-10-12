# PC04_DELIVERY_REPORT

更新：2026-10-12。**软件、CI 与独立授权的真实 CloudBase 合成 UI 验收 PASS；微信完整人工及手机验收尚未完成。** 本报告区分已经取得的证据和待执行项，不将本地 Fake、构建或截图计为完整微信验收。

## 基线与 Git

开始时工作区干净；核对后的 PC03 本地/远端 SHA 均为 `c0098ae538128bff6d8f76a20ec8c6a2d52fcb64`。当前分支 `pc-04-community-integration`，从该基线创建。已提交软件 `833767272abf4046067f5c6e3473d12e6d64a8df` 与测试工具 `b59a70ad4dfd4f6e86aa189599e20ec6341550da`。首轮软件/文档 HEAD `4cc94eead2e697e89d7b552f6e354cd74a094f40` 已推送，实际远端 SHA 一致；[软件 CI](https://github.com/C1801SYQ/SoulCompanion-AI/actions/runs/38155411038) 10/10 jobs success。

真实云回执保存于 `ce6a64d754cbd36c94f97dcd5a2bb173583da544`，实际本地与远端 SHA 一致；后续仅完善文档元数据。最终记录提交与远端分支 HEAD 见 [分支提交历史](https://github.com/C1801SYQ/SoulCompanion-AI/commits/pc-04-community-integration)，对应工作流见 [PC04 CI](https://github.com/C1801SYQ/SoulCompanion-AI/actions?query=branch%3Apc-04-community-integration)。交付回复另列最终本地/远端 SHA 和实际 CI 结果，避免在文档中填入其自身尚未生成的提交哈希。master、历史分支、schema 001/002/003 与原成果保留。

## 已实现的软件

- 专用社区 DTO、严格请求/响应验证、受控 transport、API 和有界内存 store；共用现有官方 CloudBase auth，不重复认证。公共 GET 无 token，私有请求受 subject/auth epoch 保护，旧 401 或迟到响应不影响新账户。
- REAL/DEMO 显式分离；REAL 空库/错误不切示例。Cloudflare Pages 保持 DEMO_ONLY，未改生产配置。
- 真实列表、六年龄/七话题 AND 筛选、倒序、cursor、加载更多、刷新和竞态隔离。REAL 返回列表保留筛选并明确重新验证、回到顶部；DEMO 保留旧滚动恢复。
- 真实详情、待审投稿/一级评论、本人投稿/评论/收藏、当前版本反馈、版本化编辑与撤回、点赞收藏确认和举报。纯文本展示，无假计数；503 保留原输入和动作键，不显示假成功。
- 独立 `pages/ops/index` / H5 `#/ops`，普通主导航不显示管理入口。服务端核验角色；全文、当前 revision、理由、人审提醒、通过/拒绝/隐藏、举报独立处理与回执。403 清空受保护界面，旧详情在切 Tab、筛选、刷新和身份变化后失效。
- 公开昵称 Hook 独立实例请求槽，避免缓存页面互相取消；返回重新读取，账号作用域操作锁。社区不读取儿童档案/报告，不自动采集或上传媒体。
- 普通微信分包：Home/Session/Insights/Reports/Settings/ops；主包保留四入口、详情、投稿和本人页面。原路径不变，共享认证，`lazyCodeLoading:requiredComponents`。

主要文件位于 `apps/client/src/community/`、`state/CommunityProvider.tsx`、社区/我的/运营页面、AppShell、navigation 和 app 配置。新增 API 仅两个认证只读 GET，见 [最小契约扩展](PC04_API_EXTENSION.md)；独立授权后已有真实云函数代码已更新。

## 已取得自动证据

| 项目 | 实际结果 |
| --- | --- |
| TypeScript | PASS；最终普通 UI 及 ops 修复后独立复核通过 |
| 前端单测 | PASS，25 suites / 512 tests；保留旧私有 getter 陷阱及导航断言 |
| 完整 Python | PASS，本地全量快照 1545 tests / 0 fail / 0 error / 0 skip / 269.810s；最终新增工具回归独立通过，本轮 CI 全量 1554 项通过，云相关 1227 项通过（工作流日志 progress 点及无其他结果核对） |
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
| GitHub Actions | PASS，软件/首轮文档 SHA `4cc94ee` 的工作流 10/10 jobs success；文档记录提交结果按上方 PC04 CI 与交付回复核验 |

视口：375×812、390×844、430×932、600×900、767×1024、768×1024、1440×900。Fake 集成中家庭私有接口、媒体权限、外网、角色授予 HTTP 与未捕获异常均为 0。实际 FastAPI 路由配 InMemory 仓储/FakeVerifier；FakeAuth 仅写入忽略目录的客户端副本，不修改生产 SDK。

证据保存在忽略目录 `.test-artifacts/pc04-community-integration/`；三次最终运行 `run-a6onlr`、`run-dZVFDD`、`run-ZhUf24`。本地合成 trace、截图、JSON/HTML/JUnit 不包含真实云凭据。真实验收工具禁止捕获这些凭据相关产物。

## 独立审查与未完成项

原只读后端 Python 审查 APPROVE。TS 复审 APPROVE，已修 ops 详情迟到恢复旧对象及多个公开昵称 Hook 竞争两项问题；对应单测及 3 次浏览器回归已通过。

最终通用代码及 Python 工具审查均 APPROVE；Python 独立组合 156 项及最终工具 28 项回归通过，Fake 夹具烟测通过。文档独立复核 APPROVE，8 份文档的 86 个相对链接有效。真实验收工具已修报告回执文案、分页上限和新令牌登记/清理三项缺陷；迟到写入使用原合成输入与原键落定后撤回，未确认的昵称写入清理不冒充通过。2026-10-11 自动审批曾遇到账户额度限制，被拦截动作未执行；10-12 额度窗口更新后正常审批和审查已恢复。2026-10-12 用户明确授权本轮 PC04 计划；仅覆盖计划内更新和合成验收。

## 微信与真实云

| 层次 | 状态 |
| --- | --- |
| AUTOMATED 软件 | PASS；本地可执行验收、独立审查和软件工作流通过 |
| PC04 REAL CLOUD | PASS，官方 SDK + 真实页面 + 既有 CloudBase 合成闭环，21 检查 / 0 清理失败；不代表微信账户或手机通过 |
| 官方 WXSS 语法 | PASS，实际调用本机 wcsc；不是整项目运行验收 |
| PC04 WECHAT DEVTOOLS | PARTIAL：用户截图及当前窗口读取证明 PC04 REAL 社区页渲染；Console 明确显示当前 API 不在 request 合法域名列表，网络配置 BLOCKED；修复后的四入口/详情/投稿尚未完整验证 |
| CLI 桥接 | BLOCKED：前置读取的 `.ide-status`/`.ide` 文件缺失而报 disabled；本机 GUI 实际存在监听端口，不能据此推断 GUI 未登录或开关实际关闭。未伪造状态文件，用户无需重复登录 |
| PHYSICAL DEVICE | NOT TESTED |
| CloudBase 新资源 | NONE |

实施前再次确认既有环境 `soulcompanion-dev-d0dzo6f2a24211` / 上海、数据库 `tnt-28wj48qn2`、体验版、超额付费和自动续费 false，已有 HTTP 函数 Python3.11/256MB/3s、网关保留。已有 `sc-v2-api` 代码更新返回 code_verified、configuration_unchanged true、backup_retained true、new_resources 0。候选 ZIP SHA-256 `0c1158295656a4f2982217cceed0a04342b2a7d8cd583b7f1290ad445dd82bf7`；平台下载 ZIP SHA-256 `ca7dee86ffa75de9e8e128c781339cd56d858283fc0d5828a0f68ca4d66e4114`，工具逐成员内容与权限核验一致，不要求平台重打包字节一致。实际 `/api/v2/healthz`、`readyz`、公开列表 HTTP 200；匿名 me 和新增两 GET HTTP 401。没有集合、索引、marker、身份提供方或费用设置变更。候选包、固定 PC03 回滚及有界合成流程见 [独立云计划](PC04_CLOUD_CHANGE_PLAN.md)。PC03 授权不继承。

真实页面执行通过：两位既有专用合成账户以官方 SDK 登录，公开家长昵称、A 投稿 pending/匿名不可见、B 临时 moderator 审核、公开列表/筛选、B 评论 pending/审核、确认点赞收藏、举报和独立处理、A 撤回/公开不可见、退出清空私有状态。浏览器禁止家庭/媒体/其他外网请求，不记录 trace、截图、HAR、令牌或身份日志；没有新账户。

回执 `PC04_ACCEPTANCE_PASS`：21 检查均 true，最多实际尝试 1 帖/1 评论/1 举报，cleanup_failures 0。合成内容已软撤回、举报已处理或确认不存在、关系关闭或父帖不公开、昵称恢复、临时 moderator 已撤销、签发令牌已撤销并验证。保留应有审计与撤回记录，没有物理删除历史数据。只含布尔检查与计数的安全回执位于忽略目录 `.test-artifacts/cloudbase-pc04/pc04-real-ui-acceptance.json`。该结果不会作为微信手机登录证据。

2026-10-12 不带身份凭据的公开社区 GET 实际返回 HTTP 200、items 0，仅证明该公开端点在本机请求时正常。用户随后提供 Console：Stable 2.02.2608080 / 基础库 3.17.4，00:47:10 明确拒绝 `https://soulcompanion-dev-d0dzo6f2a24211-1501181209.ap-shanghai.app.tcloudbase.com`，现有 request 合法域名只有旧 tcb.qcloud.la 域名与 tcb-api.tencentcloudapi.com。因此当前微信社区请求失败的实际原因已定位为服务器域名配置缺项，不是登录或 WXSS 问题。

除该 API origin，官方 SDK 3.10.1 默认 GATEWAY 模式及现有 `signInWithOpenId({useWxCloud:false})` 还需要 `https://soulcompanion-dev-d0dzo6f2a24211.api.tcloudbasegateway.com`。第二项由已安装官方 SDK/微信适配器源码核对，不冒充已取得微信登录结果。管理员需在既有 AppID 的 request 合法域名中保留旧项并添加这两项，然后刷新开发者工具“详情 → 域名信息”并重新编译，保持 `urlCheck:true`。当前 6 个分包及按需组件加载已有运行日志证据；弃用、灰度基础库及 preload 警告没有造成该域名拒绝的证据。不修改业务代码或将 API 切换到未经验证的旧域名。

本轮 computer-use 已实际读取原生开发者工具窗口，修正此前“无法直接查看”的工具能力判断；一次菜单点击返回 unknown screenshotId，不计为成功操作。CLI 状态文件缺失与 GUI 登录是两个问题。浏览器安全策略禁止访问微信公众平台管理站点，未执行域名配置写入；当前等待管理员配置和回测。微信登录开发者工具不等于小程序 CloudBase 登录，也不等于 CLI 可连接。后续按 [微信人工清单](PC04_WECHAT_MANUAL_CHECKLIST.md) 验证，无需重复登录开发者工具。

## 包体、依赖与费用

第一份真实 SDK 可比快照：main/total 1,829,515 → 分包后 main 1,750,966 / total 1,830,140 bytes；后续源码修补的最终快照另为 1,751,999 / 1,831,370。不混淆 SDK-disabled 与 SDK-enabled 数据；分包节省主要为低频页面，SDK 仍在共享主包。预算为项目守卫，不冒充微信官方当前上传许可或性能验收。

36 项既有依赖 finding 主要定位于 Taro 工具链；源码/版本图证据及未取得完整模块图的限制见 [依赖包体审计](PC04_DEPENDENCY_BUNDLE_AUDIT.md)。未修改 lockfile、禁用审计或 force 升级。体验版有期限和配额，不能称永久免费；没有购买/升级/超额付费/自动续费操作。

## 收尾与停止边界

软件、工具审查、授权范围内的真实 UI/清理和回执文档推送已完成。最终记录提交的远端一致性与 CI 结果在交付回复中给出。微信网络错误原因已定位；域名配置后的完整人工运行、真实微信登录及手机验证仍按清单等待用户，不会将这些项目写成 PASS。

长期运营人员、微信真实账户/设备与扫码验收仍需用户准备。未指定真实审核员时不授予长期角色。PC05 需 PC04 完整交付与明确后续授权；当前不创建 PC05、不开发 AI、不发布微信、不切 Cloudflare Production、不合并 master。
