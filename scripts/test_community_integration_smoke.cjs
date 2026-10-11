'use strict';
const assert = require('node:assert/strict');
const { allowedApi, allowedRequest } = require('./community_integration_smoke.cjs');

const origin = 'http://127.0.0.1:18405';
const api = 'http://127.0.0.1:18406';
const id = '027fe5b4-a04b-427d-b057-509f1bda97b8';
const files = new Set(['/', '/index.html', '/assets/app.js']);
for (const route of ['/api/v2/community/posts', `/api/v2/community/posts/${id}/comments`, '/api/v2/me/community/bookmarks', `/api/v2/me/community/posts/${id}/relations`, '/api/v2/ops/moderation']) {
  assert.equal(allowedApi('GET', route), true);
  assert.equal(allowedRequest(api + route, 'GET', origin, api, files), true);
}
assert.equal(allowedApi('POST', `/api/v2/ops/moderation/posts/${id}/approve`), true);
assert.equal(allowedApi('OPTIONS', `/api/v2/community/posts/${id}/like`), true);
for (const route of ['/api/v2/me', '/api/v2/children', '/api/v2/sessions', '/api/v2/emotions', '/api/v2/reports/current', '/api/v2/ops/roles/grant', '/api/v2/cloud-admin', '/api/v2/community/uploads']) {
  for (const method of ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS']) assert.equal(allowedApi(method, route), false);
}
assert.equal(allowedRequest(origin + '/assets/app.js', 'GET', origin, api, files), true);
for (const url of ['https://example.invalid/assets/app.js', origin + '/assets/app.js?token=x', origin + '/api/v2/community/posts', origin + '/%5csecret', 'http://user:password@127.0.0.1:18406/api/v2/community/posts']) {
  assert.equal(allowedRequest(url, 'GET', origin, api, files), false);
}
assert.equal(allowedRequest(origin + '/', 'POST', origin, api, files), false);
assert.equal(allowedRequest('invalid URL', 'GET', origin, api, files), false);
console.log('PC04 integration harness network boundaries PASS');
