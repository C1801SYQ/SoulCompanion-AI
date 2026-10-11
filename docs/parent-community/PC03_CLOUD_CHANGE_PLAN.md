# PC03 云变更计划与实施准入

日期：2026-10-11。状态：**AUTHORIZED**。用户已明确回复“授权按方案执行”，独立批准下述 PC03 限定增量、函数更新、合成验收与异常回滚；不是延用 PC02 授权。实际执行结果及首次网络中断的恢复记录见 [交付报告](PC03_DELIVERY_REPORT.md)。未在此扩大资源、费用、身份配置、数据清理或正式运营人员授权范围。

## 已核验目标与费用边界

| 项目 | 精确目标及证据 |
|---|---|
| 环境 | `soulcompanion-dev-d0dzo6f2a24211`；DescribeEnvInfo 实际 EnvId 匹配、Status=NORMAL |
| 地域 | 实际 EnvBaseInfo.Region=`ap-shanghai`，不以 CLI 参数或环境昵称充当核验证据 |
| 数据库 | 唯一 RUNNING 数据库 `tnt-28wj48qn2`；无迁移、回填或替代数据库 |
| 套餐 | `baas_trial`，超额付费 false、自动续费 false；2026-10-11 只读重新核验 |
| 函数 | 已有且归属已核实的 `sc-v2-api`，HTTP / Python3.11 / 256 MB / 3 秒，Active |
| HTTP 网关 | 沿用已有 `/` 路由；本方案网关调整 NONE |
| 微信 | 本地 project.config.json AppID=`wx11a055ed4dc69764`；现有 WX_CLOUDBASE_MICRO_APP / OPENID 提供方已启用。此次只读响应未独立证明提供方绑定的具体 AppID，微信手机登录仍 NOT TESTED |

每次真实写入前重新核验上述实际环境、费用、旧 schema、函数归属及完整配置。集合/角色工具不信任旧 preflight 中由常量填入的地域；部署工具同样读取实际 DescribeEnvInfo。目标、套餐、费用开关或配置不符立即停止。微信提供方/AppID 不在本方案修改范围内。

体验环境有期限与额度，索引存储、文档读写、配额计数、函数请求和临时包上传会消耗现有额度，不能保证永久免费或预估为零费用。不开超额付费或自动续费、不购买或升级套餐、不新增容器/GPU/付费服务。若额度不足、必须升级或无法确认费用，停止并向用户报告。

## 允许的增量

使用 [003 manifest](../../cloud/schema/003_parent_community.json)，canonical SHA-256 为 `af5041450e947fc043e29d529bb02e83ab71115ad19c0367ea2a3ab6a64aed34`。新增 5 个 ADMINONLY 集合、14 个项目索引：

| 集合 | 索引数 | 用途 |
|---|---:|---|
| sc_v2_community_content | 7 | 帖子/一级评论、版本状态与同文档审核审计 |
| sc_v2_community_relations | 3 | 每用户唯一点赞/私有收藏关系 |
| sc_v2_community_content_reports | 2 | 每举报人/目标/正文版本唯一举报及处理历史 |
| sc_v2_community_role_bindings | 1 | 可信运营角色及管理审计 |
| sc_v2_community_write_quotas | 1 | 用户/动作/UTC 日的分布式写入尝试配额 |

