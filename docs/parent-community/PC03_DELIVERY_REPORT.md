# PC03_DELIVERY_REPORT

日期：2026-10-11。范围：家长社区后端、独立 schema 增量、权限/人工审核/并发控制及自动验收；**用户已独立授权，真实云部署和社区后端 19 项合成验收 PASS**。PC01 页面仍明确展示示例，PC04 前后端与运营界面接入未实施，不称为已上线的真实社区产品。

## 基线与成果复用

分支 `pc-03-community-backend`，父提交及开始时本地/远端 PC02 均为 `39bf161b3a584fe545ae20553f3fc6087297d38d`；PC02 软件代码为 `6c41d4b0854cc08f41edbdf66d8429ac93f82f6a`。开始时工作区干净，从最新核实成果创建分支，无回退、强推、历史改写或 master 合并。

复用 CloudBase 官方在线认证、应用用户映射、FastAPI V2、现有 HTTP 文档数据库、PC02 公开家长昵称、私有家庭所有权、统一安全中间件、请求预算、锁定依赖和 CI。前端、媒体适配器、私有儿童/会话/情绪报告、001/002 schema 和 checksum 未改动。

具体审计见 [基线](PC03_BASELINE_AUDIT.md)，领域/索引/状态及失败语义见 [架构](PC03_ARCHITECTURE.md)，PC04 可直接采用 [API 契约](PC03_API_CONTRACT.md)。

## 实际软件交付

| 内容 | 实现与边界 |
|---|---|
| 独立后端模块 | community 模型、分页、存储协议、生产 HTTP 适配器、服务及路由；生产不选用内存 Fake |
| 帖子/一级评论 | 创建 pending，公开读取仅人工审核证据完整的当前 published；本人各状态私读、版本修改重新待审、软撤回 |
| 人工运营 | 每次查询可信 RoleBinding；当前正文 revision 与 row_version/status CAS，状态与不可变审计同一文档原子更新 |
| 点赞/收藏 | 确定性主键+唯一索引+CAS，同状态确认重试幂等；收藏私有、有界批量读取且过滤隐藏父帖 |
| 内容举报 | 与 CloudReport 隔离；举报人/目标/正文版本唯一，处理审计与状态同文档；处理不暗中跨文档隐藏 |
| 公共作者 | 复用本人 PC02 公开 UUID/昵称快照，绝不用孩子昵称、UID/OpenID、邮箱或电话；无昵称不阻碍浏览 |
| 数据增量 | 独立 003、5 ADMINONLY 集合、14 项目索引及独立 version0→3 reservation marker；全量验证旧依赖后才能增量 |
| 受保护工具 | 默认离线 plan；schema/roles 独立实际目标核验；角色只能管理 CLI 授予/撤销，HTTP 不提供自助管理员 |
| 部署与回滚 | 现有函数代码更新、包/成员/配置回读，固定 PC02 回滚包和冻结 PC03 归属证据；不改网关或费用 |
| 请求边界 | 纯文本、UTF-8/NFC、长度及 16KiB 请求限制、查询操作符白名单、绑定筛选游标、2.6 秒预算 |
| 配额 | 分布式 UTC 日动作 CAS，有限尝试/保守消耗；撤回不受贡献配额锁住，仍校验身份/版本/审计 |

没有新增框架/依赖或 lockfile 变更；没有 API key/Secret/AppSecret/Token、原始附件、儿童信息、数据库、音视频、node_modules 或 build artifact 提交。

## 独立审查及修复证据

存储、Python、代码及安全分别审查。已修复：

1. 查询条件全量预验证，空库/提前不匹配不能掩盖非法操作符；生产 HTTP 与 Fake 同一约束。
2. 作者撤回不扣投稿/评论配额；已有公开内容即使贡献配额耗尽仍能收回，增加两项行为测试。
3. 运营 revoke 不依赖用户仍 active；验证已有完整可信绑定即可撤销，覆盖禁用及缺失用户。
4. 新增实际 DescribeEnvInfo 验证，不能将旧 preflight 的常量地域当作真实证据；48 项错误目标/缺失/畸形响应均零写入。
5. 公共业务/存储回调类型边界和 Python3.11 语法检查，避免运行时或版本兼容回归。
6. PC02 回滚不依赖当前源/候选仍存在；经审查冻结的 PC03 包允许后续前向热修复，未知归属仍拒绝。
7. 真实云发现排序参数契约错误：生产适配器改为 `field/direction`，Fake 不再接受同样的错误形状，新增三个时间字段的空库回归。
8. 新增受保护的真实验收工具与 30 项 Fake 测试，覆盖失联授予/创建后的清理、错误目标零写入、匿名接口失败前置阻断及凭据保护。代码与 Python 独立审查均 APPROVE，独立复测 71 项（30 验收 + 41 传输）PASS。

