# PC03_BASELINE_AUDIT

审计日期：2026-10-10。本文记录开始实施时的历史基线，云状态描述不充当当前状态；授权后的实施、修复与真实验收见 [PC03 交付报告](PC03_DELIVERY_REPORT.md)。范围：PC03 社区后端；客户端真实社区接入及运营页面属于 PC04。

## Git 与历史成果

执行了 status、branch、fetch、分支列表、最近 15 个提交、HEAD/远端解析、diff 和 cached diff。开始时工作区干净，本地及 `origin/pc-02-family-identity` 均为 `39bf161b3a584fe545ae20553f3fc6087297d38d`。该提交是最新 PC02 文档回执，软件父提交为 `6c41d4b0854cc08f41edbdf66d8429ac93f82f6a`。附件引用的 `36fe207` 是更早的回执，未据此回退。

本地及远端没有 PC03 分支，因此从已核实最新 PC02 创建 `pc-03-community-backend`。不修改 master、重写历史、删除报告或合并历史 Phase05。

## 后端与依赖

- 独立入口：`cloud/api/app.py` 与 `soulcompanion_cloud/app.py:create_app`，使用既有 FastAPI、Pydantic、httpx，无模型推理或硬件运行时导入。
- `create_app` 可注入 repository/verifier；生产共享受控 `AsyncClient`，禁止重定向和环境代理。测试使用合成主体和 Fake，不把 Fake 当生产数据库。
- 认证闭包严格解析 Bearer，再请求官方 CloudBase introspection、核对环境和主体、映射应用用户、检查用户限流。社区写入复用该依赖，不新建 JWT 或身份系统。
- 当前只有 healthz/readyz 是公共路由，其余家庭资料均需验证身份。新公共社区 GET 不调用身份映射或读取儿童、会话、情绪和私有报告。
- 统一错误为 `{error:{code,message,request_id}}`；验证错误不回显输入，日志仅记录注册路由模板与状态/耗时。
- 请求体默认 16 KiB，上游超时 1.2 秒，整请求预算 2.6 秒；现有内存限流是实例内保护，不能冒充分布式配额。

## 已有数据库与公开身份

| schema | 成果与保护边界 |
| --- | --- |
| `001_metadata.json` | Phase04 7 个 ADMINONLY 集合、13 个项目索引，账户/身份映射/私有儿童/会话/只读情绪及报告/schema marker |
| `002_family_identity.json` | 1 个独立 ADMINONLY 家长资料集合、唯一 owner 索引；可空儿童年龄字段，无回填 |
| 家长资料 | 对外只投影独立 UUID、主动昵称及时间；内部 owner 不对外投影，不能用私有 User.id/display_name 或孩子昵称代替作者 |

001 canonical checksum：`7e23a3c17a1551df1d5a3c7c7c9deb8903f9ea7430fbd38e4fa482e85159fa49`。

002 canonical checksum：`6462a3674be5331748cf5715d81b78dd7c687a6ee326e7a0d95b253c29751324`。

两原 manifest 和 marker 均保持不变。PC03 使用独立 003 manifest 和 marker，不把 ContentReport 与私有 CloudReport 混用。

## 数据适配器能力与限制

现有 CloudBase HTTP 适配器支持确定性文档插入、条件 PATCH、严格整数 matched/updated 校验、有界查询与多字段排序。409/500 插入冲突只有在回读 canonical 文档完全匹配后才可确认，不把错误当成功。

本地官方 SDK 与现有 REST 请求形状相符；新社区查询/CAS 将通过 Fake HTTP 适配测试。未执行真实社区写入，不能据已有家庭 API 验收宣称所有新查询及并发行为 REAL CLOUD PASS。不依赖未经真实验证的跨文档事务。

## 云函数与部署边界

PC02 报告记录的目标为 `soulcompanion-dev-d0dzo6f2a24211` / 上海，既有 HTTP 函数 `sc-v2-api`：Python3.11、256 MB、3 秒。体验版有期限与配额，并非永久免费；旧授权时超额付费与自动续费关闭。

本轮真实云实施前必须重新只读核查环境、AppID、数据库、函数、权限与费用，生成具体变更计划并取得 PC03 独立授权。PC02 授权不延伸到 PC03。没有授权时只执行本地 plan/Fake 测试，不创建集合、角色或部署函数。

2026-10-11 授权前补充只读核验：实际 DescribeEnvInfo 返回上述精确 EnvId、Region=ap-shanghai、Status=NORMAL，唯一 RUNNING 数据库为 `tnt-28wj48qn2`；DescribeBillingInfo 核验体验套餐、超额付费 false、自动续费 false。既有函数仍 Active / Python3.11 / 256MB / 3秒，所属函数与原网关可核实。微信提供方 WX_CLOUDBASE_MICRO_APP / OPENID 为启用，本地 AppID 为 `wx11a055ed4dc69764`；此次安全摘要未独立证明提供方内绑定的具体 AppID，不将旧报告或本地配置当作新的真机证据。截至该次授权前核验，PC03 未执行真实写入；随后独立授权的实际实施见交付报告。

## 测试结构与历史证据

- `tests/cloud/test_api.py`：合成 token、两用户与可注入内存存储；身份、所有权及既有 API 回归。
- `test_family_identity.py`：年龄/家长公开资料、marker gate 与 HTTP Fake。
- `test_transport.py`：官方 HTTP 请求形状、插入确认与条件更新；社区查询操作符需新增专项 Fake 验证，不能假设旧 Fake 已覆盖。
- `tests/cloud_tools`：schema、打包、受控部署与验收工具；保留所有旧断言。
- PC02 历史验收：429 项后端、404 项客户端，真实 API 15 项和额外 API11/H5 SDK12项通过，软件及文档提交 CI9/9。此处是基线证据，新 PC03 需重新执行。
- 客户端现有 typecheck、Vitest、H5/weapp/WXSS、Playwright 社区/V1/媒体和依赖审计；全部作为 PC03 回归。微信手机登录仍待用户验收，不继承为 PC03 真机 PASS。

## 保留的客户端边界

PC01 四主入口、六年龄段、七话题及明确示例内容保持原状，不将原型切换为真实投稿。终端摄像头/麦克风仍由用户主动开启，离开陪伴页面释放设备；公开页面不加载家庭私有数据。CloudBase 用户切换、退出清理和现有媒体适配器不重做。

架构与契约见 [PC03_ARCHITECTURE](PC03_ARCHITECTURE.md) 和 [PC03_API_CONTRACT](PC03_API_CONTRACT.md)。
