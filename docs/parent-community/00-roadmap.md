# 予怀家长社区路线

更新日期：2026-10-12。当前执行 **PC04 真实社区前后端联通与人工审核工作台**，沿用 PC01～PC03 和 Phase 01～04 成果。软件、真实云、微信 DevTools 与手机验收分别记录。

产品面向 0～18 岁儿童家庭，由成年家长/监护人使用。微信小程序优先，H5 用于共享 UI、预览与测试；Android 和实体机器人不属于当前交付。

| 阶段 | 主题 | 当前范围 |
| --- | --- | --- |
| PC01 | 产品重定位与社区可视原型 | 已完成可视原型与自动验证；四入口、筛选、示例详情、内存投稿预览，仍非真实社区前端 |
| PC02 | 微信身份与家庭资料 | 软件与既有 CloudBase API 验收已完成；私有年龄段/公开家长昵称隔离，微信手机登录仍待人工验证 |
| PC03 | 社区数据库与审核后端 | 软件与独立授权后的真实社区后端合成验收已通过；5 ADMINONLY 集合、14 索引、003 marker、既有 API 部署；真实社区前端仍待 PC04 |
| PC04 | 真实社区与运营闭环 | 软件、CI、本地 Fake 与独立授权的真实 CloudBase H5 合成闭环通过；微信完整人工/手机仍待验证，见 PC04 报告 |
| PC05 | 育儿知识与私有成长记录 | 规划；来源核对、手动观察、私有汇总，不冒充 AI |
| PC06 | 真机与受控体验版交付 | 规划；同一代码真实云端和微信手机验收，不自动正式发布 |

PC01 分支 `pc-01-community-prototype`，父提交 `ce95b555bb1667ec653d05960ba2e47210b8b75d`。PC02 有效回执 `39bf161b3a584fe545ae20553f3fc6087297d38d` 是 PC03 基线；PC04 分支 `pc-04-community-integration` 从核对后的 PC03 远端 `c0098ae538128bff6d8f76a20ec8c6a2d52fcb64` 创建。PC04 云写入需要独立新授权，不继承 PC03 授权；不进入 PC05、不合并 master、不升级大模型。

历史 Phase 01～04 成果保留。旧 Phase 05～10 是历史候选路线，社区优先级取代默认下一步推理工作，不改写历史交付报告。

参考 [原路线计划](../v2/PARENT_COMMUNITY_REPLAN.md)、[PC01 产品规格](01-product-spec.md)、[基线审计](PC01_BASELINE_AUDIT.md)、[Phase 04 交付记录](../v2/PHASE04_DELIVERY_REPORT.md)。原计划的候选分支名由本次明确要求的 PC 分支链替代；原始商业附件不提交。

当前进度证据：[PC01 交付](PC01_DELIVERY_REPORT.md)、[PC02 交付](PC02_DELIVERY_REPORT.md)、[PC03 交付](PC03_DELIVERY_REPORT.md)、[PC04 交付](PC04_DELIVERY_REPORT.md)、[PC04 云计划](PC04_CLOUD_CHANGE_PLAN.md)、[PC04 最小契约扩展](PC04_API_EXTENSION.md)、[PC04 微信人工清单](PC04_WECHAT_MANUAL_CHECKLIST.md)。
