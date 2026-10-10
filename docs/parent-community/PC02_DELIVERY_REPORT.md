# PC02_DELIVERY_REPORT

更新：2026-10-10。

状态：PC02 软件本地测试 AUTOMATED PASS，修复后的函数代码与 version2 marker 已生效，15 项真实 CloudBase API、额外 11 项 API 与 12 项官方 H5 SDK 完整组合验收 REAL CLOUD PASS。最终软件代码及已核实远端 SHA 均为 `6c41d4b0854cc08f41edbdf66d8429ac93f82f6a`，其自身 9 项 CI job 全部通过。最终微信身份构建和手机验收仍待用户参与，不能描述为阶段全部完成。首次认证门槛失败及成功回滚保留为历史证据。

## PC02_CURRENT_STATE_AUDIT

开始时执行了 status、branch、fetch、分支列表、最近提交、diff 与 cached diff。工作区干净，当前分支及 upstream 均为 `pc-02-family-identity`，本地与远端 HEAD 同为 `fd3f3759e7b6555e4b2dfa5b20a01aadac6706ba`。未回退、清理、改写历史或合并 master。

| 基线 | SHA |
| --- | --- |
| Phase04 | `ce95b555bb1667ec653d05960ba2e47210b8b75d` |
| PC01 最新正式成果 | `a58320ba5384fff7b872ccbd450609088bdf53a4` |
| 本阶段父提交 / 已有 WXSS 修复 | `fd3f3759e7b6555e4b2dfa5b20a01aadac6706ba` |
| 独立微信兼容性提交 | `03a68adf12eddc498711f1ef5ff470fbca00cafa` |

共享入口为 Taro 4 / React / TypeScript 的 `apps/client`；默认路由为社区，详情和投稿是普通页面。H5 hash 路由与 weapp 页面路径共享业务意义。AppShell 为四主入口自绘导航，保留 Home/Session/Insights/Reports/Settings。使用既有设计 tokens、AccessibleButton、Primitives 与官方 CloudBase SDK，未增加 UI 框架或重复认证体系。

## 微信兼容性

源 WXSS 根因、列号与最小复现见 [原修复报告](PC02_WXSS_FIX_REPORT.md)，本次平台适配结果见 [兼容性报告](PC02_WECHAT_COMPATIBILITY.md)。裸伪类选择器是官方编译器可复现的问题；没有据旧报错列号认定 `.sc-history-cause` 或 `overflow-wrap:anywhere` 为根因。

保留生成样式检查与 22 项回归，官方编译器批处理全部 WXSS。新增原子跳转、浅栈返回、键盘生命周期和 600～767px 导航适配，保留 H5 布局、focus 和 reduced motion。微信 V1 无有效 HTTPS 地址时零相对路径请求并明确 OFFLINE，CloudBase V2 与媒体功能分别沿用。

用户已确认一次 DevTools 手动“编译成功，页面切换正常”。CLI 的预期 profile 目录缺少 `.ide-status` / `.ide`，所以连接前报服务端口关闭；具体同步失败原因仍未确定。没有伪造状态文件或预览结果。最终身份构建须再次人工验收，详见 [清单](WECHAT_MANUAL_CHECKLIST.md)。

## 身份与数据边界

- 微信继续通过官方 adapter / CloudBase SDK 登录。FastAPI 沿用在线验证与应用用户映射，全部新私有路由使用服务端验证的 user.id；不信任客户端 UID、OpenID、owner，也不签发替代 JWT。
- 家长社区资料独立于私有 `/me.display_name` 和儿童档案。认证后的 `GET/PUT /api/v2/parent-profile` 只投影独立公开 UUID、昵称和时间；没有公共作者查询或真实帖子 API。
- 昵称主动填写，NFC 规范化，2～24 个 Unicode 字符；禁止控制字符、链接、HTML、换行和表情；允许重名，昵称不是登录身份。不读取或预填微信头像/昵称，不从儿童资料复制。
- 儿童 `age_band` 可为空，六个年龄段与社区枚举一致；旧记录缺失按 null 读取。create/PATCH 字段一致，PATCH 缺省保留、null 清除；无需精确生日，不驱动社区筛选或投稿标签。
- `/api/v2/capabilities` 与独立 PC02 marker 控制新能力。未部署及旧服务器 404 表示不可用，原有昵称档案 CRUD 保留。只有 Settings 显式进入才读取新家庭资料，公共页面不启动私有请求。
- 退出、身份切换、页面作用域变化撤销迟到响应。保存锁覆盖写入与完整刷新；昵称读取等待/失败与成功空结果区分，不能把未加载当成未设置，不能重复点击创建档案产生额外 POST。
- 社区仍为合成示例，投稿仅内存预览；真实发布、审核、评论、点赞和收藏不在 PC02 实现。

