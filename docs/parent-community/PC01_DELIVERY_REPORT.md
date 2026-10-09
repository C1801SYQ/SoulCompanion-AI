# PC01 交付报告：予怀家长社区产品重定位与可视原型

日期：2026-10-09（Asia/Shanghai）。范围仅 PC01，沿用 Phase 01～04 成果；不合并 master、不进入 PC02、不建立社区云资源。

## 状态与边界

| 交付项 | 状态 |
| --- | --- |
| 社区可视原型 | PASS（本地软件验收；提交和 CI 回执见末节） |
| 真实社区发布 | NOT IMPLEMENTED |
| 真实内容审核 | NOT IMPLEMENTED |
| 微信真机 | NOT TESTED |
| 微信 DevTools / 实际微信身份登录 | NOT TESTED |
| CloudBase 新资源 | NONE |

这是一版可以实际浏览、组合筛选、打开详情、返回和编辑纯文本预览的社区原型。示例帖子、昵称和日期均为合成内容，不是已经上线的真实社区。没有云投稿、评论、点赞、收藏、审核或运营数据，也没有虚构热度、专家合作和医学能力。

## Git 基线与材料

- 已核对本地及 fetch 后的 `origin/04-cloud-backend`，父提交均为 `ce95b555bb1667ec653d05960ba2e47210b8b75d`。没有新的 Phase 04 正式成果需要另行继承。
- 指定分支 `pc-01-community-prototype` 从该基线创建，保护旧阶段历史；未 reset/clean/force push，未修改 master。
- 开始时唯一未提交文件 `docs/v2/PARENT_COMMUNITY_REPLAN.md` 是此前按用户要求完成的路线计划，本次保留并纳入交付，不混入无关文件。
- 已阅读原计划、用户提供的商业书相关章节与十页 PPT。原始附件和完整提取文本留在仓库外或忽略目录；不提交真实个人信息及商业原始材料。材料中的市场、性能、专家和财务陈述不当作软件能力。
- 逐项审计记录：[PC01_BASELINE_AUDIT](PC01_BASELINE_AUDIT.md)。路线及规格：[00-roadmap](00-roadmap.md)、[01-product-spec](01-product-spec.md)。

## 旧成果复用及新增页面

复用 Taro 4.3.0、React 18.3.1、TypeScript 5.9.3、已有 Taroify、AccessibleButton、Primitives、AppShell、Design Tokens、官方 CloudBase SDK/认证、CloudStore、SessionProvider 和媒体适配器。没有新增 UI 框架、认证体系、依赖或锁文件变更。

| 路径 | PC01 功能 |
| --- | --- |
| `pages/community/index` | 默认社区、引导、年龄/话题、示例列表和安全说明 |
| `pages/community/detail` | 示例详情、诚实评论未接入状态、无效 ID 空状态、返回列表 |
| `pages/community/compose` | 标题/正文/主动年龄与话题、校验、内存预览、返回编辑 |
| `pages/knowledge/index` | 分龄及生活情境结构，无来源内容保持空状态 |
| `pages/growth/index` | 私有手动观察说明和未接入空状态，旧家庭工具入口 |
| `pages/profile/index` | 现有登录状态展示、显式账号/私有档案入口、未来社区昵称/投稿/收藏位置 |
| 原 home/session/insights/reports/settings | 原路径及真实/DEMO 功能保留，属于可选家庭工具 |

新增共享 `community/constants.ts`、纯展示 DTO、过滤/校验 model、内存 state、合成 fixtures、ChoiceGroup、PostCard、PostTags、ExampleLabel；新增统一 `navigation.ts` 和独立 `parent-community.scss`。根 README 与客户端 README 更新为予怀路线，历史报告保持原证据。

## 导航、筛选与投稿

四主入口为社区 / 育儿知识 / 成长记录 / 我的。沿用 AppShell 自绘侧栏/底栏，不叠加原生 TabBar，普通详情不配置为 Tab 页。主切换使用 reLaunch，详情与投稿使用 navigateTo/navigateBack；进入家庭工具压栈，工具内切换 redirectTo，当前工具重复点击不重建。

