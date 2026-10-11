# PC04 依赖暴露面与包体审计

审计日期：2026-10-11。基于 PC03 父提交 `c0098ae538128bff6d8f76a20ec8c6a2d52fcb64` 和 PC04 工作区的实际安装依赖、源码、平台别名、审计 JSON 及本机构建产物。依赖分析未修改 package.json、lockfile、框架版本或云资源。分包改动属于 PC04 独立实现；这里记录其测量结果。

## 结论和证据口径

`npm run client:audit` 的既有例外策略检查通过，审计 harness 的 11 项检查通过；**依赖并不干净**：36 项包级 finding，1 critical / 29 high / 6 moderate，对应 7 个受影响叶子包、10 个不同 advisory。传递依赖会传播风险等级，包级数量不能与 advisory 数量或可利用入口数量直接等同。

critical `decompress@4.2.1` 位于 Taro CLI 模板下载/解压链。社区正文、评论和举报不会进入该解压函数；构建机器处理不可信模板或压缩包仍有真实风险，不能因为它属于工具链而忽略。[上游公告](https://github.com/advisories/GHSA-mp2f-45pm-3cg9)没有为原始 `decompress` 包列出修复版本。

现有应用入口、平台运行时别名及已安装模块解析支持以下判断：受影响的工具链叶子版本没有发现从社区运行源码进入浏览器或小程序的引用；H5 路由确实使用 URL 解码器，但解析到未落入本次受影响范围的 `decode-uri-component@0.5.0`。这是对实际入口图的审计结论，**不是完整 Rollup 模块清单或所有未来构建的零漏洞证明**。没有为了消除 audit 输出而使用 `npm audit fix --force`、降级 Taro 或扩大例外策略。

本地证据保留在忽略目录，不提交原始构建、node_modules 或可能混入环境配置的日志：

- `.test-artifacts/client-dependency-audit.json`：2026-10-11 12:49（UTC+8）取得的 npm audit 数据。
- `.test-artifacts/pc04-audit/dependency-bundle-baseline.json`：依赖、初始 SDK 未启用 weapp 产物与来源快照。
- `.test-artifacts/pc04-weapp-before-optimization.json`：真实 SDK 配置下分包前测量。
- `.test-artifacts/pc04-weapp-bundle.json`：普通分包后测量。

审计时 `apps/client/package-lock.json` SHA-256：`abbb2ef62113abd65a245d5f8d33de710a079de213832b130ac23006be54d821`。

## 七个叶子包及其调用链

下表的版本和路径来自当前 lockfile 与安装文件。`dev` 标记只能说明 npm 的安装分类，不能单独证明某段代码会进入用户运行时。例如构建插件列在 dependencies 中，其 Node 侧 helper 仍然属于构建代码。

| 受影响叶子版本 | 已核查的实际链 / 入口 | 当前暴露判断 |
| --- | --- | --- |
| `braces@3.0.3` | Taro helper → `chokidar` → braces；Vite runner → `fast-glob` → micromatch → braces；位于根 `node_modules/braces` | 文件匹配、开发监听和样式构建工具链；无社区运行输入调用证据。深嵌套模式可造成栈耗尽，不能把 `dev:false` 当成浏览器暴露的证据。[公告](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) |
| `decode-uri-component@0.2.2` | CLI HTTP 缓存链 → `normalize-url` → 其嵌套 `query-string@5.1.1` → `normalize-url/node_modules/decode-uri-component` | 受影响副本位于工具链；H5 路由使用另一份 `query-string@9.5.1` → 根解码器 `0.5.0`，不能混淆这两份安装。[公告](https://github.com/advisories/GHSA-vcc3-ghjq-m6fr) |
| `decompress@4.2.1` | `@tarojs/cli/dist/create/fetchTemplate.js` → `download-git-repo@3.0.2` → `download@7.1.0` → decompress | 模板压缩包解压，存在路径/链接逃逸风险；没有被社区输入触发的路径。构建主机风险仍保留。[公告](https://github.com/advisories/GHSA-mp2f-45pm-3cg9) |
| `git-clone@0.1.0` | 同一 CLI 模板入口 → `download-git-repo` → git-clone | Node 侧模板克隆命令；不接收社区帖子内容。攻击者可控制克隆参数时有命令注入风险。[公告](https://github.com/advisories/GHSA-8jmw-wjr8-2x66) |
| `got@8.3.2`、嵌套 `got@9.6.0` | CLI 模板下载，以及 `package-json` 的版本/元数据 HTTP 请求 | 工具链 HTTP；当前社区网络请求使用受控 Taro transport，没有导入 got。低版本重定向存在 UNIX socket 风险。[公告](https://github.com/advisories/GHSA-pfrx-2q88-qq97) |
| `html-minifier@4.0.0` | `@tarojs/vite-runner/dist/mini/emit.js:244` 的 WXML 模板生成分支 | Node 构建端；当前 `mini.minifyXML.collapseWhitespace:false` 使所核查的 `require('html-minifier')` 分支不执行。关闭该分支不等于卸载依赖或修复所有调用入口。[公告](https://github.com/advisories/GHSA-pfq8-rq6v-vf5m) |
| `http-cache-semantics@4.2.0` | got → cacheable-request；包括 `package-json` 嵌套缓存请求 | Node 工具 HTTP 缓存；社区 transport 没有该缓存实现。公告描述的跨用户缓存泄露仍需在依赖升级时处理。[公告](https://github.com/advisories/GHSA-ch52-4w7c-c8xp) |

10 个 advisory 的完整对应如下，避免将四个 decompress 公告当成四份可独立计数的包：

| 包 | Advisory |
| --- | --- |
| braces | [GHSA-vfj7-8cjw-p6xm](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) |
| decode-uri-component | [GHSA-vcc3-ghjq-m6fr](https://github.com/advisories/GHSA-vcc3-ghjq-m6fr) |
| decompress | [GHSA-mp2f-45pm-3cg9](https://github.com/advisories/GHSA-mp2f-45pm-3cg9)、[GHSA-h39j-r5qq-r9mm](https://github.com/advisories/GHSA-h39j-r5qq-r9mm)、[GHSA-jwp9-9v96-94mx](https://github.com/advisories/GHSA-jwp9-9v96-94mx)、[GHSA-hrh2-vp3x-79xf](https://github.com/advisories/GHSA-hrh2-vp3x-79xf) |
| git-clone | [GHSA-8jmw-wjr8-2x66](https://github.com/advisories/GHSA-8jmw-wjr8-2x66) |
| got | [GHSA-pfrx-2q88-qq97](https://github.com/advisories/GHSA-pfrx-2q88-qq97) |
| html-minifier | [GHSA-pfq8-rq6v-vf5m](https://github.com/advisories/GHSA-pfq8-rq6v-vf5m) |
| http-cache-semantics | [GHSA-ch52-4w7c-c8xp](https://github.com/advisories/GHSA-ch52-4w7c-c8xp) |

来源为原始 GitHub Reviewed advisory 及本地 npm 快照。多数公告在本轮浏览复核；got 公告页面工具访问失败，因此其风险描述按审计 JSON 保留，不声称本轮复核了该页面最新正文。版本修复建议和风险等级以执行审计当天的记录为准，后续升级前应再次核验上游。

## 用户运行代码与构建代码的对应

1. 应用源码使用 `@tarojs/taro`、React、Taroify、共享社区 DTO/组件和安全 transport；没有导入上述七个受影响叶子包。唯一 `@tarojs/cli` 引用位于 [构建配置](../../apps/client/config/index.ts)，不在页面入口。
2. 已安装 `@tarojs/taro/index.js` 只接入 `@tarojs/runtime` 的 hooks 与 `@tarojs/api`。H5 插件将 `@tarojs/taro` 别名映射到 `dist/runtime/apis`；插件顶层的 `@tarojs/helper` 用于编译器，并非应用导入目标。Mini runner 同样在 Node 进程执行 helper、文件读写与模板 emit。
3. H5 的已安装 `@tarojs/router/dist/router/{page,multi-page}.js` 导入 `query-string`。沿实际安装解析得到 `query-string@9.5.1` 和 `decode-uri-component@0.5.0`，与 normalize-url 内的受影响副本分开。[解码器公告](https://github.com/advisories/GHSA-vcc3-ghjq-m6fr)的受影响范围到 `0.4.2`。
4. 官方 CloudBase SDK 是用户运行依赖。H5 的 [平台适配](../../apps/client/src/cloud/auth/platform.h5.ts)在 `PUBLIC_CLOUD_ENABLED` 分支动态导入 `@cloudbase/js-sdk`；微信的 [平台适配](../../apps/client/src/cloud/auth/platform.weapp.ts)另导入 `@cloudbase/adapter-wx_mp`。REAL 配置产物包含这些模块的运行成本，SDK 未启用的产物不能代表真实包体。
5. 本次未导出完整 Rollup 模块图、逐模块字节归属或 SBOM。对“受影响叶子未进入用户 bundle”的判断来自已核查入口/平台别名/解析链，仍有传递图覆盖限制；不能仅凭压缩文件中搜索不到包名宣称彻底排除。包体测量只按文件字节记账，不把整个 vendors 文件归给某一个依赖。

## weapp 包体快照

所有数字为构建目录中**全部文件的未压缩字节和**，包含 manifest 和元数据；不是微信官方上传的压缩包大小或上传审核结论。初始默认构建与真实 SDK 配置的差异主要来自运行依赖和本轮功能，不能把不同配置间的差值全部算作优化成果。

| 快照 | 文件数 | 主包 bytes | 总包 bytes | 普通分包 | SDK 状态 |
| --- | ---: | ---: | ---: | ---: | --- |
| PC04-A 初始产物 | 48 | 832,560 | 832,560 | 0 | 未启用；仅用于初始对比 |
| 2026-10-11 18:06 分包前 | 54 | 1,829,515 | 1,829,515 | 0 | REAL 配置，官方 SDK |
| 2026-10-11 18:07 分包后 | 54 | 1,750,966 | 1,830,140 | 6 | 同一 REAL 配置，官方 SDK |
| PC04 最终软件修复后 | 54 | 1,751,999 | 1,831,370 | 6 | REAL 配置，官方 SDK |

以上为已落盘证据快照；最终交付以同一次构建生成的 `pc04-weapp-bundle.json` 为准。18:06/18:07 分包前后快照的主包减少 78,549 bytes，总包增加 625 bytes，主要是将低频页面文件分出并增加分包元数据，**不是总下载量降低**。最终软件修复另有源码变动，不能用它与更早源码的差值冒充纯分包优化效果。

18:07 分包快照的六个普通包（最终源代码修复后会有小幅变化）：

| root | bytes |
| --- | ---: |
| `pages/home` | 8,010 |
| `pages/session` | 16,050 |
| `pages/insights` | 6,861 |
| `pages/reports` | 7,010 |
| `pages/settings` | 24,168 |
| `pages/ops` | 17,075 |

18:07 分包快照中最大文件的实际字节如下，不能从单个文件大小精确拆分 CloudBase、React、Taroify 的份额：

| 文件 | 分包后 bytes | 可核查来源 |
| --- | ---: | --- |
| `vendors.js` | 1,126,995 | node_modules 运行依赖汇总；官方 SDK、平台适配、UI 运行依赖仍共享于主包 |
| `taro.js` | 227,029 | Taro/小程序 React 运行支持 |
| `common.js` | 156,746 | 应用共享模块与公共入口代码 |
| `base.wxml` | 63,233 | Taro 组件模板 |
| `app-origin.wxss` | 49,694 | 应用 SCSS 编译结果 |
| `vendors.wxss` | 26,580 | 依赖组件样式 |

最终 18:17 产物的 vendors/Taro/template/style 数字相同；`common.js` 为 157,215 bytes、`pages/community/detail.js` 为 22,218 bytes、ops 普通分包为 17,272 bytes。这些增量来自后续软件修复，最终主包仍在项目预算内。

## H5 快照

2026-10-11 18:15 本地 `apps/client/dist` 共 20 文件、1,201,704 bytes；最大 JS 为 `vendors.DH55ypeO.js` 755,108 bytes、`common.IcN4gSps.js` 203,040 bytes，主 CSS 49,174 bytes、依赖 CSS 34,874 bytes。该构建采用默认配置，没有设置 `PUBLIC_API_BASE_URL`，所以官方 CloudBase SDK 未启用；日志报告 1,791 个模块转换。不能拿这份默认 H5 体积当成 REAL 官方 SDK 配置的测量结果。

该项是当前磁盘产物测量，不是浏览器传输大小，不据此声称 Cloudflare Production 更新、微信预览通过或模块图完整。H5 浏览器功能、隐私边界及 REAL 请求的验收结果应结合阶段交付报告中的专门测试记录；Fake SDK 浏览器测试也不能代替真实 SDK 运行的模块审计。

## 分包、按需注入与回归门槛

[app.config.ts](../../apps/client/src/app.config.ts)使用六个**非独立**普通分包，保留原 Session/Insights/Reports/Settings/Home/Ops 页面路径和同一应用身份上下文。社区四主入口及详情、投稿、本人内容仍在主包；没有把普通详情误设为原生 Tab。

`lazyCodeLoading:'requiredComponents'` 由 Taro 官方 [全局配置文档](https://docs.taro.zone/docs/app-config/)与本地 4.3 类型支持。它控制组件代码注入策略；不直接缩小已生成的文件，也不能代替微信 DevTools 和真机验证。普通页面分包没有把共享 vendors/SDK 一并搬走，因此包体的主要运行依赖成本仍在主包。没有以替换框架或重复身份体系换取数字变小。

[包体回归脚本](../../scripts/check_weapp_bundle.cjs)按 manifest root 归属文件，拒绝符号链接、重复/重叠 root、independent 包，检查每个包和总包；[回归测试](../../scripts/test_weapp_bundle.cjs)覆盖非法 manifest 与预算失败。预算为项目自行设定的保守门槛：主包 2 MiB、每个分包 2 MiB、总包 20 MiB。**这些不是对微信平台当前所有主体/基础库官方限制的声明**，官方上传器的实际结果仍需单独记录。

可重复执行的验收：

```bash
npm run client:audit
npm run client:build:h5
npm run client:build:weapp
node scripts/test_weapp_bundle.cjs
node scripts/check_weapp_bundle.cjs
```

正式 SDK 测量应使用已核对的公开 API origin 配置；不写入登录密码、Token 或 Secret。普通分包的导航、返回、共享登录和媒体释放需要既有浏览器回归及微信手工清单共同验收。此报告未执行微信官方上传、整项目 DevTools 编译或手机真机测试，不能给这些项目标记 PASS。

## 后续边界

依赖升级另行评估 Taro 上游、替代工具维护情况及锁定版本兼容性；本轮没有依赖/lockfile 变动。既有 audit 例外继续可见、可失败，不能用 `continue-on-error` 隐藏新风险。避免让构建工具处理用户上传压缩包、任意模板源或社区正文；本阶段没有建立这些能力。若未来引入服务端上传/解压，应重新进行独立安全设计与依赖审计。
