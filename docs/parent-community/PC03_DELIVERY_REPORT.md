# PC03_DELIVERY_REPORT

日期：2026-10-11。范围：真正的家长社区后端、独立 schema 增量、权限/人工审核/并发控制及自动验收；**真实云实施等待 PC03 独立授权**。不是已上线社区，PC01 页面仍明确展示示例，PC04 前后端与运营界面接入未实施。

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

构建独立 Linux CPython3.11 部署候选：556 文件、3,626,906 字节，既有锁定依赖齐全、bootstrap 0755。候选 SHA-256：`72f754d3f96dc0cb941dceb27a891b82c81708dd36c104087df9172e6707f6ff`。三个工具离线 plan 均 PASS；包在忽略的 `.test-artifacts/cloudbase-pc03/`，未上传。PC02 固定回滚包 SHA：`81726829c4384d2474509cf382a5b38abd26c0ee0a265a32bcdf0df00956b6b6`，原包没有覆盖。

已只读重新核验精确既有环境、真实地域、运行数据库、体验套餐、付费开关与函数配置；见 [云变更计划](PC03_CLOUD_CHANGE_PLAN.md)。此次提供方摘要没有独立核对具体微信 AppID，不虚报绑定或手机登录。当前 PC03 新云资源 **NONE**、函数部署 **NONE**、角色授权 **NONE**、真实社区业务写入 **NONE**。

| 状态类别 | 结果 |
|---|---|
| AUTOMATED PASS | 已执行客户端全部八项；最终 Python/静态/独立审查回执见下表 |
| REAL CLOUD PASS | PC03 NOT TESTED；旧 PC02 PASS 属于历史证据 |
| WECHAT DEVTOOLS PASS | PC03 NOT TESTED；离线 wcsc 不替代真实预览 |
| PHYSICAL DEVICE PASS | NOT TESTED；真实微信登录仍需用户参与 |
| BLOCKED | 云实施 AUTHORIZATION REQUIRED（用户 PC03-I 明确门槛），本地开发未因此停下 |
| 真实社区前端/运营界面 | NOT IMPLEMENTED（PC04 范围） |
| AI 自动审核/诊断、媒体上传 | NOT IMPLEMENTED |

## 费用、隐私、限制与下一步

所有新集合 ADMINONLY；身份由服务端在线验证推导，公共 DTO 不带私有家庭字段。文本安全边界和字段投影不等于正文自动脱敏，真实人工审核仍需检查儿童姓名、学校、住址、联系方式、病史及未经支持的专业断言。不能声称 AI 审核或医学功效。

索引、文档和请求消耗现有体验配额，不保证永久免费。不开超额付费/自动续费、不购买或升级资源。配额是用户动作尝试预算，不能阻止多账户滥用；不退款未知结果，不自动清理历史配额。审计最多 32 条，普通操作保留最后隐藏/撤回容量。公共分页是排序边界而非跨请求数据库快照；运营队列变化可能影响后续页。

合法原子审核提交后 ACK 丢失可返回 503/INDETERMINATE；相同动作键核验不可变审计及当前状态，不声称所有 503 都零写入。真实 CloudBase 的新查询/索引和 3 秒函数预算仍须在授权后的合成验收验证，Fake HTTP 不能替代此环节。

下一步先取得 [PC03 云方案](PC03_CLOUD_CHANGE_PLAN.md)的独立授权，再限定目标增量、部署、短期合成运营授权、两个合成账户全链路验收与清理。正式运营人员身份由用户另行指定。PC03 真实验收和用户安排的微信手机验证完成前，不自动开始 PC04、创建后续分支或合并 master。

## 最终本地与 Git 交付回执

| 项目 | 当前记录 |
|---|---|
| 全量 Python 回归 | 1441 PASS，0 fail/error/skip；含 cloud/cloud_tools 1114 项；153.032 秒 |
| PC03 专项独立复测 | 685 PASS：domain197、API170、transport38、schema148、roles55、deploy77 |
| Ruff 全仓库 | PASS |
| Python3.11 AST | 13 个 PC03 生产文件 PASS；mypy/Black/Pylint/Bandit 未安装，NOT RUN |
| 独立部署代码审查 | PASS；PC03/PC02 部署共 140 项回归 PASS |
| 最终 Python/安全独立审查 | PASS；安全独立执行 schema/roles/deploy 280 项 Fake 全通过，无遗留 CRITICAL/HIGH/MEDIUM |
| 既有 acceptance / hardware smoke | PASS；hardware 为 FAKE 软件接口，真实设备 NOT TESTED |
| git diff --check / 相对文档路径 | PASS；26 相对链接目标存在，提交前复核 staged 文件 |
| 软件提交 SHA / 远端 SHA | 本地工作尚未提交推送，完成后登记独立回执 |
| GitHub Actions | 尚未触发 PC03 软件提交；不得继承 PC02 CI 成功 |

文档最终回执作为后续独立提交，SHA 由 Git 与交付消息报告，不在自身正文伪造自引用。软件提交与文档回执分开记录。
