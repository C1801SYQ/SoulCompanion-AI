# PC03 社区 API 契约

状态：本地实施契约，PC03 真实云操作未授权；PC01 前端仍为示例模式。本契约的真实社区接入和运营界面由 PC04 实现。

基线与存储策略见 [架构](PC03_ARCHITECTURE.md)。基础路径沿用 `/api/v2`。服务端复用 CloudBase 在线身份验证，没有新的身份系统或公开角色授权接口。

## 1. 通用规则

- 受保护接口使用既有 `Authorization: Bearer <access_token>`；匿名公共读取无需登录。
- 请求为 UTF-8 JSON，未知字段拒绝，最大请求体仍为 16384 字节。客户端不能提交 owner、principal、作者 ID、status、角色、审核者或发布时间。
- 所有资源 ID 为规范 UUID，时间为服务端 UTC。下文占位符是语法说明，不是凭据。
- `age_band`：`0-2 / 3-5 / 6-8 / 9-12 / 13-15 / 16-18`。
- `topic`：`parent-child / emotional-support / daily-habits / school-transition / learning-peers / adolescence / parent-growth`。
- 路径 `target_type`：`posts / comments`；举报 JSON 的 `target_type` 与内部内容 kind 为 `post / comment`，两者由服务端明确映射。
- 标签是内容适用范围；社区浏览不要求儿童档案或精确生日。写入标签由投稿者主动选择，绝不从私有儿童档案自动复制。
- 纯文本 NFC 校验；标题 1～80、正文 1～2000、评论 1～1000、举报说明 0～500、审核理由 1～200 个 Unicode 字符；理由最多 800 UTF-8 字节。拒绝无效 UTF-8、控制/双向控制、HTML 标签及危险嵌入；正文允许 LF。
- `Idempotency-Key` 为安全 ASCII 1～64 字符，创建帖子/评论、举报与审核动作必填；同用户、同动作/目标、同输入重试收敛，同键不同输入返回 409。跨域允许该受审查请求头；重复或歧义敏感头拒绝。
- 所有响应沿用 `Cache-Control: no-store`、`X-Request-ID` 及统一错误。

错误格式：

```json
{"error":{"code":"not_found","message":"Record not found.","request_id":"<server-request-uuid>"}}
```

| HTTP | 语义 |
|---|---|
| 401 | 缺失、无效或已撤销身份 |
| 403 | 已认证但无可信运营角色，或既有 CORS 拒绝 |
| 404 | 资源不存在、公共不可见、外人的私有内容；不得区分泄露存在性 |
| 409 | 旧版本、非法状态、幂等输入冲突、审计容量不足，或需先设置本人家长昵称 |
| 413 | 请求总字节超限 |
| 422 | 非法字段、标签、长度、游标或文本 |
| 429 | 既有限流或分布式用户动作配额耗尽 |
| 503 | schema 不完整、存储不可用、竞争预算耗尽或写入确认不确定 |

错误不包含上游响应、token、内部 UID、儿童档案、查询语句或数据库标识。503 不承诺数据库完全没改变；重试必须沿用原幂等键，不能显示虚假成功。

## 2. 返回对象与分页

公开帖子：

```json
{
  "id":"<post-uuid>",
  "title":"合成示例：晚饭后聊聊今天",
  "body":"这是一条接口说明用的虚构家长分享。",
  "age_band":"6-8",
  "topic":"parent-child",
  "author":{"id":"<pc02-public-parent-uuid>","nickname":"合成家长小禾"},
  "created_at":"2026-10-10T00:00:00.000000Z",
  "updated_at":"2026-10-10T00:00:00.000000Z",
  "published_at":"2026-10-10T00:00:01.000000Z"
}
```

示例仅解释结构，不能提交到真实云伪装业务记录。公开评论输出 `id/post_id/body/author/created_at/updated_at/published_at`。本人内容在安全正文对象上增加 `status/content_revision`；运营详情增加受保护的审核历史及当前版本。公开响应绝不包含 owner、原始 UID/OpenID、运营 actor、幂等 hash、举报人、私有家庭字段。

作者为 PC02 公开资料快照，创建及正文修改时刷新，家长昵称独立修改不自动重写旧内容。作者没有填写公开昵称不影响阅读，投稿提示设置家长昵称；不要求创建儿童档案。

列表响应：

```json
{"items":[],"limit":20,"next_cursor":null}
```

查询 `limit` 默认 20，范围 1～50；`cursor` 是不透明、严格验证的排序边界，不使用 offset。公共按 `(published_at,id)` 降序，本人内容按 `(created_at,id)`，运营队列按 `(updated_at,id)`。游标绑定列表类型及筛选条件，切换筛选须重新从第一页开始；游标不是身份凭据或跨请求事务快照。列表不提供假总数、推荐排序、假热度或逐帖 count。

## 3. 公共读取

