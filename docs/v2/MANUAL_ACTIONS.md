# Phase 04 人工操作与待完成验收

最后更新：2026-10-08（Asia/Shanghai）。

Phase 04 云后端开发、部署与自动验收 PASS：实际 CloudBase API 11 项、官方 SDK H5 浏览器 12 项全部通过，最终本地测试、验收后费用复核与同一已推送代码 `0ee5b4e` 的九项 CI 均成功。本文记录尚未完成的微信开发者工具与物理手机测试，不把 H5 或构建结果当作微信人工验收。

## 当前已确认的公开配置

| 项目 | 值 | 状态 |
| --- | --- | --- |
| 分支 | `04-cloud-backend` | Phase 04 开发分支；不进入 Phase 05 |
| CloudBase 环境 | `soulcompanion-dev-d0dzo6f2a24211` | 使用用户确认的已有环境 |
| 地域 | `ap-shanghai` | 上海 |
| 微信小程序 AppID | `wx11a055ed4dc69764` | 已在现有 CloudBase 微信认证配置中核对 |
| HTTP 云函数 | `sc-v2-api` | 已创建并核对 Python 3.11 / 256 MB / 3 秒配置 |
| 公共网关域名 | `soulcompanion-dev-d0dzo6f2a24211-1501181209.ap-shanghai.app.tcloudbase.com` | `/` 路由、真实 health/ready、元数据 API 与 H5 SDK 验收 PASS |
| CloudBase Auth 域名 | `soulcompanion-dev-d0dzo6f2a24211.api.tcloudbasegateway.com` | 官方认证入口 |

上述 AppID、环境 ID 与域名是公开标识。不要将 AppSecret、服务端 API key、登录文件、访问令牌或刷新令牌填入前端配置、截图、Issue、README 或聊天消息。

## 微信开发者工具

1. 安装并打开微信官方开发者工具，使用对 AppID `wx11a055ed4dc69764` 有权限的微信账号登录。当前未完成实际开发者工具或真机验收。
2. 网关路由、健康检查及实际环境配置的小程序构建已通过。当前电脑可直接导入步骤 3 的生成目录；如更换电脑或需要重建，在仓库根目录执行下列公开配置构建。`PUBLIC_API_BASE_URL` 必须是域名的 HTTPS origin，不包含 `/api/v2`：

   ```powershell
   $env:PUBLIC_CLOUDBASE_ENV_ID = 'soulcompanion-dev-d0dzo6f2a24211'
   $env:PUBLIC_CLOUDBASE_REGION = 'ap-shanghai'
   $env:PUBLIC_WECHAT_APP_ID = 'wx11a055ed4dc69764'
   $env:PUBLIC_API_BASE_URL = 'https://soulcompanion-dev-d0dzo6f2a24211-1501181209.ap-shanghai.app.tcloudbase.com'
   $env:PUBLIC_DEMO_ONLY = 'false'
   Remove-Item Env:CF_PAGES -ErrorAction SilentlyContinue
   npm run client:build:weapp
   ```

   这些环境变量已与仓库 `.env.example` 和客户端配置源码核对。`CF_PAGES` 仅在当前本地终端中清除，公开 Cloudflare 配置保持不变。构建步骤只使用公开配置。
3. 在开发者工具选择“导入项目”，项目目录选择 `D:\SoulCompanion_AI\apps\client\dist-weapp`，填入上述 AppID。使用构建生成的 `project.config.json`（`miniprogramRoot: "./"`）；不要导入 H5 输出目录 `apps/client/dist`。也可导入 `apps/client`，其源项目配置已指定 `miniprogramRoot: "dist-weapp/"`。
4. 在微信公众平台的小程序后台确认该 AppID 已关联同一个 CloudBase 环境。CloudBase 已存在的微信认证提供方配置已核对，平台侧实际权限和真机可用性仍需人工验证。若界面需要 AppSecret，应由有权限的操作者在官方平台输入，不发送给开发代理或写入仓库。
5. 在小程序后台“开发管理 → 开发设置 → 服务器域名”中，将下列 HTTPS origin 加入 `request` 合法域名：

   - `https://soulcompanion-dev-d0dzo6f2a24211-1501181209.ap-shanghai.app.tcloudbase.com`
   - `https://soulcompanion-dev-d0dzo6f2a24211.api.tcloudbasegateway.com`

   验收时启用合法域名校验。若真实网络记录显示官方 SDK 还需要其他官方域名，依据 SDK 实际调用和官方说明核对后添加，不能用关闭域名校验替代真机验证。
