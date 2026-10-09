# PC02 微信 WXSS 编译修复

本次只修复微信样式编译，不实施 PC02 其他功能。分支为 `pc-02-family-identity`，父提交与已核对的 PC01 最新远端均为 `a58320ba5384fff7b872ccbd450609088bdf53a4`。开始时工作区干净，PC02 本地、远端分支均不存在；从该 PC01 提交创建分支，没有回退、覆盖历史或合并 master。

## 根因与复现证据

使用本机微信开发者工具 `2.02.2608080` 所带的官方 `wcc-exec/wcsc.exe`，版本 `v0.4me_20200724_db`，实际离线编译失败，报错为：

```text
ERR: app-origin.wxss(1:10961): error at token `:`
```

失败的是未用元素或类名限定、直接出现在复合选择器起始位置的伪类，例如 `.sc-soft-note > :first-child`。将其改为具名展示类，或把已有类名移到伪类之前，官方编译器通过。不是依据错误附近的 CSS 属性猜测。

重新生成的修复前产物 UTC 时间为 `2026-10-09T09:17:24.216480+00:00`，47887 字节、47887 字符，全为 ASCII，无 UTF-8 BOM。SHA-256 为 `6587124f59f9c92edef598cd1397ef4d3b67843538fd50318fc670fd172c7d0e`，与重建前一致。

本次产物第 10961 列（一基）即 UTF-8 字节偏移 10960（零基），为 `.sc-soft-note>:first-child` 中的冒号。用户历史报错第 12086 列在本次产物中是 `.sc-history-cause` 内的 `o`；该选择器起始偏移为 12077。因此不能把不同产物或编译结果的列号直接视为同一原因。

采用 PostCSS 解析后的完整规则二分，保留括号与媒体查询结构，从 356 个顶层节点缩小到单条失败规则。随后逐条调用官方编译器检查 581 条应用规则和 390 条 Taroify 规则：应用中有 12 处上述选择器失败，Taroify 的全部规则及完整 `vendors.wxss` 均通过。

| 最小输入 | 官方编译结果 |
| --- | --- |
| `.sc-soft-note>:first-child{font-weight:600}` | FAIL，冒号 |
| `.sc-soft-note>text:first-child{font-weight:600}` | PASS |
| `.sc-soft-note>.sc-soft-note-title:first-child{font-weight:600}` | PASS |
| `.pc-shell .sc-page-header>:last-child.pc-action{width:100%}` | FAIL，冒号 |
| `.pc-shell .sc-page-header>.pc-action:last-child{width:100%}` | PASS |
| `.sc-history-cause` 原属性，包括 `overflow-wrap:anywhere` | PASS |
| 具名 `:focus-within`、`:focus-visible`，`:root,page` 和 `var()` | PASS |
| `calc()`、`clamp()`、`env()`、`repeat()`、`minmax()` | PASS |
| 宽度媒体查询与 `prefers-reduced-motion` | PASS |
| 未展开的 CSS 嵌套、生成产物中的 `*` 选择器 | FAIL；实际产物无此失败规则 |

这些 PASS 只说明本机官方编译器接受语法，不证明所有基础库版本的视觉效果。未删除上述函数、变量、媒体查询、无障碍样式或 `overflow-wrap:anywhere`。Taro 会转换原始通配选择器，因此回归检查作用于最终 WXSS，而不是全局禁止 H5 源 SCSS。

## 生成 WXSS 与源文件对应

`src/app.tsx` 引入共享设计 SCSS；`styles.scss` 使用 `tokens.scss`。Taro/Vite 编译并将 px 转换为 rpx，形成 `app-origin.wxss`；Taroify 样式形成 `vendors.wxss`；`app.wxss` 导入这两份样式。未修改 `tokens.scss` 或第三方包，也未提交生成的 WXSS。

以下偏移为修复前 `app-origin.wxss` 内规则起始 UTF-8 字节偏移（零基），源文件行号为本次修改后的行号：

| 生成规则与偏移 | 原始 SCSS | 修复方式 / 对应页面 |
| --- | --- | --- |
| `.sc-soft-note>:first-child`，10946 | `styles.scss:84` | `.sc-soft-note-title`；Home:35 |
| `.sc-distribution-heading>:last-child`，17355 / 31087 | `styles.scss:97,146` | `.sc-distribution-value`；Insights:39，含移动样式 |
| `.sc-report-note>:last-child`，19041 | `styles.scss:100` | `.sc-report-note-text`；Reports:13 |
| `.sc-profile>:nth-child(2)`，19364 | `styles.scss:101` | `.sc-profile-copy`；Settings:27 |
| `.sc-setting-row>:first-child`，20841 / 24601 / 26238 | `styles.scss:102,128,136` | `.sc-setting-copy`；Settings:36，含响应式覆盖 |
| `.sc-settings-facts>:last-child`，21930 | `styles.scss:104` | `.sc-setting-fact-last`；Settings:44 |
| `.sc-system-row>:first-child`，22187 | `styles.scss:105` | `.sc-system-copy`；Settings:50 |
| `.sc-media-permission-row>:last-child`，36954 | `styles.scss:203` | `.sc-media-permission-value`；Session:93 |
| `.pc-shell .sc-page-header>:last-child.pc-action`，46839 | `parent-community.scss:92` | 重排为 `.pc-action:last-child`，语义不变 |