## 增量 schema 与资源保护

新增 [002 manifest](../../cloud/schema/002_family_identity.json)、[独立增量工具](../../scripts/cloud_family_schema.py)、[代码部署/回滚工具](../../scripts/cloud_family_deploy.py) 及 [真实验收工具](../../scripts/cloud_family_acceptance.py)，默认纯离线 plan，apply 必须显式授权。完整目标、费用、验收和回滚见 [云变更计划](PC02_CLOUD_CHANGE_PLAN.md)。

2026-10-10 用户明确授权后，重新核查 `soulcompanion-dev-d0dzo6f2a24211` / 上海 / 体验套餐，超额付费与自动续费关闭；AppID、已有函数、网关、原 7 个集合 ACL 和13个索引匹配。实际新增一个 ADMINONLY 家长集合、一个唯一 owner 索引及独立 PC02 marker，更新过已有函数代码。没有购买或升级套餐、新增容器/GPU/应用存储桶、改网关、迁移旧数据或改变身份提供方。

001 原文件和 canonical checksum `7e23a3c17a1551df1d5a3c7c7c9deb8903f9ea7430fbd38e4fa482e85159fa49` 保持不变，无数据回填。工具绑定 001 / 002 / 运行时三方 hash，拒绝陌生集合、权限/索引不一致和 marker 竞争。首次 schema apply 的新集合、索引验证通过，marker 升到 version2；首次验收失败后精确关闭到0，新集合和全部数据保留。认证修复部署后，幂等 resume 再次核对 ADMINONLY 集合与唯一索引，将既有 marker 恢复到 version2，没有重复创建集合/索引或回填数据，付费开关仍关闭。

## 首次真实云验收与回滚

- 部署前保留并核对原 Phase04 ZIP（SHA256 `d1fda1c05f2a52daf6ae49d49141b4421d1a955c9eb916645ab952af9b240745`），现有远端 548 个文件与该历史包逐字节一致。环境仅有 `$LATEST`，未声称存在不可变旧版本。
- PC02 包按原 ZIP 字节通过 SCF 管理的临时 COS 上传，bootstrap 模式0755；远端代码和原函数配置验证通过。未创建应用存储桶、修改身份、网关、运行时、内存、超时或付费开关。
- 首次验收在登录前4个请求内失败：CloudBase 对合成无效 token 的 introspection 返回 HTTP400（`failed_precondition` / error code9），原验证器将其映射为503，未达到无效登录必须401的验收要求。该失败不能计为 REAL CLOUD PASS。
- 此次尚未进入合成账户登录或家庭资料操作，未创建 Auth 用户、未写入儿童/家长测试资料。在已授权回滚范围内关闭 marker 2→0并恢复原 Phase04 代码；548个远端文件、函数配置及 health/ready 均复核通过，保留新增集合和已有数据。

认证修复仅针对在线 introspection 的已观测拒绝响应：HTTP400、`error` 精确为 `failed_precondition` 且 `error_code` 为整数9时，返回401。未知400、错误结构、字符串/布尔/浮点代码以及超时、5xx继续返回503；合法身份的在线校验和所有权规则不变，不将 code9泛化为所有接口的无效 token。

新增 29 项认证边界回归通过，全量 cloud/cloud_tools 共 429 项通过，通用代码、Python 与安全审查均 APPROVE。

修复包上传后曾因下载校验暂时失败返回 `PRIVATE_DOWNLOAD_FAILED`，当时没有假定更新未生效或立即重复写入。随后安全只读获取远端 ZIP、验证下载 SHA 并逐文件比对：远端 549 个文件与当前修复包完全一致，bootstrap 模式 0755、函数配置未变。部署工具幂等重跑返回 `already_verified`，没有再次更新代码。随后 marker 幂等恢复到 version2，完整真实 API 验收通过。

| 修复包部署证据 | 已核实结果 |
| --- | --- |
| 本地 ZIP SHA256 | `81726829c4384d2474509cf382a5b38abd26c0ee0a265a32bcdf0df00956b6b6` |
| 包大小 / 文件数 | 3,608,251 字节 / 549 个文件 |
| 远端代码 SHA256 | `85ca02ba53b8dc8f7350f809d57abaa348f4a2d4eb62fce94ad00dfe55e82877` |
| 执行模式 / 配置 | bootstrap 0755；`configuration_unchanged=true` |
| 新代码部署资源 | 0；旧包与备份保留 |

代码更新/恢复证据与真实登录、资料读写和手机验收分别记录。

## 最终真实 CloudBase API 验收