索引字段及方向逐项见 [架构](PC03_ARCHITECTURE.md#21-索引清单)。原生系统索引另计。DescribeTable 实际没有独立 build-state 字段，工具核对回读 Name/Keys/Unique/Sparse/PartialFilterExpression；不把不存在的字段当作 ready 证据。

复用 PC02 家长资料，不创建第二套身份。001/002 文件、checksum、marker、原有 8 个集合、已有索引及用户/儿童/会话数据均保留；只读检查依赖 ACL、指纹与定义。新增 marker `pc03-parent-community`，owner `SoulCompanion-AI/pc03`，唯一 reservation_id，先 version0；所有新资源及旧依赖回读完整后，以绑定 reservation 的 CAS 晋升 version3。部分失败保持 version0；后续同指纹、同归属重跑补齐，归属不明拒绝。完成后的重跑只读核验。

只更新已有 `sc-v2-api` 的代码，不调整函数配置、身份提供方、网关、费用或权限。Linux CPython3.11 包只包含独立 Cloud API 与既有锁定依赖，无推理/硬件运行时、凭据或附件。实际候选包 SHA、文件数及验证结果在 [交付报告](PC03_DELIVERY_REPORT.md)登记。

## 执行顺序与双重门槛

1. 用户明确授权本方案；历史授权、默认 plan 或读取该文件都不是许可。
2. 重做只读目标/额度/函数完整配置/旧包与 schema 检查；下载并保留当前函数包，不打印环境变量或临时上传凭据。
3. `cloud_community_schema.py --apply --cloud-write-authorized`：只进行上列增量。任何未确认结果停止，不盲目重放 marker 晋升。
4. `cloud_community_deploy.py --apply --cloud-write-authorized`：校验候选与当前源一致、PC02 回滚包固定 SHA、当前代码精确归属；冻结候选包并保留旧包。使用已审查 SCF 管理的临时 COS 上传，再核验远端每个 ZIP 成员、完整函数配置及健康状态。代码验证不等于业务验收。
5. 复用恰好两个已归属的 PC02 合成测试账户 A/B，不创建真实家长或儿童账号。仅在内存中生成测试口令/令牌，使用受保护既有账户工具登录；允许重置这两个合成账户口令、撤销本轮令牌。输出只包括脱敏检查名、计数、状态与耗时。
6. 通过已验证 token 的 `/api/v2/me` 获取应用 UUID；复核服务端现有 active 用户记录，以 B 为短期合成运营主体。受保护 `cloud_community_roles.py --apply --cloud-write-authorized` 写入带理由、动作键和完整审计的 grant；不使用原始 OpenID/UID，不新增自助授权 API。A 保持普通用户。
7. 执行下述有界真实验收。结束或失败均优先审计 revoke B 角色、撤回本轮合成内容、撤销本轮令牌；清理失败单独报告，不能伪造通过。

上述合成业务及收尾由 [cloud_community_acceptance.py](../../scripts/cloud_community_acceptance.py) 执行，默认 plan，真实执行同样要求 `--apply --cloud-write-authorized`。工具在重置合成口令或授予角色前，必须先核验真实目标/费用及匿名社区接口；部署包成员和完整配置仍由独立部署工具验证。旧家庭与官方 H5 SDK 回归串行复用同两账户，避免同时重置口令。角色历史、配额和软撤回内容按方案保留，失败记录不会被后续 PASS 覆盖。

以上脚本默认 plan 不加载密钥、不连接云；apply 与授权确认参数同时存在才允许写入。命令行不放密码、SecretKey、AppSecret、Token、内部用户清单；不提交私有 `.test-artifacts` 或部署包。

## 真实验收与数据收尾

全部文本显式使用“PC03 合成验收”，无真实儿童姓名、学校、地址、照片或病史。记录本轮资源 ID 在私有内存/忽略文件中，只操作本轮确定性键对应的数据，不扫库清空。

- 匿名/无效 token 不能写入；缺角色的 A 运营请求 403；缺失/隐藏/他人私有内容按契约 404。
- A 建立待审帖，匿名列表/详情不公开，A 能读取，其他用户不能私读；B 审核当前版本后公开，公共 DTO 没有内部主体及家庭字段。
- A 编辑后重新 pending；旧 revision 审核 409；B 审核新版本，年龄+话题 AND、分页排序及游标实际读回正确。
- 一级评论先待审再审核，父帖隐藏后评论列表及直接 URL 不公开。
- A 点赞/收藏重复确认不产生重复关系，A 私有收藏可见、B 不能读取 A 的收藏关系；取消只变 inactive。
- 举报重复收敛，举报人不对目标作者公开，B 处理举报与隐藏目标分别确认，不伪称跨文档事务。
- 并发/重复请求以有界少量操作验证 CAS 和幂等；存储响应未知时记 INDETERMINATE，保持相同动作键恢复，不批量撞限流或承诺负载测试。
- A 撤回自己的帖/评论（按实际当前 revision）；角色 revoke 读回、重试运营访问拒绝；旧家庭 API及官方 H5 SDK 做回归，不读取真实家庭数据。

保留新 schema、软撤回内容、必要审核/角色/举报历史和已消耗配额；不物理删除记录/索引，不销毁账户、不回填旧数据。点赞/收藏在父帖仍公开时先取消；后续隐藏的残留关系不会公开。生产运营主体的正式 grant 不包含在合成验收授权里，需用户指定并独立核对。

## 回滚与停用

原 PC02 回滚包 SHA-256：`81726829c4384d2474509cf382a5b38abd26c0ee0a265a32bcdf0df00956b6b6`，保存在忽略的 `.test-artifacts/cloudbase-pc02/sc-v2-api.zip`。不覆盖 Phase04 或 PC02 包。部署前在私有 `approved-packages/<sha>.zip` 冻结经源验证的 PC03 ZIP，最多 32 个快照；精确成员集和 bootstrap 模式核验后才作为归属证据。

异常时停止新的社区操作，审计撤销合成运营角色和令牌；`cloud_community_deploy.py --apply --cloud-write-authorized --rollback` 恢复固定 PC02 代码，回读每个成员及配置。回滚不依赖当前源或前向候选仍存在；当前代码必须属于已核实 PC02 或冻结 PC03，未知归属拒绝覆盖。恢复 PC02 后社区路由不可用，旧家庭 API继续存在。

回滚不修改 marker、不删表或数据。若需要把 PC03 marker 降回 version0、删除任何数据或改变资源，应另行生成受审查方案与授权，不由部署脚本隐式执行。本方案覆盖异常时恢复原函数代码及合成验收收尾，不允许购买资源、重写 001/002 或自动进入 PC04。
