'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { createHash } = require('node:crypto');

const reviewedLock = '944cbb7574d130e3e23573ccb816b718f3a824f887b655fa9a12fcb567867d97';

// Reviewed exceptions apply to the locked build tools, not to public input handling.
// Rationale and limits: docs/v2/02-cross-platform-ui.md. New advisories fail closed.
const approved = new Set([
  'GHSA-vfj7-8cjw-p6xm', 'GHSA-ch52-4w7c-c8xp', 'GHSA-vcc3-ghjq-m6fr',
  'GHSA-mp2f-45pm-3cg9', 'GHSA-h39j-r5qq-r9mm', 'GHSA-jwp9-9v96-94mx',
  'GHSA-hrh2-vp3x-79xf', 'GHSA-8jmw-wjr8-2x66', 'GHSA-pfrx-2q88-qq97',
  'GHSA-pfq8-rq6v-vf5m',
]);
const packages = new Set([
  '@tarojs/cli', '@tarojs/components', '@tarojs/components-react', '@tarojs/helper',
  '@tarojs/plugin-framework-react', '@tarojs/plugin-platform-h5', '@tarojs/plugin-platform-weapp',
  '@tarojs/router', '@tarojs/runner-utils', '@tarojs/service', '@tarojs/taro',
  '@tarojs/taro-h5', '@tarojs/vite-runner', 'babel-preset-taro', 'braces',
  'cacheable-request', 'chokidar', 'decode-uri-component', 'decompress', 'download',
  'download-git-repo', 'fast-glob', 'find-yarn-workspace-root', 'git-clone', 'globby',
  'got', 'html-minifier', 'http-cache-semantics', 'latest-version', 'micromatch',
  'normalize-url', 'package-json', 'query-string', 'scss-bundle', 'stylelint',
  'vite-plugin-static-copy',
]);

function assessAudit(report, lockPackages = require('../apps/client/package-lock.json').packages) {
  if (!report || report.error || report.auditReportVersion !== 2
      || !report.vulnerabilities || typeof report.vulnerabilities !== 'object'
      || !Number.isInteger(report.metadata?.vulnerabilities?.total)) {
    throw new Error('Dependency audit is unavailable or malformed');
  }
  const entries = Object.entries(report.vulnerabilities);
  if (report.metadata.vulnerabilities.total !== entries.length) {
    throw new Error('Dependency audit totals are inconsistent');
  }
  const advisories = new Set();
  const reachable = new Set();
  for (const [name, item] of entries) {
    if (!packages.has(name) || !item || item.name !== name
        || !Array.isArray(item.via) || item.via.length === 0) {
      throw new Error(`Unreviewed dependency path: ${name}`);
    }
    if (!Array.isArray(item.nodes) || !item.nodes.length || item.nodes.some(node =>
      typeof node !== 'string' || !Object.hasOwn(lockPackages, node)
      || node.slice(node.lastIndexOf('node_modules/') + 'node_modules/'.length) !== name)) {
      throw new Error(`Unreviewed installation path: ${name}`);
    }
    for (const cause of item.via) {
      if (typeof cause === 'string') {
        if (!Object.hasOwn(report.vulnerabilities, cause)) {
          throw new Error('Dependency audit contains an unresolved advisory chain');
        }
        continue;
      }
      const match = typeof cause?.url === 'string'
        && /^https:\/\/github\.com\/advisories\/(GHSA-[a-z0-9-]+)$/.exec(cause.url);
      if (!match || !approved.has(match[1])) {
        throw new Error(`Unreviewed advisory in ${name}`);
      }
      advisories.add(match[1]);
      reachable.add(name);
    }
  }
  // Fixed-point reachability allows real dependency cycles with a reviewed leaf,
  // but rejects isolated cycles without exponential recursive graph traversal.
  for (let changed = true; changed;) {
    changed = false;
    for (const [name, item] of entries) {
      if (!reachable.has(name) && item.via.some(cause => typeof cause === 'string' && reachable.has(cause))) {
        reachable.add(name); changed = true;
      }
    }
  }
  if (reachable.size !== entries.length) throw new Error('Dependency audit has a chain without approved advisory evidence');
  return { findings: entries.length, advisories: [...advisories].sort(), counts: report.metadata.vulnerabilities };
}

function run() {
  const root = path.resolve(__dirname, '..');
  const output = path.join(root, '.test-artifacts');
  fs.mkdirSync(output, { recursive: true });
  const rawPath = path.join(output, 'client-dependency-audit.json');
  const policyPath = path.join(output, 'client-dependency-policy.json');
  const startedAt = new Date().toISOString();
  fs.writeFileSync(rawPath, JSON.stringify({ status: 'not_completed', started_at: startedAt }) + '\n');
  fs.writeFileSync(policyPath, JSON.stringify({ status: 'running', started_at: startedAt }) + '\n');
  try {
  const lock = fs.readFileSync(path.join(root, 'apps/client/package-lock.json'), 'utf8').replace(/\r\n/g, '\n');
  if (createHash('sha256').update(lock).digest('hex') !== reviewedLock) {
    throw new Error('Client lockfile changed; re-review the advisory exceptions before updating their fingerprint');
  }
  const cli = process.env.npm_execpath;
  if (!cli || path.basename(cli) !== 'npm-cli.js') throw new Error('Run this check with npm run client:audit');
  const result = spawnSync(process.execPath, [cli, 'audit', '--json', '--fetch-retries=0',
    '--fetch-timeout=15000', '--cache', path.join(output, 'npm-client-cache')], {
    cwd: path.join(root, 'apps/client'), encoding: 'utf8', timeout: 25000, maxBuffer: 5_000_000,
  });
  if (result.error || ![0, 1].includes(result.status)) throw new Error('Dependency audit could not complete');
  let report;
  try { report = JSON.parse(result.stdout); } catch { throw new Error('Dependency audit returned unreadable data'); }
  fs.writeFileSync(rawPath, JSON.stringify(report, null, 2) + '\n');
  const reviewed = assessAudit(report);
  fs.writeFileSync(policyPath, JSON.stringify({ status: 'known_exceptions_accepted', started_at: startedAt,
    finished_at: new Date().toISOString(), reviewed_lock_sha256: reviewedLock, ...reviewed }, null, 2) + '\n');
  console.log(`Dependency policy passed: ${reviewed.findings} known findings retained; ${reviewed.advisories.length} reviewed toolchain advisories. This does not mean npm audit is clean.`);
  } catch (error) {
    fs.writeFileSync(policyPath, JSON.stringify({ status: 'failed', started_at: startedAt,
      finished_at: new Date().toISOString(), reason: error.message }, null, 2) + '\n');
    throw error;
  }
}

module.exports = { assessAudit };
if (require.main === module) {
  try { run(); } catch (error) { console.error(error.message); process.exitCode = 1; }
}