在已授权环境执行真实验收，15 项检查全部通过：70 个请求，2 次受控限流重试，最大请求延迟 1,812ms。复用两个既有合成 CloudBase 用户，创建 Auth 用户数量为0。该结果使用官方 CloudBase 用户名登录后的真实 token，不代表微信扫码或微信手机登录通过。

- 匿名与合成无效 token 的私有访问返回401；两个主体映射稳定且互不相同，capabilities 正确开放新能力。
- 主动保存/读取独立家长昵称，严格公开 DTO 只包含规定字段；同名昵称允许而公开 ID 不同。客户端提交所有权字段被拒绝，原资料不受影响。
- 私有儿童年龄段创建、读取、修改、PATCH 缺省保留和 null 清除通过；非法年龄拒绝，跨用户访问统一拒绝，另一账户没有读到测试儿童。
- 用户 token 不能直接访问 ADMINONLY 家长集合；本轮新建合成儿童已归档并确认清理，两账户 token 已撤销，撤销后的私有请求返回401。

`child_cleanup_verified=true`、`api_token_cleanup_verified=true`，验收阶段为 `complete`。没有提交测试账户凭据、用户/儿童 ID、私有 DTO、数据库或媒体。

当前部署上额外执行既有 Phase04 API 回归，11 项全部通过、token 撤销验证通过。其官方 H5 SDK 浏览器脚本仍使用旧首页 `nav-settings` 入口，PC01 默认社区没有该控件，导致 `guest_boundary` 超时；不使用真实凭据的独立重现也在同一入口失败。仅将测试入口适配为“我的 → 未登录状态 → 私有账户”，保留全部12项 SDK/CRUD/退出/隐私断言，修改后的登录前 probe 通过公共路径零私有请求、零自动设备获取。完整组合第二次运行曾 FAIL，其具体失败阶段未获证明，不能将第一次旧入口根因套用到第二次失败。

随后复用既有合成账户，通过受保护 stdin 运行独立官方 SDK 浏览器流程，12项全部 PASS：匿名公共路径无私有请求/设备获取、真实官方 SDK 登录、服务端用户与私有界面读取、儿童新增/改名/选择/归档、退出隐藏私有数据、token 撤销、认证持久存储清理及原始媒体请求缺席。未创建新 Auth 用户。

最终再次执行完整 API/浏览器组合流程，`status=pass`、`browser_status=pass`，API11项与浏览器12项全部通过：62个请求、0次限流重试、最大延迟798ms。仍只复用两个既有合成账户，合成档案归档、会话结束、token撤销后拒绝访问及认证存储清理均保留，不读取真实儿童资料或启用物理麦克风。独立12项 PASS和完整组合 PASS分别记录；第二次失败具体阶段仍未获证明，不称所有尝试都通过，也不等于微信人工验收。

## 验证状态