H5 自定义别名与微信规范路径由同一模型处理。验收发现 H5 `getCurrentPages().route` 返回 `/session`，修复其与微信 `pages/session/index` 的识别差异；四种路由形式的回归先失败再通过。列表筛选及滚动仅内存保存，详情返回恢复，包括从最后一条帖子返回的非零滚动位置。直接打开详情无页面栈时回社区。

年龄为全部及六段 0～2、3～5、6～8、9～12、13～15、16～18 岁；话题为亲子沟通、情绪陪伴、习惯与生活、入园入学、学习与同伴、青春期、家长成长。单一常量定义，AND 组合、发布时间倒序、无匹配空状态；无推荐算法或假互动计数。

投稿始终提示“功能预览：目前不会发布到社区”。trim 后标题/正文必填，Unicode code point 上限 80 / 2000，年龄与话题须合法；允许保留超限输入并报错，不静默截断。预览纯文本展示，HTML/脚本/链接不执行、不自动变为可点击内容。草稿只在当前应用内存，刷新及身份 epoch 变化清空；没有真实写入 API、云帖子或审核成功状态。

## 公共/私有数据与设备边界

社区 DTO 不含内部 UID/OpenID、儿童档案、报告或媒体字段。年龄由投稿者主动选择，示例作者来自合成昵称。浏览无需登录、儿童档案、诊断标签、购买或订阅。

公共页不挂载旧 useResource/CloudRecords/CloudAccount。CloudProvider 默认暂停私有读取，AppShell 进入家庭工具才恢复；进入公共页取消 pending，以 revision 忽略迟到响应。全局官方认证对象保留，退出/账户切换/401 清理继续有效，未重建认证。

Session 仍需主动 Start。离开媒体页保持原 hide/unmount 清理，不等待网络结束；新增 active media → community → growth → session 验收确认 tracks/AudioContext/视频附件均释放，返回不自动重启。不上传音视频，不把采样冒充 AI 推理。

`cloud/api`、认证适配器、媒体适配器、`cloud/schema/001_metadata.json` 内容/checksum 与锁文件保持不变。没有修改线上 collection、权限、函数或 HTTP Gateway，没有 SQLite 迁移、付费资源、CloudBase 部署或 Cloudflare Production 设置变更。

## 视觉与可访问性

对外名称统一予怀，必要的内部 SoulCompanion 资源标识保留。米黄背景、柔灰文字、暖棕强调，中文层级和间距面向家长；无紫色 SaaS 模板、玻璃拟态、无意义渐变或新增动画。

桌面侧栏/帖子流/安全说明，移动四入口底栏和自然换行筛选；控件至少 44px，有 aria-current/aria-pressed、文字选中提示及 focus。社区字号使用相对组件基准，避免 Taro 动态根字号导致桌面放大。验证实际内容字体放大、减少动态效果和 Enter/Space。浏览器测试等待活跃页面完成转场，以页面容器读取滚动，不通过固定 sleep 掩盖竞态。DOM 检查不是完整 WCAG/屏幕阅读器认证。

## 自动验证

运行环境 Node.js 24.15.0、Python 3.12.4、现有 Playwright Chromium；小程序编译使用已锁定 Taro。社区测试独立静态服务器仅允许已知构建文件 GET/HEAD，拒绝 API/外部请求/写入/WebSocket，关闭服务器后验证 TCP refusal。旧 E2E 使用隔离合成 65 条 SQLite，媒体使用虚拟设备；不使用真实家庭数据、物理设备或云凭据。

