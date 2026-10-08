# PHASE 04 DELIVERY REPORT

最后更新：2026-10-08（Asia/Shanghai）。

**状态：PASS（云后端开发、部署与自动验收）。** 实际 CloudBase API 11 项和官方 SDK H5 浏览器 12 项检查全部通过，覆盖真实认证、档案/会话、所有权隔离、退出撤销和隐私边界。最终 Python 513 个测试、客户端 241 个测试、三次连续 E2E、media、类型、lint、构建与依赖审计策略检查通过。验收后当前使用 1.45/3000 套餐内资源点、按量计费用量 0 点，超额付费和自动续费关闭。实际验收代码 `0ee5b4e` 已推送，同一提交九个 CI 作业全部成功。微信 DevTools 与物理手机仍 NOT TESTED，后续人工步骤明确列出，不以 H5 或构建结果替代微信设备证据。

## 1. Preflight state

本地仓库为 `D:\SoulCompanion_AI`，远程为 [SoulCompanion-AI](https://github.com/C1801SYQ/SoulCompanion-AI)。在 Phase 03 后创建并使用 `04-cloud-backend`。已完成只读环境与资源审计后，再沿用户授权的零付费路径实施。未合并 `master`，未创建 Phase 05 分支。

## 2. Parent Phase03 SHA

父提交为 `2626fa387be793cbc27157f273494357b47ef8bc`：`test: remove backend recovery race from client e2e`。Phase 03 断网恢复测试保留 AUTO_RETRY 与 MANUAL_RETRY 两条合法路径，并保留 ONLINE、历史 65 条和 DEMO badge 隐藏断言。最终远程引用复核确认 Phase 03 分支仍指向该提交。

## 3. CloudBase environment verified

用户确认使用已有环境 `soulcompanion-dev-d0dzo6f2a24211`，地域 `ap-shanghai`，别名 `soulcompanion-dev`。实际 CLI 审计显示环境 NORMAL。没有创建第二个环境。附件中的旧环境 ID 不再作为部署目标。公开小程序 AppID 为 `wx11a055ed4dc69764`。

## 4. CloudBase resources discovered

初始审计发现一个 RUNNING 文档数据库实例 `tnt-28wj48qn2`、一个默认 HTTPS 网关域名，零项目集合、零云函数和零网关路由。用户名认证已启用；邮箱、手机和匿名登录未启用。微信小程序认证提供方与上述 AppID 一致。当前已新增七个集合、十三个索引、一个 HTTP 云函数和现有默认域名上的一个 `/` 路由，见第 7、14、15 节。

## 5. Cost / FREE status

实际套餐为 `baas_trial` 体验版，包含 3000 资源点，体验期截至 2027-04-07。完整真实验收后的最终费用审计再次确认 `EnableOverrun=false`、`IsAutoRenew=false`，现有函数和路由配置一致。它是有限期免费额度，不能描述为永久免费或无限资源。未购买升级、开启付费超额、自动续费、预热实例、VPC、GPU 或托管 PostgreSQL，未出现 `PAID_RESOURCE_REQUIRED`。本轮免费配置保持 PASS；当前账期与原始用量字段见第 25 节。

## 6. Database decision

采用环境中已有的 CloudBase 文档数据库。MySQL 未启用，无法证明启用路径满足本轮零付费限制；没有据此断言所有 MySQL 方案都收费。文档数据库支持所需元数据和索引，并能使用 ADMINONLY 权限限制客户端直连。选择依据记录在 [DATABASE_DECISION.md](DATABASE_DECISION.md)。本地 V1 SQLite 数据未迁移。

## 7. Database resources created

真实环境已创建并验证七个 ADMINONLY 集合：`sc_v2_users`、`sc_v2_identities`、`sc_v2_child_profiles`、`sc_v2_sessions`、`sc_v2_emotion_records`、`sc_v2_reports`、`sc_v2_app_schema`。十三个索引的名称、字段顺序、方向和唯一性已核对；应用 schema marker 为版本 1。可复现声明为 [001_metadata.json](../../cloud/schema/001_metadata.json)，执行器为 [cloud_schema.py](../../scripts/cloud_schema.py)。操作只增建、不删除集合或索引，并拒绝所有权或 marker 版本不符的命名空间。

## 8. Authentication design

CloudBase Auth 是唯一身份来源。客户端使用官方 `@cloudbase/js-sdk` 3.10.1，服务端每次通过当前环境的在线 token introspection 验证访问令牌及主体。没有自行保存密码、签发 JWT、相信客户端 UID/OpenID，或使用测试适配器作为真实身份。客户端 token/refresh token 只存内存；刷新后重新登录。服务端管理员 key 只进入忽略的本地部署配置和托管函数环境变量。

## 9. WeChat authentication result

微信认证提供方在实际环境中为启用状态，AppID 已核对。小程序适配器实现官方 SDK `signInWithOpenId({ useWxCloud: false })`，原生适配器内存存储回归测试通过。**实际开发者工具和手机微信登录均 NOT TESTED**；提供方存在、编译和模拟 SDK 测试不能作为实际微信登录 PASS。

## 10. Web authentication result

环境用户名认证已启用，H5 实现官方 SDK 用户名/密码登录、退出、错误提示和私有页面清理。退出会检查 SDK 返回的错误，不能把未确认的撤销显示为成功。两个现有合成身份的实际 CloudBase REST 登录和在线 introspection 通过；官方 SDK 的实际 H5 浏览器登录、用户加载、档案操作、退出清除私有 UI、旧 token 401 与内存存储边界也通过。Web Auth 的 REST 与浏览器证据分别取得，结果 PASS。

## 11. Principal normalization

服务端将已验证环境与主体映射为确定性应用用户 UUID 和身份 UUID，避免首次并发请求产生两个应用用户。注册采用确定性 ID 的原子 POST 创建及不可变身份字段的 canonical readback 校验；不使用当前 CloudBase NoSQL 路径不支持的 `$setOnInsert`。并发创建冲突后必须核对已有记录，不能覆盖不同主体的身份。身份映射留在服务端；不同 CloudBase 主体不会自动关联为同一个用户。真实验收确认两个应用用户彼此不同，重复请求的应用用户 ID 稳定，昵称修改持久化。

## 12. Ownership / IDOR model

所有私有查询、更新、归档和结束操作带有服务端推导的 owner 条件。实际双账户验收覆盖所有相关动作与过滤路径，跨所有者和不存在资源统一 404；owner/UID/OpenID、原始媒体和操作符字段请求返回 422。实际匿名 `/api/v2/me` 返回 401，直接使用用户令牌访问数据库返回 401/403。ADMINONLY 集合和应用 owner 检查的实际隔离结果 PASS；列表分页与字段边界仍由服务端强制执行。

## 13. FastAPI V2 routes

独立入口 [cloud/api/app.py](../../cloud/api/app.py) 与 [soulcompanion_cloud/app.py](../../cloud/api/soulcompanion_cloud/app.py) 不加载 V1 推理或设备模块。实际 HTTPS health 返回 200/ok、ready 返回 200/healthy、匿名 me 返回 401；下列元数据业务路径已纳入真实 CloudBase 验收并通过：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/v2/healthz` | 公共健康检查 |
| GET | `/api/v2/readyz` | 认证配置、数据库 marker 与集合就绪检查 |
| GET / PATCH | `/api/v2/me` | 当前应用用户与昵称 |
| GET / POST | `/api/v2/children` | 档案列表与创建 |
| GET / PATCH / DELETE | `/api/v2/children/{child_id}` | 档案查看、修改、归档 |
| GET / POST | `/api/v2/sessions` | 会话元数据列表与创建 |
| GET | `/api/v2/sessions/{session_id}` | 会话元数据详情 |
| POST | `/api/v2/sessions/{session_id}/end` | 幂等结束会话 |
| GET | `/api/v2/emotions` | 只读情绪记录 |
| GET | `/api/v2/reports` | 只读报告列表 |
| GET | `/api/v2/reports/current` | 当前报告或明确空状态 |

## 14. HTTP Function deployment

`sc-v2-api` 已在实际环境创建，并核对所有权描述、Python 3.11、256 MB 内存、3 秒超时和 HTTP 类型。没有预热实例。最新身份注册修复包已更新同一个函数，现有路由保持一致，未重建资源。部署包 SHA-256 为 `d1fda1c05f2a52daf6ae49d49141b4421d1a955c9eb916645ab952af9b240745`，3,605,658 字节、548 个文件、17 个固定 Linux CPython 3.11 依赖。使用 SCF 管理的临时上传路径，不创建应用存储桶或上传用户媒体。更新后真实 health/ready、匿名拒绝、CRUD、所有权隔离和 SDK 验收 PASS；费用复核确认同一函数与路由配置。

## 15. HTTP Gateway

现有域名为 `soulcompanion-dev-d0dzo6f2a24211-1501181209.ap-shanghai.app.tcloudbase.com`。`/` 已成功路由到已拥有的 `sc-v2-api`，类型 WEB_SCF，`enable=true`、`auth=false`、`pathTransmission=true`；原来的参数问题已修复。网关透传完整 `/api/v2` 路径，由应用处理私有 Bearer 认证。已核对总 QPS 100（官方最低值）与每客户端 IP QPS 5。没有创建新域名或覆盖其他服务；公开 Cloudflare 页面不切换到此入口。

## 16. CORS

应用按 `CLOUD_ALLOWED_ORIGINS` 精确允许 origin，本轮实际浏览器验收为 `http://127.0.0.1:18404`。仅允许 GET、POST、PATCH、DELETE，请求头为 Authorization 与 Content-Type；向允许的 origin 暴露响应 `X-Request-ID`。本地测试确认拒绝通配 origin 和未授权跨域请求；真实允许 origin 的 OPTIONS 返回 204，响应 origin 与请求精确一致，实际 SDK 浏览器业务链路也通过。未将公开 Cloudflare 域名加入生产切换。

## 17. Rate limit

应用每实例 60 秒窗口：健康入口 20 次、认证前入口 120 次、已认证用户 60 次；计数器容量有界，饱和时拒绝请求。网关已部署并核对总 QPS 100、单客户端 IP QPS 5；总 QPS 使用官方最低允许值，不以原计划的 20 冒充部署结果。请求体上限 16 KiB，上游超时 1.2 秒，总请求预算 2.6 秒。当前限流是开发保护，不是分布式生产配额系统。

## 18. H5 integration

H5 云账户、昵称、档案、会话、情绪和报告空状态已接入独立 cloud state。登录状态变化、401 和账户切换立即清理私有 UI，晚到响应因版本标识被丢弃。真实配置 H5 构建、241 个客户端测试和类型检查通过；官方 SDK 与真实 CloudBase 浏览器的 12 项检查全部通过，包括登录、me、档案创建/改名/选择/归档、退出和隐私边界。公开 Cloudflare 构建继续 `DEMO_ONLY`。

## 19. WeChat integration

小程序使用同一元数据 API 和独立微信登录适配器。AppID 固定为上述公开标识；构建输出为 `apps/client/dist-weapp`，源项目 `project.config.json` 指向该目录，构建生成配置指向 `./`。提交 `a6174fc` 的小程序 CI 构建及实际环境配置的最新本地构建均通过；本地构建包含 1268 个模块，用时 15.07 秒。DevTools/真机仍 NOT TESTED，步骤在 [MANUAL_ACTIONS.md](MANUAL_ACTIONS.md)。

## 20. Session metadata integration

云端只保存档案关联、来源平台、服务器 UTC 开始/结束时间和 active/ended 状态。真实验收通过会话创建、详情、列表和连续两次 End 的幂等结果；归档档案后禁止新建会话，归档操作重复执行也幂等。前端观察 Phase 03 本地媒体会话的实际状态；本地停止先完成，再异步结束元数据会话，不等待云端。后台、导航、错误、超时等结束路径都受此约束。元数据失败有明确提示，不持久化离线队列，也不延长设备占用。

## 21. Privacy guarantees

不上传原始视频、画面、截图、音频、PCM、设备 ID/label；不迁移 SQLite。日志仅记录请求 ID、路由模板、状态和耗时，错误不回显输入或上游敏感响应。客户端令牌不写入 localStorage、sessionStorage、IndexedDB、Taro 存储或验收产物；实际浏览器验收确认令牌/密码不在持久存储或 cookies 中，访客不请求私有数据、不自动获取设备、没有原始媒体请求。最终使用实际服务端 key 值扫描 219 个源码/文档文件与部署 ZIP，均未发现该值；临时私有部署配置剩余 0，忽略的 `.env` 未被 Git 跟踪。CI 无真实凭据，不自动部署。情绪与报告只读，真实空结果不会生成结论。边界说明见 [CLOUD_PRIVACY.md](CLOUD_PRIVACY.md)。

## 22. Tests

| 检查 | 结果 | 范围与限制 |
| --- | --- | --- |
| Python 全量 | 最终 PASS：513 | XML 确认 failures=0、errors=0、skipped=0；50.32 秒；覆盖本地基线、云 API 和工具，真实云端证据另列 |
| 最新云端定向测试 | PASS：90 个云 API、40 个传输测试 | 当前实现与传输兼容性检查；不作为真实 CRUD 证据 |
| 客户端单元测试 | 最新 PASS：241，13 个套件 | 云状态、SDK 适配器、账户隔离与 Phase 03 行为 |
| 客户端类型检查 | PASS | H5/小程序客户端源码 |
| 根 lint / Ruff | PASS | 已运行的源码与脚本检查 |
| H5 实际配置构建 | PASS | 实际配置构建成功；官方 SDK 真实浏览器验收另列 |
| Phase 03 E2E | 连续 3 次 PASS，每次 14 组 | 断网恢复、65 条历史及 DEMO 隐藏断言保留；只修复 Windows Proactor 测试清理，产品恢复逻辑未修改 |
| Phase 03 media | PASS：14 组 | 浏览器虚拟相机/音频；不是手机物理设备验证 |
| WeChat 构建 | PASS：CI 与实际环境配置本地构建 | 本地 1268 模块、15.07 秒，输出 `dist-weapp`；不冒充 DevTools/真机验收 |
| 客户端依赖审计策略 | PASS | 36 项继承风险无新增发现或豁免；不表示依赖没有漏洞 |

现有 Python 327+ 基线已包含在最终 513 项全量回归中。最新身份注册实现的代码、Python 与安全审查已通过；客户端类型、lint 和依赖审计策略已刷新通过。同一实际验收代码的远程 CI 九项全部成功。

## 23. Real cloud acceptance

**PASS：实际 CloudBase API 11 项检查与官方 SDK H5 浏览器 12 项检查全部为 true。** 本轮使用两个已有合成认证身份的安全复用模式，没有增加认证账户：先在拥有者检查后于私有进程输入中重置测试密码，再执行真实登录、业务与退出验收。凭据仅在内存与私有 stdin 中流转，不进入操作系统命令参数、日志、仓库或公开产物。默认计划模式不调用云端。

```text
python scripts/cloud_acceptance.py --apply --browser --reuse-fixtures
```

真实 API 检查包括 health/ready/匿名 401、两个官方认证主体、稳定且不同的应用用户及昵称持久化、档案创建/读取/改名/列表、两次归档幂等与禁止新会话、会话创建/详情/列表/两次 End 幂等、跨所有者与不存在资源统一 404、owner/UID/OpenID/媒体/操作符字段 422、直接客户端数据库请求 401/403、只读情绪和报告空状态、退出后旧 token 401。

真实浏览器检查包括官方 SDK 登录、me UI、档案创建/改名/选择/归档、退出后私有 UI 隐藏、旧 token 撤销、认证持久存储和 cookies 中无令牌/密码、访客私有请求为空、不自动获取设备、原始媒体请求为空。以上来自实际 HTTPS 环境，不使用 fake/mock 结果填充。

公开验收文件为本地忽略目录中的 `.test-artifacts/cloudbase-phase04/acceptance-public.json`：`status=pass`、`fixture_mode=reuse`，62 个 HTTP 请求，`rate_limit_retries=0`，最大请求延迟 2298 ms；API 11 项和 browser 12 项全部 true。验收保留两个明确标识的合成认证用户、应用身份、归档档案和结束会话元数据，不含真实个人或媒体数据。WeChat DevTools 和物理微信设备不在这份 H5/API 证据中。

## 24. GitHub Actions

实际验收代码提交 `0ee5b4e6ee064bf0daad844e2721a025c43e8e6c` 已推送；[GitHub Actions 37717747946](https://github.com/C1801SYQ/SoulCompanion-AI/actions/runs/37717747946) 的九个作业 **ALL SUCCESS**。这次运行验证同一实际验收代码，不以旧提交成功替代。计划模式及产物问题已修复；后续文档提交的独立 CI 与 SHA 由最终回复记录。

## 25. CloudBase resource usage

验收后最终费用审计 **PASS**：既有体验版、`EnableOverrun=false`、`IsAutoRenew=false`，同一函数和路由配置已复核（总 QPS 100、单 IP QPS 5）。当前账期为 2026-10-07 至 2026-11-07；官方 CLI 标签核对显示当前使用 **1.45/3000 套餐内资源点**，资源包用量 0 点，按量计费用量 0 点。资源点不是人民币或现金账单；计量记录可能延迟。

| 原始字段 | 官方 CLI 含义 | 最终返回值（资源点） |
| --- | --- | --- |
| `totalCredits` | 当前套餐额度 | 3000 |
| `totalCreditsValue` | 资源点用量 | 1.45 |
| `totalDeductValue` | 套餐内用量 | 1.45 |
| `totalPackageDeductValue` | 资源包用量 | 0 |
| `totalReportValue` | 按量计费用量 | 0 |

初始审计的 `0.19 / 3000` 属于初始快照，不能写成最终用量。现有资源为七集合、十三索引、一个小型 HTTP 云函数、现有默认域名的一个 `/` 路由；没有付费资源购买或升级流程。

## 26. Files changed

| 范围 | 主要文件 | 目的 |
| --- | --- | --- |
| 公开配置 | `.env.example`、`.gitignore` | 已有环境标识与秘密/产物隔离 |
| 架构与资源审计 | `docs/v2/04-cloud-resource-audit.md`、`DATABASE_DECISION.md`、`CLOUD_ARCHITECTURE.md` | 资源、费用和数据库选择依据 |
| 云 API | `cloud/api/app.py`、`cloud/api/soulcompanion_cloud/`、`cloud/api/requirements-cloud.txt` | 独立 V2 API、在线认证、所有权与安全边界 |
| 数据声明 | `cloud/schema/001_metadata.json` | 七集合、十三索引与版本 marker |
| 部署工具 | `scripts/cloud_admin.py`、`cloud_schema.py`、`cloud_package.py`、`cloud_deploy.py` | 安全审计、增量 schema、Linux 包与拥有者检查 |
| 真实验收 | `scripts/cloud_acceptance.py`、`cloud_browser.cjs` | 凭据不落盘的双身份 API/SDK 验收 |
| 客户端 | `apps/client/src/cloud/`、`src/state/CloudProvider.tsx`、`src/state/SessionProvider.tsx`、`src/components/CloudAccount.tsx` | 云账户/档案/会话接入与本地设备生命周期 |
| 小程序构建 | `apps/client/config/index.ts`、`project.config.json`、`package.json` | 微信公开配置与独立构建输出 |
| 自动检查 | `.github/workflows/checks.yml`、根 `package.json`、`tests/cloud/`、`tests/cloud_tools/`、客户端测试 | 无秘密 CI、回归与工具测试 |
| 审计策略 | `scripts/client_audit.cjs` | 锁文件指纹更新；继承风险策略不新增例外 |
| 交付文档 | `CLOUDBASE_DEPLOY.md`、`CLOUD_PRIVACY.md`、本报告、`MANUAL_ACTIONS.md` | 可复现步骤、边界和待办 |

最终修改清单应以 `git diff 2626fa387be793cbc27157f273494357b47ef8bc...04-cloud-backend --name-only` 为准，忽略的 `.env` 与产物不进入提交。

## 27. Commits

以下 Phase 04 逻辑代码提交已推送至 `origin/04-cloud-backend`。最终文档提交单独交付，其 SHA 由最终回复记录，避免报告把自身提交 SHA 写入自身：

| 提交 | 内容 |
| --- | --- |
| `7c07ef2` | `chore: establish CloudBase Phase04 architecture` |
| `48cf782` | `feat: add verified CloudBase auth and owned metadata API` |
| `f72044c` | `deploy: add safe CloudBase schema and HTTP function tooling` |
| `6322776` | `feat: integrate cloud accounts profiles and session metadata` |
| `ae3c11d` | `fix: use managed upload for CloudBase function packages` |
| `efbebac` | `test: add private real cloud acceptance and Phase04 CI` |
| `8192673` | `fix: keep cloud acceptance plans dependency free in CI` |
| `a6174fc` | `fix: deploy owned routes on the existing CloudBase default domain` |
| `5ba424a` | `fix: register CloudBase identities with verified atomic inserts` |
| `ab6e949` | `test: stabilize Windows acceptance server shutdown` |
| `0ee5b4e` | `test: reuse existing CloudBase acceptance fixtures safely` |

## 28. Remote branch SHA

通过真实验收、最终本地测试与九项远程 CI 的代码 SHA 为 `0ee5b4e6ee064bf0daad844e2721a025c43e8e6c`，已推送至 `origin/04-cloud-backend`。随后文档提交的 SHA 和最终远程分支 HEAD 由最终回复及独立提交记录报告，避免自身提交 SHA 的循环引用。

## 29. Manual actions still required

微信开发者工具和手机微信的实际权限、合法 `request` 域名、微信登录与设备测试仍需有 AppID 权限的操作者执行，详见 [MANUAL_ACTIONS.md](MANUAL_ACTIONS.md)。真实 API/H5 自动验收、最终本地测试、代码远程 CI 和费用复核均已完成。服务端 key 有效期 30 天，到期前需以官方托管配置轮换，不能向聊天或仓库导出。

## 30. Known limitations

DevTools 和物理手机未测试。体验版有期限和配额，服务端 key 为环境管理员权限，应用限流是每实例。情绪与报告为空且只读，未实现媒体上传或 AI 推理。客户端依赖审计仍有继承的 36 项发现（1 critical、29 high、6 moderate），审计策略 PASS，锁文件更新没有引入新增风险或新增豁免；不能声称依赖审计零漏洞。合成测试身份和归档/结束元数据保留，原始凭据不保存或发布。Phase 03 本地 SQLite、设备和公开 DEMO 页面保持既定边界。

## 31. Phase05 prerequisites

真实云端 API/H5 验收、最终本地测试、九作业 CI 和费用复核已完成。微信人工验收及下一阶段要求仍由所有者确认。Phase 05 必须有新的所有者指令；本轮停在 Phase 04，不创建 `05-realtime-emotion-pipeline`，不启动媒体上传、推理或生产切换。

## CLOUD_ENDPOINTS

以下是现有默认域名上的公开开发 API 地址。**网关、真实 health/ready、元数据 API 与官方 SDK H5 验收均已通过；公开 Cloudflare 页面保持 DEMO_ONLY。**

| 字段 | 值 | 当前状态 |
| --- | --- | --- |
| API base URL | `https://soulcompanion-dev-d0dzo6f2a24211-1501181209.ap-shanghai.app.tcloudbase.com/api/v2` | PASS：真实 API 11 项、H5 浏览器 12 项 |
| Health URL | `https://soulcompanion-dev-d0dzo6f2a24211-1501181209.ap-shanghai.app.tcloudbase.com/api/v2/healthz` | PASS：实际 200/ok |
| Ready URL | `https://soulcompanion-dev-d0dzo6f2a24211-1501181209.ap-shanghai.app.tcloudbase.com/api/v2/readyz` | PASS：实际 200/healthy |
| Gateway route | `/` → `sc-v2-api`，保留完整 `/api/v2` 路径 | PASS：WEB_SCF，enable=true、auth=false、pathTransmission=true |
| Function name | `sc-v2-api` | 存在，拥有者与配置核对 PASS |
| Database type | CloudBase 文档数据库（现有实例） | schema、ACL、索引核对 PASS |

客户端 `PUBLIC_API_BASE_URL` 使用上述 API 域名的 HTTPS origin，**不带 `/api/v2`**；客户端请求自行附加完整 V2 路径。

## REAL EVIDENCE TABLE

实际 CloudBase API/H5 结果来自 `acceptance-public.json` 的 11+12 项真实检查，数据库与资源配置来自实际控制面复核。标为 MANUAL/NOT TESTED 的微信项目明确缺少实际设备证据，不用模拟或 H5 结果替代。

| Capability | Result | Evidence |
| --- | --- | --- |
| CloudBase environment | PASS | 实际 CLI 审计确认用户指定的已有环境 NORMAL、上海；未创建第二环境 |
| FREE plan preserved | PASS | 验收后实际 `baas_trial`、超额付费关闭、自动续费关闭；最终用量字段见第 25 节，无购买或升级操作 |
| HTTP FastAPI | PASS（health/ready/匿名边界） | 实际默认域名路由至 HTTP 函数；health 200/ok、ready 200/healthy、匿名 me 401 |
| Database | PASS | 实际七 ADMINONLY 集合、十三索引、marker version 1；真实业务写读通过，用户直连 401/403 |
| Web Auth | PASS | 两个现有合成身份 REST 登录/introspection、官方 SDK H5 登录/退出、旧 token 401 全部通过 |
| WeChat Auth | MANUAL | 实际提供方/AppID 核对与适配器测试通过；开发者工具/真机登录未测试 |
| Profile CRUD | PASS | 真实创建/读取/改名/列表/两次归档；浏览器创建/改名/选择/归档也通过 |
| Session CRUD | PASS | 真实元数据创建/详情/列表/两次 End 幂等；归档档案不能开始新会话 |
| IDOR protection | PASS | 真实双账户全部相关动作/过滤路径中跨所有者与不存在资源统一 404；直连数据库 401/403 |
| H5 | PASS | 实际配置构建、241 单元测试、类型检查和官方 SDK 真实浏览器 12 项全部通过 |
| WeChat DevTools | NOT TESTED | 没有实际开发者工具运行证据；见人工步骤 |
| Physical WeChat device | NOT TESTED | 没有实际手机微信运行证据；浏览器虚拟设备不是手机证据 |
| Media upload | NOT IMPLEMENTED BY DESIGN | 本轮只处理元数据；需后续阶段另行授权 |
| AI inference | NOT IMPLEMENTED BY DESIGN | 本轮情绪与报告只读空状态；未开始 Phase 05 |
