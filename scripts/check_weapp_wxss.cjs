'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { createRequire } = require('node:module');
const { spawnSync } = require('node:child_process');

const repositoryRoot = path.resolve(__dirname, '..');
const clientRequire = createRequire(path.join(repositoryRoot, 'apps/client/package.json'));
const postcss = clientRequire('postcss');

// Check compound boundaries without interpreting strings, attribute values or
// functional pseudo-class arguments as top-level selector tokens.
function unsupportedSelectorTokens(selector) {
  const issues = [];
  let branchStart = 0;
  let expectsQualifier = true;
  let quote = null;
  let brackets = 0;
  let parentheses = 0;

  function branchEnd(start) {
    let depth = 0;
    let bracketDepth = 0;
    let stringQuote = null;
    for (let index = start; index < selector.length; index += 1) {
      const character = selector[index];
      if (character === '\\') { index += 1; continue; }
      if (stringQuote) { if (character === stringQuote) stringQuote = null; continue; }
      if (character === '"' || character === "'") { stringQuote = character; continue; }
      if (character === '/' && selector[index + 1] === '*') {
        const end = selector.indexOf('*/', index + 2);
        index = end === -1 ? selector.length : end + 1;
        continue;
      }
      if (character === '[') bracketDepth += 1;
      if (character === ']') bracketDepth -= 1;
      if (bracketDepth) continue;
      if (character === '(') depth += 1;
      if (character === ')') depth -= 1;
      if (character === ',' && depth === 0) return index;
    }
    return selector.length;
  }

  for (let index = 0; index < selector.length; index += 1) {
    const character = selector[index];
    if (character === '\\') {
      // A CSS escape can consume up to six hex digits and a trailing space.
      const escapedHex = selector.slice(index + 1).match(/^[0-9a-fA-F]{1,6}(?:\s)?/);
      index += escapedHex ? escapedHex[0].length : 1;
      if (!quote && !brackets && !parentheses) expectsQualifier = false;
      continue;
    }
    if (quote) { if (character === quote) quote = null; continue; }
    if (character === '"' || character === "'") { quote = character; continue; }
    if (character === '/' && selector[index + 1] === '*') {
      const end = selector.indexOf('*/', index + 2);
      index = end === -1 ? selector.length : end + 1;
      continue;
    }
    if (character === '[') { brackets += 1; expectsQualifier = false; continue; }
    if (character === ']') { brackets -= 1; continue; }
    if (brackets) continue;
    if (character === '(') { parentheses += 1; continue; }
    if (character === ')') { parentheses -= 1; continue; }
    if (parentheses) continue;
    if (character === ',') { branchStart = index + 1; expectsQualifier = true; continue; }
    if (/\s/.test(character) || character === '>' || character === '+' || character === '~') {
      expectsQualifier = true;
      continue;
    }
    if (character === ':' && expectsQualifier) {
      const branch = selector.slice(branchStart, branchEnd(branchStart)).replace(/\/\*[\s\S]*?\*\//g, '').trim();
      // The installed official compiler accepts the exact :root selector.
      if (branch !== ':root') issues.push({ code: 'bare-pseudo-selector', index });
    }
    if (character === '*') issues.push({ code: 'universal-selector', index });
    expectsQualifier = false;
  }
  return issues;
}

function inspectWxss(css, filename = '<wxss>') {
  const issues = [];
  let ast;
  try {
    ast = postcss.parse(css, { from: filename });
  } catch (error) {
    return [{ code: 'malformed-css', file: filename, line: error.line, column: error.column, message: error.reason }];
  }
  ast.walk((node) => {
    if (node.type !== 'rule' && node.type !== 'atrule') return;
    for (let ancestor = node.parent; ancestor; ancestor = ancestor.parent) {
      if (ancestor.type === 'rule') {
        issues.push({ code: 'nested-css', file: filename, line: node.source.start.line, column: node.source.start.column, message: 'Uncompiled CSS nesting is not valid WXSS.' });
        return;
      }
    }
    if (node.type !== 'rule') return;
    for (const issue of unsupportedSelectorTokens(node.selector)) {
      const prefix = node.selector.slice(0, issue.index);
      const lines = prefix.split('\n');
      issues.push({
        code: issue.code,
        file: filename,
        line: node.source.start.line + lines.length - 1,
        column: lines.length === 1 ? node.source.start.column + prefix.length : lines.at(-1).length + 1,
        selector: node.selector,
        message: issue.code === 'bare-pseudo-selector'
          ? 'Qualify the pseudo-class with a class or element selector; bare compound pseudo-classes fail the official WXSS compiler.'
          : 'Generated universal selectors fail the official WXSS compiler.',
      });
    }
  });
  return issues;
}

function compilerFailure(result) {
  if (result.error) return `Compiler could not run: ${result.error.code || result.error.message}`;
  if (result.signal) return `Compiler was terminated: ${result.signal}`;
  const output = `${result.stdout || ''}\n${result.stderr || ''}`;
  const errorLine = output.split(/\r?\n/).find((line) => /\bERR(?:OR)?\s*:|error at token|unexpected token/i.test(line));
  if (errorLine) return errorLine.trim().slice(0, 300);
  if (result.status !== 0) return `Compiler exited with status ${result.status ?? 'unknown'}.`;
  return null;
}

function compileWxssFiles(compilerPath, relativeFiles, directory, outputFile, runner = spawnSync) {
  // wcsc resolves @import references from its input file set. Its working
  // directory alone does not make otherwise omitted imported files available.
  const result = runner(compilerPath, ['-lc', '-o', outputFile, ...relativeFiles], {
    cwd: directory,
    encoding: 'utf8',
    shell: false,
    windowsHide: true,
    timeout: 30000,
    maxBuffer: 4 * 1024 * 1024,
  });
  return compilerFailure(result);
}

function findWxssFiles(directory) {
  const files = [];
  function visit(current) {
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const absolute = path.join(current, entry.name);
      if (entry.isDirectory()) visit(absolute);
      else if (entry.isFile() && entry.name.endsWith('.wxss')) files.push(path.relative(directory, absolute).split(path.sep).join('/'));
    }
  }
  visit(directory);
  return files.sort();
}

