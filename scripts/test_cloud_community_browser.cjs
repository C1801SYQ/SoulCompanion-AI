/** No network: fixed-target write bounds and Python/Node deterministic-ID compatibility. */
'use strict';

const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const path = require('node:path');
const { deterministicId, SyntheticBoundary } = require('./cloud_community_browser.cjs');
const users = ['00000000-0000-4000-8000-000000000001', '00000000-0000-4000-8000-000000000002'];
let count = 0;
function test(name, operation) { operation(); count++; process.stdout.write(`PASS ${name}\n`); }
const post = { title: 'PC04 合成验收：晚饭后的聊天', body: 'PC04 合成验收内容：完全虚构，不含真实儿童、学校或家庭信息。', age_band: '6-8', topic: 'parent-child' };
const review = { expected_revision: 1, reason: 'PC04 合成验收：已检查全文与隐私边界。' };

test('Node deterministic ID matches production Python UUID5 vector', () => {
  assert.equal(deterministicId('post', users[0], 'stable-action'), 'd8942b6d-d196-5a53-aaab-4c13adfbf67d');
});
test('Reject missing, duplicate and malformed fixture identities', () => {
  for (const input of [[], [users[0]], [users[0], users[0]], ['not-a-uuid', users[1]], null]) assert.throws(() => new SyntheticBoundary(input));
});
test('Same post action replays one deterministic target; a second new post is blocked', () => {
  const guard = new SyntheticBoundary(users);
  assert.deepEqual(guard.attempt(0, 'POST', '/api/v2/community/posts', post, 'stable-action'), { kind: 'post', account: 0, key: 'stable-action', body: post });
  assert.doesNotThrow(() => guard.attempt(0, 'POST', '/api/v2/community/posts', post, 'stable-action'));
  assert.throws(() => guard.attempt(0, 'POST', '/api/v2/community/posts', post, 'second-action'));
});
test('Post writes refuse guest, second account, owner injection, real text and unsafe key', () => {
  for (const [account, body, key] of [[null, post, 'post'], [1, post, 'post'], [0, { ...post, owner_id: users[1] }, 'post'],
    [0, { ...post, body: 'Different or real text' }, 'post'], [0, post, 'unsafe key']]) {
    assert.throws(() => new SyntheticBoundary(users).attempt(account, 'POST', '/api/v2/community/posts', body, key));
  }
});
test('Only second synthetic user comments once on the acknowledged synthetic post', () => {
  const guard = new SyntheticBoundary(users); guard.attempt(0, 'POST', '/api/v2/community/posts', post, 'post');
  const url = `/api/v2/community/posts/${guard.post}/comments`, body = { body: 'PC04 合成验收评论：仅用于软件验证，无真实儿童信息。' };
  assert.throws(() => guard.attempt(0, 'POST', url, body, 'comment'));
  guard.attempt(1, 'POST', url, body, 'comment'); assert.doesNotThrow(() => guard.attempt(1, 'POST', url, body, 'comment'));
  assert.throws(() => guard.attempt(1, 'POST', url, body, 'second-comment'));
  assert.throws(() => guard.attempt(1, 'POST', `/api/v2/community/posts/${users[0]}/comments`, body, 'foreign-comment'));
});
test('Only synthetic post has second-user relations; foreign targets and forged body are denied', () => {
  const guard = new SyntheticBoundary(users); guard.attempt(0, 'POST', '/api/v2/community/posts', post, 'post');
  assert.equal(guard.attempt(1, 'PUT', `/api/v2/community/posts/${guard.post}/like`, null).target_id, guard.post);
  assert.throws(() => guard.attempt(0, 'PUT', `/api/v2/community/posts/${guard.post}/like`, null));
  assert.throws(() => guard.attempt(1, 'PUT', `/api/v2/community/posts/${users[0]}/bookmark`, null));
  assert.throws(() => guard.attempt(1, 'PUT', `/api/v2/community/posts/${guard.post}/bookmark`, { owner_id: users[0] }));
});
test('Report remains bounded to synthetic post and exact nonidentifying payload', () => {
  const guard = new SyntheticBoundary(users); guard.attempt(0, 'POST', '/api/v2/community/posts', post, 'post');
  const body = { target_type: 'post', target_id: guard.post, reason: 'privacy', detail: 'PC04 合成验收举报，不代表真实内容风险。' };
  assert.throws(() => guard.attempt(0, 'POST', '/api/v2/community/content-reports', body, 'report'));
  assert.throws(() => guard.attempt(1, 'POST', '/api/v2/community/content-reports', { ...body, target_id: users[0] }, 'report'));
  guard.attempt(1, 'POST', '/api/v2/community/content-reports', body, 'report');
  assert.equal(guard.report, deterministicId('content_report', users[1], `post:${guard.post}:1`));
});
test('Moderator cannot approve foreign content, wrong revision, reject or hide', () => {
  const guard = new SyntheticBoundary(users); guard.attempt(0, 'POST', '/api/v2/community/posts', post, 'post');
  assert.equal(guard.attempt(1, 'POST', `/api/v2/ops/moderation/posts/${guard.post}/approve`, review, 'approve'), null);
  for (const [url, body, account] of [[`/api/v2/ops/moderation/posts/${users[0]}/approve`, review, 1],
    [`/api/v2/ops/moderation/posts/${guard.post}/approve`, { ...review, expected_revision: 2 }, 1],
    [`/api/v2/ops/moderation/posts/${guard.post}/approve`, review, 0],
    [`/api/v2/ops/moderation/posts/${guard.post}/hide`, review, 1],
    ['/api/v2/ops/moderation/comments/null/approve', review, 1]]) assert.throws(() => guard.attempt(account, 'POST', url, body, 'review'));
});
test('No family, reports, media or role-grant HTTP route is admitted', () => {
  const guard = new SyntheticBoundary(users);
  for (const url of ['/api/v2/children', '/api/v2/sessions', '/api/v2/reports', '/api/v2/emotions', '/api/v2/ops/roles', '/api/v2/cloud/upload']) {
    assert.equal(guard.read(url), false); assert.throws(() => guard.attempt(1, 'POST', url, {}, 'action'));
  }
});
test('Nickname mutation only permits explicit synthetic public nicknames', () => {
  const guard = new SyntheticBoundary(users);
  assert.deepEqual(guard.attempt(0, 'PUT', '/api/v2/parent-profile', { nickname: 'PC04合成家长甲' }), { kind: 'nickname', account: 0 });
  assert.throws(() => guard.attempt(0, 'PUT', '/api/v2/parent-profile', { nickname: 'A real child name' }));
  assert.throws(() => guard.attempt(0, 'PUT', '/api/v2/parent-profile', { nickname: 'PC04合成家长甲', child_id: users[0] }));
});
test('Direct browser CLI is offline by default and needs independent authorization', () => {
  for (const [args, status, code] of [[[], 'plan', 0], [['--apply'], 'blocked', 1]]) {
    const result = spawnSync(process.execPath, [path.join(__dirname, 'cloud_community_browser.cjs'), ...args], { encoding: 'utf8', timeout: 10000 });
    assert.equal(result.status, code); const value = JSON.parse(result.stdout); assert.equal(value.status, status); assert.equal(value.real_calls, false);
  }
});
test('Credential-bearing protocol cannot start from an ordinary direct CLI invocation', () => {
  const result = spawnSync(process.execPath, [path.join(__dirname, 'cloud_community_browser.cjs'), '--apply', '--cloud-write-authorized'], { encoding: 'utf8', timeout: 10000 });
  assert.equal(result.status, 1); const value = JSON.parse(result.stdout);
  assert.equal(value.code, 'PRIVATE_PARENT_PIPE_REQUIRED'); assert.equal(value.real_calls, false);
});
process.stdout.write(`Official-SDK acceptance boundary checks: ${count} PASS (no real cloud calls)\n`);