最终审查结论与最终全量计数、Git 回执在文末记录。没有为通过测试删断言、降低限流或使用 continue-on-error。

## 客户端与跨端回归

Node.js 24.15.0；Python3.12.4；Chromium 浏览器测试使用合成内容与虚拟媒体设备。

| 验证 | 结果 |
|---|---|
| client:typecheck | PASS |
| client:test | 21 文件、404 项 PASS |
| client:build:h5 | PASS，1779 模块 |
| client:build:weapp | PASS，1280 模块；22 项 WXSS guard、3 生成 WXSS |
| 官方 wcsc 离线语法编译 | PASS，3 WXSS；不等于 DevTools/手机运行验收 |
| client:test:community | 11 组、28 响应式记录、42 年龄×话题组合；网络越界/公共异常均 0 |
| client:test:media | 15 组、6 尺寸；全部轨道结束、音频上下文关闭，attached video=0 |
| client:test:e2e | 14 组、30 响应式记录；ONLINE、history=65、无 DEMO，recovery_mode=manual；无 fatal/媒体权限请求 |
| client:audit | 11 项审计策略测试 PASS；36 项既有漏洞发现（6 moderate/29 high/1 critical），10 受审查 advisory 例外；不宣称零漏洞 |

首次 sandbox 导致 Vite realpath EPERM、0 项客户端单测执行；在同一授权范围正常本机权限重跑全部通过，没有改业务或断言。本阶段测试证据留在忽略的 `.test-artifacts/pc03-local/`，不提交可含本地路径的浏览器产物。

## Python、部署包与云状态

新增合成领域、真实 FastAPI HTTP、生产适配器 Fake REST、迁移/角色/部署工具测试；覆盖权限、错误编码、版本审核、隐藏父帖、确定性幂等、游标排序、CAS 竞争、配额、审计容量与不确定确认。全量回归包含 Phase04/PC02 原断言。

最终 Linux CPython3.11 部署包：556 文件、3,626,921 字节，既有锁定依赖齐全、bootstrap 0755；SHA-256：`835348e8c775cade98a6a263cce8990088c76c37019f61ebab2eecd2574246fe`。远端提供方重新压缩后的 SHA：`2e209953389a87a9ca222483aedc2d76c1e7173b5c21217fa06a7d7baf90adb2`；逐个 ZIP 成员与内容、模式核验通过，不要求不同压缩包字节相同。完整函数配置保持不变，已有网关未修改，旧包及原始候选均保留。PC02 固定回滚包 SHA：`81726829c4384d2474509cf382a5b38abd26c0ee0a265a32bcdf0df00956b6b6`，原包没有覆盖。部署包在忽略的 `.test-artifacts/cloudbase-pc03/`，不提交 Git。

实施前和受保护操作中重新核验实际环境 `soulcompanion-dev-d0dzo6f2a24211`、地域 `ap-shanghai`、唯一 RUNNING 数据库 `tnt-28wj48qn2`、体验套餐 `baas_trial`，超额付费与自动续费均 false；见 [云变更计划](PC03_CLOUD_CHANGE_PLAN.md)。新增 **5 个 ADMINONLY 集合、14 个项目索引及独立 003 marker（version3）**；仅更新已有 `sc-v2-api` 代码，HTTP/Python3.11/256 MB/3 秒与完整配置保留。001/002 checksum、marker、旧 8 集合 ACL/索引定义未修改；旧 API 验收仅在这些集合操作限定的合成家长资料、新建合成档案与会话，不改真实用户数据。无回填、数据迁移或物理删除。没有新增付费服务、容器、GPU、函数、网关或身份提供方。此次提供方摘要没有独立核对具体微信 AppID，不虚报绑定或手机登录。

| 状态类别 | 结果 |
|---|---|
| AUTOMATED PASS | 客户端全部八项、1474 Python 回归、静态与独立审查通过，见下表 |
| REAL CLOUD PASS | PC03 社区后端 19 项、PC02 家庭回归 15 项 PASS；额外旧 API / H5 SDK 结果见下文 |
| WECHAT DEVTOOLS PASS | PC03 NOT TESTED；离线 wcsc 不替代真实预览 |
| PHYSICAL DEVICE PASS | NOT TESTED；真实微信登录仍需用户参与 |
| BLOCKED | NONE（本阶段已授权软件与合成云验收）；正式运营身份及真实微信手机验收仍需要人工参与 |
| 真实社区前端/运营界面 | NOT IMPLEMENTED（PC04 范围） |
| AI 自动审核/诊断、媒体上传 | NOT IMPLEMENTED |