| 方法与路径 | 参数 / 结果 |
|---|---|
| `GET /community/posts` | 可选 age_band、topic、limit、cursor；仅 published 且有匹配人工审核证据的帖子 |
| `GET /community/posts/{post_id}` | 仅当前公开帖子；隐藏、拒绝、待审、撤回均 404 |
| `GET /community/posts/{post_id}/comments` | limit、cursor；父帖必须当前公开，仅已审核 published 一级评论 |
| `GET /community/comments/{comment_id}` | 评论与父帖都必须当前公开；不存在或隐藏均 404 |

年龄及话题同时指定时使用 AND。省略条件表示全部，不把 `all` 当作储存标签。相同发布时间使用唯一 ID 第二排序字段，测试必须证明静态数据分页没有重复或遗漏。

公共路由没有私有子女、情绪报告、会话或媒体读取；可选身份也不能扩大公共可见范围。父帖隐藏后，评论直接 URL 和互动入口也不得绕过父帖检查。

## 4. 作者写入与私有内容

| 方法与路径 | 身份 / 输入 | 结果 |
|---|---|---|
| `POST /community/posts` | 登录、本人家长昵称、Idempotency-Key；title、body、age_band、topic | 新内容 pending，首次 revision=1；201，确认重试可 200 |
| `PATCH /community/posts/{post_id}` | 本人；expected_revision、title、body、age_band、topic | 全文替换输入，非 deleted 才允许；pending，revision+1，旧公开版本立即撤下 |
| `DELETE /community/posts/{post_id}` | 本人；expected_revision | 软撤回 deleted；确认后 204，重复本人已撤回可 204 |
| `GET /me/community/posts` | 登录；limit、cursor | 仅本人各状态帖子，owner 由身份推导 |
| `GET /me/community/comments` | 登录；limit、cursor | 仅本人各状态评论 |
| `GET /me/community/{target_type}/{target_id}` | 登录，本人 | 读取本人待审、拒绝、隐藏、已撤回内容；外人统一 404 |
| `POST /community/posts/{post_id}/comments` | 登录、本人家长昵称、Idempotency-Key；body | 父帖公开才允许；一级评论 pending，201/200 |
| `DELETE /community/comments/{comment_id}` | 登录、本人；expected_revision | 软撤回，204；不改变其他家长评论 |

`expected_revision` 为正整数，与当前正文版本匹配。DELETE 的版本参数采用受验证 query，避免小程序/代理丢弃 DELETE body；PATCH 的参数放 JSON。禁止缺失版本时盲目覆盖。修改 published、rejected 或 hidden 正文都重新待审；不能只换正文而保留旧审核许可。撤回保留必要审计，不能物理删除他人数据。

投稿示意：

```http
POST /api/v2/community/posts
Authorization: Bearer <access_token>
Content-Type: application/json
Idempotency-Key: pc03-synthetic-example-01

{"title":"合成分享","body":"虚构的亲子沟通体验。","age_band":"6-8","topic":"parent-child"}
```

首次输入规范化 hash 与确定性资源键保存后，编辑内容不会使原创建幂等键重新创建另一个帖子。同键同初始输入重试返回现有本人内容的**当前**状态，不能把历史 pending 或 published 回执当作当前状态。

## 5. 点赞与私有收藏

| 方法与路径 | 语义 |
|---|---|
| `PUT /community/posts/{post_id}/like` | 本人设置 liked=true；空 JSON/无 body 依契约验证，禁止 owner 输入 |
| `DELETE /community/posts/{post_id}/like` | 本人设置 liked=false |
| `PUT /community/posts/{post_id}/bookmark` | 本人设置 bookmarked=true |
| `DELETE /community/posts/{post_id}/bookmark` | 本人设置 bookmarked=false |
| `GET /me/community/bookmarks` | 私有收藏页；limit、cursor；只返回当前仍公开的帖子 |

确认响应可输出 `post_id/kind/active`，不得输出内部关系 owner。PUT/DELETE 都幂等，同用户与帖子一条关系；CAS 冲突不能假装相反操作已经执行。父帖当前不可见统一 404，取消不会暴露已隐藏内容。读取隐藏的残留收藏时过滤该条，但游标继续沿最后扫描关系推进；允许空页，不无限补齐。匿名收藏写入 401，其他用户无权获取收藏关系。

公共列表不显示伪造计数；若详情返回点赞或公开评论数，必须来自真实 indexed count 并在父帖再次确认公开后返回。收藏数量与收藏人不公开。

## 6. 举报

`POST /community/content-reports`：登录、Idempotency-Key，字段：

```json
{"target_type":"post","target_id":"<post-uuid>","reason":"privacy","detail":"合成说明：疑似包含可定位信息。"}
```

原因枚举固定为 `privacy / harassment / unsafe / spam / other`；`other` 必须有非空说明。目标必须是当前公开帖子或父帖也公开的评论。target_revision 由服务端读取，客户端不能提交；不存在或不可见统一 404。