只新增展示 `className`、调整选择器，没有改变声明值与选择器优先级。社区、旧 Home/Session/Insights/Reports/Settings 的页面内容、事件与状态逻辑保持原样。CloudBase、媒体适配器、Provider、导航、隐私边界、数据库迁移、依赖锁文件均未修改。没有部署或创建云资源。

最终重建产物 UTC 时间为 `2026-10-09T13:11:40.050Z`，47968 字节、47968 字符，无 UTF-8 BOM；SHA-256 为 `265f7ae9b8b3d204a20c184816cad729bec8a3a675c56aca1597f95b302e30f8`。官方批量编译 `app.wxss`、`app-origin.wxss`、`vendors.wxss` 退出码为 0，无 `ERR`，生成非空编译输出。

## 回归保护

- [WXSS 检查器](../../scripts/check_weapp_wxss.cjs) 递归解析实际生成文件；裸伪类、生成通配选择器、未展开嵌套、缺失产物及解析失败均使检查失败。允许已验证的限定伪类、变量、函数与媒体查询；这不是完整的 WXSS 支持矩阵。
- [22 项检查器测试](../../scripts/test_weapp_wxss.cjs) 覆盖真实失败选择器、组合边界、属性字符串、转义、嵌套、缺失文件，以及官方编译器缺失、异常退出和退出码为零但输出 `ERR:`。
- 两项脚本已接入 `apps/client/package.json` 的 `build:weapp`，现有 GitHub Actions 的微信构建任务会运行。未新增依赖。
- `WECHAT_WXSS_COMPILER` 可配置官方可执行文件路径；未配置时明确输出 `NOT RUN`。配置但无法执行时失败，不跳过。
- 官方 `wcsc` 的导入解析需要把入口及被导入文件同时作为命令输入，不能只逐文件编译并依赖 cwd。检查器一次提供全部生成 WXSS，使用参数数组、无 shell、超时限制，不上传或发布。

本机验证命令示例（根据实际安装路径调整）：

```powershell
$env:WECHAT_WXSS_COMPILER='D:/Program Files (x86)/Tencent/微信web开发者工具/resources/app.asar.unpacked/node_modules/wcc-exec/wcsc.exe'
npm run client:build:weapp
# 已构建后的单独检查：
npm run client:check:wxss
```

## 验证结果

Node.js `24.15.0`；Python `3.12.4`，复用本地隔离测试环境。浏览器使用已有 Playwright Chromium，媒体使用虚拟设备或 Fake Adapter。

| 项目 | 结果 |
| --- | --- |
| `npm run client:typecheck` | PASS |
| `npm run client:test` | PASS，16 文件 / 296 测试 |
| `npm run client:check:wxss` | PASS，22 检查；3 个生成文件官方批量编译通过 |
| `npm run client:build:h5` | PASS |
| `npm run client:build:weapp` 最终完整流程 | PASS，含 22 项检查及官方批量编译 |
| `npm run client:test:community` | PASS，11 组行为验收、5 种规定屏幕尺寸 |
| `npm run client:test:e2e` | PASS，14 组既有验收；离线恢复、65 条历史与 DEMO 隐藏断言保留 |
| `npm run client:test:media` | PASS，15 组验收；采集页进入社区会释放设备、返回不自动重启 |
| `npm run client:audit` | PASS，11 策略检查；保留既有 36 条 findings / 10 项已审查工具链 advisories，不代表零漏洞 |
| `python -m pytest tests/cloud tests/cloud_tools -q -p no:cacheprovider` | PASS，186 测试 |
| `git diff --check` | PASS，最终提交前再次检查 |
| `npm run lint` | PASS，仓库既有 JavaScript 语法检查 |
| 独立 code-reviewer | 展示样式与批量检查复核通过，无需修复的问题 |
| 独立 TypeScript reviewer | Typecheck PASS；仓库未配置 ESLint，无法完成其额外 ESLint 门槛；没有添加配置或依赖 |
| 开发者工具整项目模拟器预览 | NOT TESTED |
| 微信真机 | NOT TESTED |

已实际执行本机官方编译器，不能将 `npm run client:build:weapp` 的产物生成等同于开发者工具预览通过。原始复现、二分与逐规则结果留在忽略的 `.test-artifacts/wxss-diagnosis/`，不提交生成文件。

## 用户仍需完成的验收

1. 更新到 `pc-02-family-identity` 的本次修复提交，使用 Node.js 24 执行 `npm run client:build:weapp`。
2. 微信开发者工具导入仓库的 `apps/client` 项目（其 `project.config.json` 指向 `dist-weapp/`），使用现有 AppID；确认工具读取的是本次重建目录，清除旧编译缓存后重新编译。
3. 检查社区、知识、成长、我的，以及旧家庭工具；验证帖子返回、筛选状态、中文排版与小屏布局。
4. 在真机主动开始媒体预览并离开陪伴页，确认设备释放；浏览社区时不应请求设备权限或读取私有家庭数据。

不需要新 CloudBase 资源、修改权限或重新生成认证体系。本次到此停止，不继续开发 PC02 其他功能。