function checkDirectory(directory, options = {}) {
  let files;
  try {
    files = findWxssFiles(directory);
  } catch (error) {
    return { files: [], issues: [{ code: 'missing-directory', file: directory, message: `Cannot read generated WXSS: ${error.code || error.message}` }], officialCompiler: false };
  }
  if (!files.length) return { files, issues: [{ code: 'missing-wxss', file: directory, message: 'No generated WXSS files were found.' }], officialCompiler: false };
  const issues = files.flatMap((file) => inspectWxss(fs.readFileSync(path.join(directory, file), 'utf8'), file));
  let officialCompiler = false;
  if (options.compilerPath && !issues.length) {
    const outputDirectory = options.outputDirectory || path.join(repositoryRoot, '.test-artifacts/weapp-wxss-check');
    fs.mkdirSync(outputDirectory, { recursive: true });
    officialCompiler = true;
    const failure = compileWxssFiles(options.compilerPath, files, directory, path.join(outputDirectory, 'compiled-batch.js'), options.runner);
    if (failure) issues.push({ code: 'official-compiler', file: '<generated WXSS batch>', message: failure });
  }
  return { files, issues, officialCompiler };
}

function main() {
  const args = process.argv.slice(2);
  if (args.length && (args.length !== 2 || args[0] !== '--dir')) throw new Error('Usage: node scripts/check_weapp_wxss.cjs [--dir generated-directory]');
  const directory = args.length ? path.resolve(args[1]) : path.join(repositoryRoot, 'apps/client/dist-weapp');
  const result = checkDirectory(directory, { compilerPath: process.env.WECHAT_WXSS_COMPILER });
  if (result.issues.length) {
    for (const issue of result.issues) console.error(`${issue.file}${issue.line ? `:${issue.line}:${issue.column}` : ''} [${issue.code}] ${issue.message}${issue.selector ? ` Selector: ${issue.selector.slice(0, 160)}` : ''}`);
    process.exitCode = 1;
    return;
  }
  console.log(`WXSS regression checks: ${result.files.length} generated files passed. Official compiler: ${result.officialCompiler ? 'PASS (syntax compilation only)' : 'NOT RUN (set WECHAT_WXSS_COMPILER to enable)'}.`);
}

module.exports = { unsupportedSelectorTokens, inspectWxss, compilerFailure, compileWxssFiles, checkDirectory };
if (require.main === module) {
  try { main(); } catch (error) { console.error(`WXSS regression check failed: ${error.code || error.message}`); process.exitCode = 1; }
}
