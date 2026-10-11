# PC04 最小兼容读取契约

基于 [PC03 契约](PC03_API_CONTRACT.md)，只新增两个经过认证的 GET；原响应、写入规则、数据库 schema 001/002/003、集合、索引与授权体系不变。方案已在 [基线审计](PC04_BASELINE_AUDIT.md) 提出。当前本地实现通过回归；真实部署状态见 [交付报告](PC04_DELIVERY_REPORT.md)。

## 本人互动状态

`GET /api/v2/me/community/posts/{post_id}/relations`

```json
{"post_id":"<UUID>","liked":false,"bookmarked":false}
```

从已验证主体派生本人关系键；不接受 owner、UID、OpenID。父帖在读取前后均须公开。匿名 401，父帖不可公开 404，仓储异常或关系完整性异常 503。没有关系代表 false；客户端在读取失败时保持未知状态，不假设 false，不启用未确认的切换。

## 本人当前版本审核反馈

`GET /api/v2/me/community/{posts|comments}/{id}/feedback`

```json
{
  "target_type":"post",
  "target_id":"<UUID>",
  "content_revision":1,
  "status":"rejected",
  "feedback":{
    "action":"reject",
    "reason":"<审核理由>",
    "at":"<UTC 时间>",
    "content_revision":1
  }
}
```

无当前版本反馈时 `feedback:null`。先检查内容所有权，其他用户与不存在资源统一 404。只返回当前正文版本的最近 approve/reject/hide；编辑后 pending 不复用旧版反馈。无 actor、内部运营身份、动作键、hash 或完整审计记录。本人内容和反馈仅内存存在，退出、切换或失效同步隐藏并丢弃旧响应。

## 安全验证与部署边界

[新增 HTTP 回归](../../tests/cloud/test_community_pc04_reads.py) 包含 47 项认证、所有权、关系完整性、父帖状态竞态、版本反馈与 DTO 最小化验证。保留全部 PC03 回归。

客户端仍使用 [PC03 原接口](PC03_API_CONTRACT.md) 完成投稿、评论、互动、举报和审核；公共 GET 不携带身份令牌。路径统一在 API 层附加 `/api/v2`。两个新增读取端点部署前，旧 API 仍可完成既有操作；新客户端对缺失端点显示读取未确认，不虚构已点赞或审核反馈。

真实函数更新需要 [PC04 独立云变更计划](PC04_CLOUD_CHANGE_PLAN.md) 的新授权。本地测试、打包和方案默认不访问云。
