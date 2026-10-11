'use strict';

const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');

// Conservative project budgets: count every emitted file, including metadata.
const BUDGET = { main: 2 * 1024 * 1024, subpackage: 2 * 1024 * 1024, total: 20 * 1024 * 1024 };
function measureBundle(directory) {
  const root = fs.realpathSync(directory);
  const config = JSON.parse(fs.readFileSync(path.join(root, 'app.json'), 'utf8'));
  const packages = config.subPackages ?? config.subpackages ?? [];
  assert.ok(Array.isArray(packages), 'Invalid subpackage manifest');
  const roots = packages.map(entry => {
    assert.ok(typeof entry.root === 'string' && /^[A-Za-z0-9_-]+(?:\/[A-Za-z0-9_-]+)*$/.test(entry.root), 'Unsafe subpackage root');
    assert.ok(entry.independent !== true, 'Shared identity requires ordinary subpackages');
    return entry.root + '/';
  });
  assert.equal(new Set(roots).size, roots.length, 'Duplicate subpackage roots');
  assert.ok(roots.every(a => !roots.some(b => a !== b && a.startsWith(b))), 'Overlapping subpackage roots');
  const files = [];
  function visit(folder) {
    for (const entry of fs.readdirSync(folder, { withFileTypes: true })) {
      assert.ok(!entry.isSymbolicLink(), 'Bundle must not contain symlinks');
      const absolute = path.join(folder, entry.name);
      if (entry.isDirectory()) visit(absolute);
      else if (entry.isFile()) files.push({ path: path.relative(root, absolute).split(path.sep).join('/'), bytes: fs.statSync(absolute).size });
    }
  }
  visit(root);
  const subpackages = roots.map(packageRoot => ({ root: packageRoot.slice(0, -1), bytes: files.filter(file => file.path.startsWith(packageRoot)).reduce((sum, file) => sum + file.bytes, 0) }));
  const totalBytes = files.reduce((sum, file) => sum + file.bytes, 0);
  const mainBytes = totalBytes - subpackages.reduce((sum, item) => sum + item.bytes, 0);
  return { fileCount: files.length, mainBytes, totalBytes, subpackages, lazyCodeLoading: config.lazyCodeLoading ?? null,
    largestFiles: files.sort((a, b) => b.bytes - a.bytes).slice(0, 8), budgets: BUDGET };
}
function checkBundle(result) {
  assert.ok(result.mainBytes <= BUDGET.main, 'Main package exceeds project budget');
  assert.ok(result.totalBytes <= BUDGET.total, 'Total package exceeds project budget');
  assert.ok(result.subpackages.every(item => item.bytes <= BUDGET.subpackage), 'Subpackage exceeds project budget');
  assert.equal(result.lazyCodeLoading, 'requiredComponents', 'Component injection configuration regressed');
}
if (require.main === module) {
  const result = measureBundle(path.resolve(__dirname, '../apps/client/dist-weapp'));
  checkBundle(result);
  const evidence = path.resolve(__dirname, '../.test-artifacts/pc04-weapp-bundle.json');
  fs.mkdirSync(path.dirname(evidence), { recursive: true });
  fs.writeFileSync(evidence, JSON.stringify(result, null, 2));
  console.log(`WeChat package budget PASS: main ${result.mainBytes} / total ${result.totalBytes} bytes; ${result.subpackages.length} ordinary subpackages.`);
}
module.exports = { measureBundle, checkBundle, BUDGET };
