# PC02 微信兼容性软件结果

基线：`fd3f3759e7b6555e4b2dfa5b20a01aadac6706ba`，分支 `pc-02-family-identity`。继续保护 PC01 与 Phase01～04，不改 master、不重复建立微信业务页面。

## WXSS

先前根因和最小复现见 [WXSS 修复证据](PC02_WXSS_FIX_REPORT.md)。官方编译器实际拒绝裸伪类选择器；不是根据旧列号推断 `overflow-wrap:anywhere`。修复源 JSX/SCSS 的显式 class，保留样式与 H5 无障碍。

本轮重建 weapp 后，22 项兼容性检查和全部 3 个生成 WXSS 的官方批处理编译通过。没有手改或提交 `dist-weapp`，也没有全局删除函数、变量或媒体查询。

## 平台边界

- 保留四主入口和详情/投稿页面栈。主入口重新打开，详情前进/返回，工具切换只替换工具帧；直接进入 Settings 返回“我的”。快速重复点击由同一未完成跳转接管，失败后可重试。
- 微信独立键盘 hook 在页面隐藏/卸载时移除监听、忽略迟到回调；键盘打开时隐藏底部导航，输入使用 Taro 的键盘避让参数。H5 使用自己的隔离实现。
- 小于 768px 的导航统一位于底部，补齐原 600～767px 中间区间；保留暖米色设计、安全区域和 H5 focus/reduced-motion。
- 列表滚动恢复与投稿草稿用页面可见性/身份 epoch 撤销迟到操作，切换账户不会显示上一份稿件。
- 微信没有配置有效的 V1 HTTPS 地址时返回明确 OFFLINE，七类旧请求均不会发出相对路径 `Taro.request`。H5 同源 `/api/v1` 保留；CloudBase V2 配置、认证及媒体适配器不被替换。

## 验证

| 检查 | 结果 |
| --- | --- |
| 独立兼容性审查 | APPROVE；4 文件 / 50 个 focused tests PASS |
| H5 / weapp 构建 | PASS；官方 WXSS 批处理 PASS |
| 社区行为 / 隐私 | 11 组 PASS；六年龄、七话题、42 组合、详情返回、纯文本预览、公共页面零私有请求和设备授权 |
| 响应式 | 四主页面 × 七尺寸，共 28 组；包含五个要求尺寸和 600/767px；无横向溢出、44px 触控 |
| 旧 V1 E2E | 14 组 PASS；65 条历史、离线恢复、DEMO 标识和错误恢复保持 |
| 媒体回归 | 15 组 PASS；浏览器虚拟设备，离开媒体页释放轨道/上下文 |
| 现有依赖策略 | 11 项策略 PASS；36 个已知 finding / 10 个已审查工具链 advisory 保留，不代表 npm audit 零漏洞 |
| 脚本语法 / diff whitespace | PASS |
| DevTools 手动编译 / 页面切换 | 用户确认 PASS；最终身份构建仍需再次检查 |
| CLI 桥接 | BLOCKED；预期目录无 `.ide-status` / `.ide`，报端口关闭；更深原因未确认 |
| 真机、真实微信登录 | NOT TESTED |

上述浏览器回归使用合成数据，不产生真实云写入。后续人工步骤见 [微信人工清单](WECHAT_MANUAL_CHECKLIST.md)，云端新增资料须先按 [云变更计划](PC02_CLOUD_CHANGE_PLAN.md) 获得授权。