首次为 open；返回仅本人可见的安全回执：`id/target_type/target_id/target_revision/reason/detail/status/created_at/handled_at`。同一举报人对同一目标正文版本仅一条记录，重复相同输入幂等，不同输入 409；不允许伪造 status、handled_at、审核结论或举报人。新正文版本公开后可再次举报。

举报键的范围包含目标及服务端读取的正文版本，并非所有目标共享一个全局键。即使使用不同键，相同用户/目标/版本/输入也收敛为同一举报；相同键针对不同目标或后来公开的新版本可以产生独立举报。运营动作键则绑定 actor、目标及动作，不是对任意资源的通用发布许可。

举报记录不能通过公共帖子、作者自己的内容接口或普通运营以外的用户查询。内容举报与私有情绪 `CloudReport` 是两个领域，不复用旧报告集合。

## 7. 运营与审核

运营请求先通过既有在线认证，再读取可信服务端 RoleBinding。没有角色的已登录用户返回 403；不依赖前端按钮是否存在。角色不存在、被撤销或角色字段异常不能放行。HTTP 不提供授予角色、自助管理员或编辑角色路由。

| 方法与路径 | 输入 / 结果 |
|---|---|
| `GET /ops/moderation` | status 默认 pending，可选合法审核状态，limit、cursor；混合帖子/评论的有界队列 |
| `GET /ops/moderation/{target_type}/{target_id}` | 当前受保护内容及版本、审核历史；404 不存在 |
| `POST /ops/moderation/{target_type}/{target_id}/approve` | Idempotency-Key；expected_revision、reason；仅 pending |
| `POST /ops/moderation/{target_type}/{target_id}/reject` | 同上；仅 pending |
| `POST /ops/moderation/{target_type}/{target_id}/hide` | 同上；pending/published/rejected 可隐藏，重复已隐藏的同动作幂等 |
| `GET /ops/content-reports` | status 默认 open，可选 open/resolved/dismissed，limit、cursor |
| `POST /ops/content-reports/{report_id}/resolve` | Idempotency-Key；expected_revision、decision=resolved/dismissed、reason |

运营不得接受客户端 actor、role、owner 或任意目的状态。内容 `expected_revision` 绑定正文；report 的 `expected_revision` 绑定独立处理版本。运营内部 CAS 还绑定当前 row_version/status，避免同正文的并发状态操作互相覆盖。

审批与审核历史同一次原子条件更新；评论审批需再次检查父帖公开。举报 resolve 仅说明举报已处理/驳回，**不会暗中触发跨文档隐藏**；需要隐藏目标时先调用独立 hide，分别核查结果，避免声称没有事务保障的组合操作是原子的。

确认动作返回安全当前内容/举报结果及可追溯动作回执；回执的 `action_applied` 和历史 revision 表示动作曾成功应用，另行输出当前 status/revision。重复同键重试先核查已有不可变审核条目，不能把旧通过记录作用到后来修改的正文。历史动作已经执行、当前内容后来被编辑或隐藏时，响应必须同时如实表达当前状态。客户端只能提交动作键，不能提交 `action_id` 或 actor 字段。

人工审核应检查儿童姓名、学校、住址、可识别照片描述、联系方式、骚扰与未经支持的诊断/治疗断言。只有 DTO 隔离不等于正文隐私脱敏；本阶段没有 AI 自动审核或自动医疗建议。

## 8. 配额、容量与失联恢复

每天 UTC 每位用户配额：帖子 10、评论 100、举报 20、关系改变 200、运营改变 200。配额采用分布式单记录 CAS，最多三次竞争重试；失败可能保守消耗次数。重复已确认请求不重复消费。不得承诺实例内存限流能代替该配额或阻止多账号滥用。

作者撤回不消耗投稿/评论配额，配额耗尽也能撤回自己的已公开内容；认证、所有权、版本、审计容量和既有限流仍然生效。角色 grant 要求已有 active 应用用户；安全 revoke 核对可信旧绑定，即使该用户后来被禁用或已不存在，仍可撤销并保留审计。

正文/审核操作使用有界历史：普通编辑、通过、拒绝完成后最多 30 项；隐藏可到 31，撤回可到 32。普通请求不能利用最后保留位继续发布。满额必须拒绝，不静默删审计。角色管理只在受保护 CLI，授权/撤销也保留审计容量。

写入过程中断、异常确认、数据库失联时返回标准脱敏错误。事务未获验证，不能通过“先发布，后插入日志”补偿。合法原子审核可能已提交而响应丢失，交付结果为 INDETERMINATE；重试保留动作键、读取当前受保护版本与历史动作，不能重新批准新的正文，也不能断言所有 503 完全没写入。

全局 API 超时 2.6 秒仍生效；没有外部 AI 同步调用、不提高云函数资源或付费预算。真实 PC03 schema/API 部署与验收须待独立授权，Fake 测试、旧 PC02 REAL CLOUD PASS 或 weapp 构建不能替代本阶段真实验收。
