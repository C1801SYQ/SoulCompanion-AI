# PC02_DELIVERY_REPORT

更新：2026-10-10。

状态：可执行本地软件测试 AUTOMATED PASS；真实云增量 BLOCKED（待明确授权），未部署。最终微信身份构建和手机验收仍待用户参与，不能将此阶段描述为全部真实微信验收完成。

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

新增 [002 manifest](../../cloud/schema/002_family_identity.json) 和 [独立增量工具](../../scripts/cloud_family_schema.py)，默认纯离线 plan，apply 必须显式授权。完整目标、费用、验收和回滚见 [云变更计划](PC02_CLOUD_CHANGE_PLAN.md)。

真实环境只读审计确认 `soulcompanion-dev-d0dzo6f2a24211` / 上海 / 体验套餐，超额付费与自动续费关闭；AppID、已有函数、网关、7 个集合 ACL 和13个索引已核查。拟新增一个 ADMINONLY 家长集合及唯一 owner 索引、独立 PC02 marker，更新已有函数代码。没有创建或修改真实资源，没有买套餐、容器、GPU、改网关、迁移数据或改变身份提供方。

001 原文件和 canonical checksum `7e23a3c17a1551df1d5a3c7c7c9deb8903f9ea7430fbd38e4fa482e85159fa49` 保持不变。工具绑定 001 / 002 / 运行时三方 hash，拒绝陌生集合、权限/索引不一致和 marker 竞争；ready marker 发布前失败保留 version0，完整后才 version2，重复完成执行只读。发布/读回不确定时先只读核实实际状态，不假定更新未生效。原 Phase04 包保留并核对历史部署 SHA，新部署包在独立忽略目录构建并校验，未部署。

## 验证状态

| 范围 | 当前结果 |
| --- | --- |
| Python cloud / cloud_tools | AUTOMATED PASS：299 项（186 原有 +71 身份 +42 增量工具） |
| 客户端 typecheck / unit | AUTOMATED PASS：404 项 /21 文件；含 effect 执行前的同步草稿隔离 |
| 最终 H5 / weapp +官方 WXSS | AUTOMATED PASS：H5 1779 模块；微信含官方 SDK 1294 模块，22 guard /3 WXSS 官方语法编译 PASS |
| 社区行为 / 七尺寸 | AUTOMATED PASS：最终身份集成产物 11 组 /28 视口样本，公共路径零私有请求与设备授权 |
| 旧 V1 E2E | AUTOMATED PASS：14 组，65 条历史和最终 ONLINE / 无 DEMO |
| 虚拟设备媒体 | AUTOMATED PASS：15 组；真机不是该测试范围 |
| 依赖审计 | 策略 PASS：11 项；36 个既有 finding /10 个审查 advisory，非零漏洞 |
| 独立 Python / 增量工具审查 | APPROVE |
| 独立客户端 / 安全审查 | APPROVE；保存/读取状态与同步草稿隔离的 HIGH/MEDIUM 已修复并独立复核 |
| 正式 TypeScript reviewer | BLOCKED：规定 ESLint 命令因仓库无配置退出1；未引入新依赖，不能写成 APPROVE |
| GitHub Actions | 本阶段提交尚未推送，NOT TESTED；历史 fd3f375 的9项 job成功不代表本次 CI |
| REAL CLOUD PASS | Phase04 历史证据保留；PC02 新持久化 NOT TESTED / 待授权 |
| WECHAT DEVTOOLS PASS | 兼容性构建由用户确认；最终身份构建 MANUAL_VERIFICATION_REQUIRED |
| PHYSICAL DEVICE PASS | NOT TESTED |

本地测试只用合成内容、Fake Adapter / Wire 或 Chromium 虚拟设备。不读取真实儿童资料、不上传音视频、不曝光密钥。不得将本地编译、Fake 登录或浏览器结果写成真实微信登录 PASS。

## 已知限制与交付回执

最终代码、安全和 Python 审查与全部可执行本地回归已完成。身份功能提交、推送 SHA 与本次 GitHub Actions 结果将在交付回执核实；旧 fd3f375 的 CI 不是本阶段结果。

正式 TypeScript reviewer 因缺少 ESLint 配置未完成；现有 typecheck、全量单测、Ruff、JS 语法检查及独立 code-reviewer/安全审查均通过，没有安装新 lint 依赖来改变项目基线。Windows 首次非终端 E2E 启动无诊断退出，正式终端模式重跑及最终集成运行均完成全部断言，未修改或禁用测试。

真实云新增资源：NONE（本轮尚未获得云写入授权）。真实云增量必须取得明确授权后执行，微信扫码、真实登录和两个账号/真机验收须用户参与。具体步骤在人工清单，不要求提供密码、Token 或个人资料。

PC02 之后继续保留 PC01 原型状态；不建立 PC03 分支，不开发真实社区发布/审核，不自动合并 master，不调整 Cloudflare Production。