## 费用、隐私、限制与下一步

所有新集合 ADMINONLY；身份由服务端在线验证推导，公共 DTO 不带私有家庭字段。文本安全边界和字段投影不等于正文自动脱敏，真实人工审核仍需检查儿童姓名、学校、住址、联系方式、病史及未经支持的专业断言。不能声称 AI 审核或医学功效。

索引、文档和请求消耗现有体验配额，不保证永久免费。不开超额付费/自动续费、不购买或升级资源。配额是用户动作尝试预算，不能阻止多账户滥用；不退款未知结果，不自动清理历史配额。审计最多 32 条，普通操作保留最后隐藏/撤回容量。公共分页是排序边界而非跨请求数据库快照；运营队列变化可能影响后续页。

合法原子审核提交后 ACK 丢失可返回 503/INDETERMINATE；相同动作键核验不可变审计及当前状态，不声称所有 503 都零写入。真实合成验收已覆盖新查询/分页/版本修改/审核及收尾，未提高 3 秒函数预算；该有界验收不替代生产并发负载、长期稳定性或真实微信验收。受控分页检查假设验收帖子是该年龄筛选下的最新内容，其他同时投稿会导致保守失败，不能冒称数据库快照。

PC03 已按 [独立云方案](PC03_CLOUD_CHANGE_PLAN.md)授权实施。用户后续需指定真实运营审核人员、准备两个有权限的微信测试账户和真机，并按 [微信检查表](WECHAT_MANUAL_CHECKLIST.md)验证登录、账户切换、家庭隔离、退出与设备生命周期。真实社区页面接入仍属 PC04，届时另行确认运营与测试计划；本阶段停止，不创建 PC04 分支、不修改 Cloudflare Production 或合并 master。

## 真实实施、失败与恢复记录

1. 首次 schema apply 返回 `NETWORK_ERROR`，没有当作成功。只读核验确认属于本项目的 version0 reservation、2 个新集合及已有部分索引；随后按同指纹增量恢复，补齐剩余 3 集合/4 索引，最终 5 集合/14 索引全量回读，marker CAS 晋升 version3。旧资源写入为空。
2. 初始包 `72f754d3f96dc0cb941dceb27a891b82c81708dd36c104087df9172e6707f6ff` 已核对代码，但匿名社区列表 503。空库实际 REST 隔离证明 Mongo 风格 `[{"published_at":"desc"},{"id":"desc"}]` 返回 HTTP500 / `DATABASE_REQUEST_FAILED`，正确 `field/direction` 返回 HTTP200/空列表。此时没有登录、授权运营或创建社区内容。
3. 依方案实际恢复固定 PC02 包，逐成员核验与完整配置保持不变；schema、历史与新集合保留。回滚提供方包 SHA `85ca02ba53b8dc8f7350f809d57abaa348f4a2d4eb62fce94ad00dfe55e82877`。修复源适配器并增加严格传输回归，408 项领域/API/传输 PASS；随后部署上述最终包并确认匿名社区接口 200。
4. 首轮业务验收在 `role_grant` 阶段未确认，帖子/评论尝试数均 0，角色与本轮令牌清理记录为 true。进一步只读确认两合成用户 active、角色绑定均 absent；没有盲目重放未知授予。具体失败码未保留，不能倒推为网络问题或产品缺陷。固定白名单诊断的新轮次完整通过，grant/revoke 均读回确认。
5. 最终社区验收：19 项 PASS、101 请求、1 次按 Retry-After 的 429 重试、最大请求耗时 2250ms；创建尝试仅 3 合成帖子/1 合成评论/1 合成举报，没有新用户。本人待审私读、他人越权、当前版本审核、编辑重排队/旧审核409、年龄话题 AND/游标、评论直接 URL、点赞收藏幂等及私有性、举报去重/处理、隐藏父帖均通过。
6. 收尾：角色 revoke 后运营接口403，4 条本轮内容软撤回读回，关系 inactive 或父帖不可公开，本轮两令牌撤销后私有 API401；全部 cleanup true。保留不可变审核/角色/举报审计和配额，没有删库、销毁用户或恢复公开合成内容。
7. 旧家庭回归首轮在合成认证阶段停止，尚未创建新档案，完整两账户令牌验证未达到 PASS（摘要 false），未抹去该失败。受控诊断的新轮次完成 15 项 PASS：70 请求、2 次429重试、最大耗时5017ms（包括 CloudBase 身份服务）；合成档案归档、两令牌验证和剩余令牌为空均确认。未关闭限流、延长函数预算或降低断言。

全部业务与 H5 回归完成后再次只读核验 PASS：实际目标和体验套餐匹配、超额付费/自动续费 false，001/002/003 marker 完整，两个合成运营绑定状态分别 absent/revoked，匿名社区列表为空且无下一页；没有为最终检查执行云写入。