| 检查 | 结果 |
| --- | --- |
| `npm run client:typecheck` | PASS |
| `npm run client:test` | PASS，16 文件 / 296 项（241 原有 + 55 新增） |
| `npm run client:build:h5` | PASS；普通与 CF_PAGES 强制 DEMO 构建 |
| `npm run client:build:weapp` | PASS；11 个页面产物，不能当作真机通过 |
| `npm run client:test:e2e` | PASS，普通模式 14 组；离线恢复仍验证 ONLINE、65 历史、无 DEMO |
| `npm run client:test:media` | PASS，普通模式 15 组，包括媒体离开社区清理 |
| `npm run client:test:community` | PASS，11 行为组及静态测试宿主检查 |
| `python -m pytest tests/cloud tests/cloud_tools -q -p no:cacheprovider` | PASS，186 项 Fake/本地回归 |
| `npm run client:audit` | PASS，11 政策测试；36 个已审阅工具链 findings 保留，不是零漏洞 |
| `npm test` / `npm run test:demo` / `npm run lint` | PASS，38 DOM / 44 DEMO 检查及脚本语法检查 |
| `git diff --check` | PASS |
| CF_PAGES DEMO 浏览器回归 | PASS，旧 E2E 3 组、媒体 15 组、社区 11 组 / 20 样本；CF_PAGES=1 且 PUBLIC_DEMO_ONLY=false 仍强制 DEMO |
| GitHub Actions | 推送后核对，回执待补充 |

社区浏览器覆盖：默认首页、四入口、六年龄/七话题/42 组合、空结果/排序、持续示例标记、详情返回/非零滚动、无效 ID、各字段必填与超限、纯文本攻击字符串、预览/编辑/刷新清空，以及旧 Session/Insights/Reports 进入/返回。

五视口 **375×812、390×844、430×932、768×1024、1440×900** × 四主页面，共 20 响应式样本；验证页面/内部无横向溢出、筛选可点击、主导航可辨识、触控尺寸、字体放大、focus 和 reduced motion。社区公共场景设备/权限、私有 API、发布请求、草稿持久化和浏览器未捕获异常均为 0。

证据在忽略目录 `.test-artifacts/community-acceptance/`、`v2-client-acceptance/`、`v2-media-acceptance/`，CI 同时上传普通与 DEMO 的验收产物。本报告仅记录合成 H5 与 FakeAuth/云隔离回归，**没有重新执行 Phase 04 的真实云登录或部署验收**。

独立 code-reviewer 及 security-reviewer 审查 APPROVE，未发现需修复问题；导航修复已复审。typescript-reviewer 的仓库 typecheck/lint 通过且未发现高风险，但额外 ESLint 因既有仓库无配置不能完成正式检查，未为本阶段安装新 lint 基础设施。构建保留既有 Taro/Vite/Sass 弃用提示，云测试有 Starlette/httpx 弃用提示；均非本阶段伪造的通过。

## Git 交付回执

指定提交消息：`feat: establish Yuhuai parent community prototype`。本地验证完成后按本阶段明确文件提交，正常 push 至 `origin/pc-01-community-prototype`，检查远端 SHA 与本地一致；不推送 master 或 Phase 04。

实现提交 SHA、远端核对 SHA 与 GitHub Actions 链接将在推送并完成 CI 后补入本节。报告的后续回执只更新文档，不改变已验收的实现；最终分支 tip 以 GitHub 分支及最终交付消息为准。

## 已知限制与 PC02 人工前置条件

真实发布/审核/互动、知识文章、手动观察存储仍未实现。微信 DevTools、实际微信身份登录与真机 Camera/Mic/返回生命周期仍未验证；H5 虚拟设备和 weapp 构建不能替代这些步骤。Android、实体机器人、媒体上传和大模型升级均未实施。

后续 PC02 需所有者准备：具有既有 AppID 权限的微信开发者工具账号和测试手机；核实小程序主体/管理员/合法 request 域名及既有环境使用权限；确认公开家长昵称、私有儿童资料和 0～18 年龄字段的产品规则与隐私文案。涉及凭据时通过官方登录或受控配置完成，不将 AppSecret/令牌发送到聊天或提交 Git。既有 CloudBase 体验环境有期限与配额，续用成本由所有者确认，不称为永久免费。

只有另行授权下一阶段后，才从通过 PC01 的分支建立 `pc-02-family-identity`。本次到 PC01 停止，无新云资源。