6. 在开发者工具中重新编译，进入云账户页面，点击“使用微信账号登录”，完成昵称修改、儿童档案新增/修改/选择/归档，以及云端会话开始和结束。小程序通过官方 SDK 的微信 OpenID 登录，不输入 Web 用户名密码。核对退出后档案和会话页面立即隐藏私有信息。
7. 使用“预览”二维码在手机微信中重复上述流程。检验拒绝设备权限、后台切换、结束会话和网络断开后的本地停止行为。真实相机/麦克风内容不应出现在云端请求中。
8. 使用两个独立测试账户验证所有权隔离。不得把一个账户的档案或会话展示给另一个账户。测试截图只保留无敏感内容的状态信息；不要截取账号密码、令牌、请求授权头或完整个人档案。

## 自动验收结果与发布收尾

| 项目 | 当前状态 | 完成条件 |
| --- | --- | --- |
| HTTP 网关路由 | PASS | 现有 `/` 路由到 `sc-v2-api`；WEB_SCF、enable=true、auth=false、pathTransmission=true；总 QPS 100、单 IP QPS 5 |
| 公共 health / ready / 匿名 me | PASS | 最新函数更新后实际 HTTPS health 200/ok、ready 200/healthy、匿名 me 401；响应 request ID 存在 |
| 允许的本地 origin 预检 | PASS | 实际 OPTIONS 204，响应 origin 精确为 `http://127.0.0.1:18404`；实际 H5 SDK 业务链路通过 |
| CloudBase Auth 与 SDK | PASS | 两个已有合成身份真实登录/introspection；SDK H5 登录/退出；旧令牌 401 |
| 云端 CRUD 与 IDOR | PASS | 真实 API 11 项全部 true：档案/会话操作、owner 隔离、匿名拒绝、字段 422、直连数据库 401/403 |
| 云端浏览器验收 | PASS | 官方 SDK H5 12 项全部 true；无持久 token/cookie、自动设备获取或原始媒体请求 |
| 最新代码 GitHub Actions | PASS：`0ee5b4e` 九个作业 | [Actions 37717747946](https://github.com/C1801SYQ/SoulCompanion-AI/actions/runs/37717747946) 同一实际验收代码全部成功 |
| 最终用量复核 | PASS | 当前周期使用 1.45/3000 套餐内资源点，按量计费 0 点，超额付费/自动续费关闭；记录于 [交付报告第 25 节](PHASE04_DELIVERY_REPORT.md#25-cloudbase-resource-usage)，计量可能延迟 |

真实验收已使用下列复现命令。该模式只复用经拥有者检查的两个现有合成账户，在私有输入中重置它们的测试密码，不再创建认证账户。不要导出或提供测试密码、令牌或登录文件；开发环境需使用已授权的官方 CLI 登录。该命令是显式云写入验收，CI 只运行无凭据的计划模式。

```text
python scripts/cloud_acceptance.py --apply --browser --reuse-fixtures
```

公开结果位于本地忽略目录 `.test-artifacts/cloudbase-phase04/acceptance-public.json`，包含 `status=pass`、`fixture_mode=reuse`、62 个请求、0 次限流重试、最大延迟 2298 ms；不含任何凭据。两个合成认证用户、应用身份、归档档案和结束会话元数据会保留。同一实际验收代码已经推送且九项 CI 全部成功；微信 DevTools/真机测试由上述人工步骤完成。

## 服务端 key 轮换

本轮服务端 API key 的有效期为 30 天。它仅保存在忽略的本地部署配置和云函数托管环境变量中；不得复制到客户端、命令行参数、公开证据或文档。由有权限的操作者在官方控制台创建替代 key，更新云函数托管环境变量，部署并通过真实健康检查、认证和所有权验收后，撤销旧 key。轮换完成后复查云函数配置时只检查变量名称与存在性，不展示值。

体验版当前到期日为 2027-04-07；已有环境的超额付费和自动续费均为关闭状态。到期前由所有者决定续用方案。本轮没有授权购买、升级、开启超额付费或自动续费。若任何资源确需付费，停止该项云资源写入并给出 `PAID_RESOURCE_REQUIRED`、具体原因与免费替代方案，等待所有者决定。

## 保持范围

公开 Cloudflare 页面继续保持 `DEMO_ONLY`，不能在本轮切换到生产 API。Phase 04 不引入云端音视频上传、云端推理、SQLite 数据迁移或 Phase 05 功能。本地会话结束必须先停止本地设备，不等待云端会话元数据更新。