证据是忽略目录中的脱敏结果 JSON、测试 XML 和私有回滚包。真实验收由 [cloud_community_acceptance.py](../../scripts/cloud_community_acceptance.py) 执行；默认离线 plan，双参数授权后才实际调用。第二轮诊断只包裹同一工具的受保护角色调用与固定错误码输出，没有改业务、断言或清理行为。

额外旧 API 11 项 PASS：账户稳定、档案 CRUD、会话结束幂等、越权/未知记录404、客户端身份/原始媒体字段拒绝、数据库直连拒绝、无虚构情绪/报告、档案归档及退出令牌拒绝；本轮 API 令牌清理 true。首次随后执行官方浏览器阶段失败，普通本地构建没有配置公开 API，SDK 被编译裁剪，账号提示“云端账号尚未配置”，停在登录前的访客状态断言。一次补配置误带 `/api/v2` 路径，也被既有 origin 校验拒绝，没有继续实际登录。

重新按 [客户端配置](../../apps/client/config/index.ts)设置 `PUBLIC_API_BASE_URL=https://soulcompanion-dev-d0dzo6f2a24211-1501181209.ap-shanghai.app.tcloudbase.com`（只用 origin，路径由 API 模块添加），`PUBLIC_DEMO_ONLY=false`、`CF_PAGES=0`，本地 H5 构建 PASS（1793 模块，27.14 秒）。随后只复用一个既有合成账户执行原有 `cloud_browser.cjs`，12 项全部 PASS：访客无私有请求、官方 SDK 登录、当前用户 UI、合成档案创建/改名/选中/归档、退出清空私有 UI、令牌401、凭据无持久存储/ Cookie、无自动设备权限或原始媒体请求。未修改客户端源码、断言、Cloudflare Production 或云配置；官方 H5 SDK PASS 不等于微信登录/DevTools/手机 PASS。

## 最终本地与 Git 交付回执

| 项目 | 当前记录 |
|---|---|
| 全量 Python 回归 | 1474 PASS，0 fail/error/skip；cloud/cloud_tools 1147 项；143.810 秒；含全部 Phase04/PC02 和新增验收工具 |
| PC03 专项 | 718 项：domain197、API170、transport41、schema148、roles55、deploy77、acceptance30；均在全量回归中通过 |
| Ruff 全仓库 | PASS |
| Python3.11 AST | 13 个 PC03 生产文件及新增验收工具/测试 PASS；mypy/Black/Pylint/Bandit 未安装，NOT RUN |
| 独立部署代码审查 | PASS；PC03/PC02 部署共 140 项回归 PASS |
| 最终 Python/安全独立审查 | PASS；安全独立执行 schema/roles/deploy 280 项 Fake 全通过，无遗留 CRITICAL/HIGH/MEDIUM |
| 既有 acceptance / hardware smoke | PASS；hardware 为 FAKE 软件接口，真实设备 NOT TESTED |
| git diff --check / 相对文档路径 | PASS；六篇当前文档 35 个相对文件链接目标均存在，独立文档审查 APPROVE |
| 凭据与提交边界 | 301 个 tracked 文件及最终部署 ZIP 在内存中扫描实际服务端 key 均未命中；凭据模式检查 PASS，无客户端/lockfile/构建产物变更，001/002 字节保持基线 |
| 基础软件提交 | `c7d4cec3cd7de744630d5636792ad1097912ba25` · `feat: add parent community domain and moderation backend`；[CI 38109593239](https://github.com/C1801SYQ/SoulCompanion-AI/actions/runs/38109593239) 9/9 PASS |
| 云 REST 排序修复 | `b056f40d64b91a20398d155b3919f18d047de808` · `fix: align community sorting with CloudBase REST contract`；[CI 38111136373](https://github.com/C1801SYQ/SoulCompanion-AI/actions/runs/38111136373) completed/success |
| 受保护验收工具及测试 | `4fbc2d0b3a69dce83f694b8024629201e40b46b7` · `test: verify real community workflow and cleanup`，普通 push 后远端 SHA 独立核验一致 |
| 新工具 GitHub Actions | [run 38111589516](https://github.com/C1801SYQ/SoulCompanion-AI/actions/runs/38111589516)：completed/success，9/9 job PASS；包括 Python3.11 云回归、全部客户端和依赖审计 |

最终文档回执作为后续独立提交，最新本地/远端 SHA 与该文档提交的 CI 由 Git 及交付消息报告，不在正文伪造自身 SHA。软件提交和实际验收在上表逐项记录，文档提交不改变部署软件。当前工作停止在 PC03，不自动进入 PC04。
