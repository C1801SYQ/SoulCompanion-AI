'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { allowedRequest, createPreview } = require('./community_smoke.cjs');

async function main() {
  const origin = 'http://127.0.0.1:18405';
  const files = new Set(['/', '/index.html', '/assets/app.js', '/api/v2/posts']);
  assert.equal(allowedRequest(origin + '/', 'GET', origin, files), true);
  assert.equal(allowedRequest(origin + '/assets/app.js', 'HEAD', origin, files), true);
  for (const method of ['POST', 'PUT', 'PATCH', 'DELETE']) assert.equal(allowedRequest(origin + '/', method, origin, files), false);
  assert.equal(allowedRequest('https://example.invalid/assets/app.js', 'GET', origin, files), false);
  assert.equal(allowedRequest('http://test:secret@127.0.0.1:18405/', 'GET', origin, files), false);
  for (const pathname of ['/api/v2/posts', '/not-a-build-file', '/assets/app.js?token=synthetic', '/%2e%2e/secret', '/%00', '/%5csecret']) {
    assert.equal(allowedRequest(origin + pathname, 'GET', origin, files), false);
  }
  assert.equal(allowedRequest('not a url', 'GET', origin, files), false);

  const output = path.resolve(__dirname, '..', '.test-artifacts', 'community-harness-tests');
  fs.mkdirSync(output, { recursive: true });
  const fixture = fs.mkdtempSync(path.join(output, 'run-'));
  fs.writeFileSync(path.join(fixture, 'index.html'), '<!doctype html><title>Synthetic fixture</title>');
  fs.mkdirSync(path.join(fixture, 'assets'));
  fs.writeFileSync(path.join(fixture, 'assets', 'app.js'), '/* synthetic fixture */');
  let preview;
  try {
    preview = await createPreview(fixture);
    assert.equal((await fetch(preview.origin + '/')).status, 200);
    assert.equal((await fetch(preview.origin + '/assets/app.js')).headers.get('x-content-type-options'), 'nosniff');
    assert.equal((await fetch(preview.origin + '/api/v2/posts')).status, 404);
    assert.equal((await fetch(preview.origin + '/assets/app.js?credential=synthetic')).status, 404);
    assert.equal((await fetch(preview.origin + '/', { method: 'POST' })).status, 405);
    assert.equal((await fetch(preview.origin + '/outside.html')).status, 404);
    assert.equal((await fetch(preview.origin + '/', { method: 'HEAD' })).status, 200);
  } finally { if (preview) await preview.close(); }
  console.log('PC01 static harness: exact local build files, read-only methods, API/remote/query rejection and owned-server cleanup PASS');
}

main().catch(error => { console.error(error); process.exitCode = 1; });