| 范围 | 当前结果 |
| --- | --- |
| Python cloud / cloud_tools | AUTOMATED PASS：当前429项，包含增量 schema 分页、代码部署/真实验收工具及29项认证边界回归 |
| 客户端 typecheck / unit | AUTOMATED PASS：404 项 /21 文件；含 effect 执行前的同步草稿隔离 |
| H5 / weapp +官方 WXSS | AUTOMATED PASS：隔离回归 H5 1779 模块，含官方 SDK 的 H5 1793 模块；微信含官方 SDK 1294 模块，22 guard /3 WXSS 官方语法编译 PASS |
| 社区行为 / 七尺寸 | AUTOMATED PASS：最终身份集成产物 11 组 /28 视口样本，公共路径零私有请求与设备授权 |
| 旧 V1 E2E | AUTOMATED PASS：14 组，65 条历史和最终 ONLINE / 无 DEMO |
| 虚拟设备媒体 | AUTOMATED PASS：15 组；真机不是该测试范围 |
| 当前部署的 Phase04 API / 官方 H5 SDK | REAL CLOUD PASS：独立SDK浏览器12项通过，最终完整组合API11项/浏览器12项通过；62请求、0限流重试、最大798ms。第二次历史失败未改写，全部断言保留 |
| 依赖审计 | 策略 PASS：11 项；36 个既有 finding /10 个审查 advisory，非零漏洞 |
| 独立 Python / 增量工具审查 | APPROVE：已推送版本、新增工具与认证修复均已独立复核；认证修复通用代码、Python与安全审查均 APPROVE |
| 独立客户端 / 安全审查 | APPROVE；保存/读取状态与同步草稿隔离的 HIGH/MEDIUM 已修复并独立复核 |
| 正式 TypeScript / JavaScript reviewer | BLOCKED：规定 ESLint 命令因仓库无配置退出1；后续浏览器入口适配的正式 JS 审查同受此限制。未引入新依赖，不能写成 APPROVE |
| GitHub Actions | AUTOMATED PASS：最终软件提交 `6c41d4b0854cc08f41edbdf66d8429ac93f82f6a` 的 [run 38048536832](https://github.com/C1801SYQ/SoulCompanion-AI/actions/runs/38048536832) completed / success，9 项 job 全部通过；watch 返回0并以 run view 独立核实。前一认证/工具提交的 [run 38047875396](https://github.com/C1801SYQ/SoulCompanion-AI/actions/runs/38047875396) 亦为9项成功，不代替最终代码检查 |
| REAL CLOUD PASS | 最终 PC02 API 15 项检查通过；70 请求、2 次限流重试，两既有合成账户，儿童归档及 token 撤销均验证通过。首次失败与回滚保留为历史记录；不等于微信登录 PASS |
| WECHAT DEVTOOLS PASS | 兼容性构建由用户确认；最终身份构建 MANUAL_VERIFICATION_REQUIRED |
| PHYSICAL DEVICE PASS | NOT TESTED |

本地测试只用合成内容、Fake Adapter / Wire 或 Chromium 虚拟设备。不读取真实儿童资料、不上传音视频、不曝光密钥。不得将本地编译、Fake 登录或浏览器结果写成真实微信登录 PASS。

## 已知限制与交付回执

软件代码、安全和 Python 审查与可执行本地回归已完成，并正常推送到 `origin/pc-02-family-identity`。下表保存原身份版本、认证/工具及最终浏览器入口提交的证据；最终代码远端 SHA 已由 `ls-remote` 核实，最终软件提交自身 9 项 CI job 全部通过。独立 H5 SDK 和完整组合均已通过，最终报告作为后续独立文档回执提交。

| 交付回执 | 已核实结果 |
| --- | --- |
| 微信兼容性代码提交 | `03a68adf12eddc498711f1ef5ff470fbca00cafa` |
| 身份与家庭资料代码提交 | `b39a66147c2ed83fbe3a940b002114b8ebe1cdfd` |
| 初始身份软件版本 / 分支 | `b39a66147c2ed83fbe3a940b002114b8ebe1cdfd` / `origin/pc-02-family-identity` |
| 已部署认证修复 / 增量工具提交 | `5f29a7ae89829a14631e12de98bc3d7a1ffe8802`，已正常推送、9项 CI job通过；不含后续浏览器入口适配 |
| 最终软件代码提交 | `6c41d4b0854cc08f41edbdf66d8429ac93f82f6a` · `test: adapt cloud browser acceptance to community navigation` |
| 最终代码远端回执 | `origin/pc-02-family-identity`：`6c41d4b0854cc08f41edbdf66d8429ac93f82f6a`，普通 push 后以 `ls-remote` 独立核实 |
| 最终代码 GitHub Actions | [run 38048536832](https://github.com/C1801SYQ/SoulCompanion-AI/actions/runs/38048536832)：completed / success，9 项 job 全部通过 |
| 已推送文档回执 | `36fe207bde4adc4058c596ec50b1f402dae61475`；9项 CI job通过 |
| GitHub Actions | [run 38023145582](https://github.com/C1801SYQ/SoulCompanion-AI/actions/runs/38023145582)：completed / success，9 项 job 全部通过 |

以上 SHA 分别标识初始身份软件、已部署认证修复和最终浏览器入口适配。本报告的执行记录作为后续独立文档提交，其 SHA 由 Git 交付回执单独报告，不自引用；文档提交不替代软件代码 SHA。最终真实 API及H5 SDK验收已通过，但首次失败不会被改写为通过，也不将尚未执行的微信真机验收记为通过。

正式 TypeScript reviewer 因缺少 ESLint 配置未完成；现有 typecheck、全量单测、Ruff、JS 语法检查及独立 code-reviewer/安全审查均通过，没有安装新 lint 依赖来改变项目基线。Windows 首次非终端 E2E 启动无诊断退出，正式终端模式重跑及最终集成运行均完成全部断言，未修改或禁用测试。

真实云新增资源：1 个 ADMINONLY 家长集合、1 个唯一 owner 索引及独立 PC02 marker，已在用户限定授权下建立。首次失败时保留资源和数据、停用 marker 并回滚函数；修复后代码及 marker version2 已生效，真实 API 验收通过。没有新增付费资源，超额付费和自动续费关闭；扩大资源或费用范围须另行授权。微信扫码、真实微信登录和两个微信账号/真机验收须用户参与，具体步骤在人工清单，不要求提供密码、Token 或个人资料。

PC02 之后继续保留 PC01 原型状态；不建立 PC03 分支，不开发真实社区发布/审核，不自动合并 master，不调整 Cloudflare Production。
