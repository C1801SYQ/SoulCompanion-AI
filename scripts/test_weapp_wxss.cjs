'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { inspectWxss, compilerFailure, compileWxssFiles, checkDirectory } = require('./check_weapp_wxss.cjs');

let checks = 0;
function check(name, test) { test(); checks += 1; }
function codes(css) { return inspectWxss(css).map((issue) => issue.code); }

check('bare child pseudo-class reproduces official compilation failure', () => {
  assert.deepEqual(codes('.sc-soft-note>:first-child{font-weight:600;margin-bottom:3rpx}'), ['bare-pseudo-selector']);
});
check('bare pseudo-class followed by class still fails', () => {
  assert.deepEqual(codes('@media(max-width:767px){.pc-shell .sc-page-header>:last-child.pc-action{width:100%}}'), ['bare-pseudo-selector']);
});
check('bare pseudo-class at branch start and descendant boundary fails', () => {
  assert.deepEqual(codes('.valid,:first-child,.x :last-child{color:red}'), ['bare-pseudo-selector', 'bare-pseudo-selector']);
});
check('qualified class and element pseudo-classes pass', () => {
  assert.deepEqual(codes('.sc-soft-note>text:first-child,.x>.pc-action:last-child,.x:focus-within{color:red}'), []);
});
check('exact root selector and custom properties pass', () => {
  assert.deepEqual(codes(':root,page{--accent:red}.x{color:var(--accent)}'), []);
  assert.deepEqual(codes(':root:focus{color:red}'), ['bare-pseudo-selector']);
});
check('actual history rule and ordinary CSS functions are preserved', () => {
  assert.deepEqual(codes('.sc-history-cause{display:block;font-size:14rpx;line-height:1.8;margin-top:7rpx;overflow-wrap:anywhere}.x{width:clamp(1px,2vw,4px);padding:calc(1px + env(safe-area-inset-bottom));grid-template-columns:repeat(2,minmax(0,1fr))}'), []);
});
check('media queries and reduced motion do not imply incompatibility', () => {
  assert.deepEqual(codes('@media(prefers-reduced-motion:reduce){.x{animation:none}}@media(max-width:767px){.x>.y:last-child{width:100%}}'), []);
});
check('quotes and functional arguments are not selector boundaries', () => {
  assert.deepEqual(codes('.x[data-label=" > :first-child, *"]:not(.qualified:hover,.other){color:red}.x:is(.a,.b){color:blue}'), []);
});
check('attribute operators and escaped punctuation are not universal selectors', () => {
  assert.deepEqual(codes('.x[data-label*="*"] .escaped\\:name,.escaped\\*name,.escaped\\3a name{color:red}'), []);
});
check('comments cannot conceal an unsupported selector', () => {
  assert.deepEqual(codes('.x/**/>/**/:first-child{color:red}'), ['bare-pseudo-selector']);
  assert.deepEqual(codes('/* comment */:root{--color:red}.x/**/:first-child{color:red}'), []);
});
check('generated universal selectors are rejected after source transformation', () => {
  assert.deepEqual(codes('*{color:red}.x *::before{color:red}'), ['universal-selector', 'universal-selector']);
});
check('raw nesting fails while flat media and keyframes pass', () => {
  assert.ok(codes('.parent{.child{color:red}}').includes('nested-css'));
  assert.ok(codes('.parent{@media(max-width:2px){color:red}}').includes('nested-css'));
  assert.deepEqual(codes('@keyframes pulse{from{opacity:0}to{opacity:1}}'), []);
});
check('malformed CSS fails closed', () => {
  assert.deepEqual(codes('.x{color:red'), ['malformed-css']);
});
check('locations refer to the failing selector token', () => {
  const [issue] = inspectWxss('\n.x>\n:first-child{color:red}', 'app-origin.wxss');
  assert.equal(issue.file, 'app-origin.wxss');
  assert.equal(issue.line, 3);
  assert.equal(issue.column, 1);
});
check('official ERR output fails even when exit status is zero', () => {
  assert.match(compilerFailure({ status: 0, stdout: '', stderr: 'ERR: app-origin.wxss(1:10961): error at token `:`' }), /ERR:/);
  assert.match(compilerFailure({ status: 0, stdout: 'ERR: invalid file', stderr: '' }), /ERR:/);
});
check('compiler failures, signals and successful outputs have honest status', () => {
  assert.match(compilerFailure({ error: { code: 'ENOENT' } }), /ENOENT/);
  assert.match(compilerFailure({ status: 1 }), /status 1/);
  assert.match(compilerFailure({ status: null, signal: 'SIGTERM' }), /SIGTERM/);
  assert.match(compilerFailure({ status: null }), /unknown/);
  assert.equal(compilerFailure({ status: 0, stdout: '/* successful compilation */', stderr: '' }), null);
});
check('official invocation includes the complete input set and generated cwd', () => {
  let called = false;
  const failure = compileWxssFiles('compiler path.exe', ['app.wxss', 'app-origin.wxss', 'vendors.wxss', 'pages/community/index.wxss'], 'generated path', 'output path.js', (executable, args, options) => {
    called = true;
    assert.equal(executable, 'compiler path.exe');
    assert.deepEqual(args, ['-lc', '-o', 'output path.js', 'app.wxss', 'app-origin.wxss', 'vendors.wxss', 'pages/community/index.wxss']);
    assert.equal(options.cwd, 'generated path');
    assert.equal(options.shell, false);
    return { status: 0, stdout: '', stderr: '' };
  });
  assert.ok(called);
  assert.equal(failure, null);
});

const artifactBase = path.resolve(__dirname, '../.test-artifacts');
fs.mkdirSync(artifactBase, { recursive: true });
const temporary = fs.mkdtempSync(path.join(artifactBase, 'wxss-guard-tests-'));
const pageDirectory = path.join(temporary, 'pages');
try {
  check('missing generated directory and empty output fail', () => {
    assert.equal(checkDirectory(path.join(temporary, 'missing')).issues[0].code, 'missing-directory');
    assert.equal(checkDirectory(temporary).issues[0].code, 'missing-wxss');
  });
  fs.mkdirSync(pageDirectory);
  fs.writeFileSync(path.join(temporary, 'app.wxss'), '@import "./pages/page.wxss";\n:root{--color:red}', 'utf8');
  fs.writeFileSync(path.join(pageDirectory, 'page.wxss'), '.page>text:first-child{color:var(--color)}', 'utf8');
  check('all recursive generated files are checked without cloud calls', () => {
    const result = checkDirectory(temporary);
    assert.equal(result.files.length, 2);
    assert.deepEqual(result.issues, []);
    assert.equal(result.officialCompiler, false);
  });
  check('official batch contains entry styles and imported dependencies', () => {
    const requested = [];
    const result = checkDirectory(temporary, { compilerPath: 'compiler.exe', outputDirectory: path.join(temporary, 'outputs'), runner: (_executable, args, options) => {
      assert.equal(options.cwd, temporary);
      requested.push(args.slice(3));
      return { status: 0, stderr: '' };
    } });
    assert.deepEqual(requested, [['app.wxss', 'pages/page.wxss']]);
    assert.equal(result.officialCompiler, true);
    assert.deepEqual(result.issues, []);
  });
  check('official batch error fails even if all files are present and exit is zero', () => {
    const result = checkDirectory(temporary, { compilerPath: 'compiler.exe', outputDirectory: path.join(temporary, 'outputs'), runner: (_executable, args) => {
      assert.deepEqual(args.slice(3), ['app.wxss', 'pages/page.wxss']);
      return { status: 0, stderr: 'ERR: simulated compiler failure' };
    } });
    assert.equal(result.issues.length, 1);
    assert.equal(result.issues[0].code, 'official-compiler');
  });
  check('configured but missing compiler is a failure, not a skip', () => {
    const result = checkDirectory(temporary, { compilerPath: path.join(temporary, 'missing-compiler.exe'), outputDirectory: path.join(temporary, 'outputs') });
    assert.equal(result.issues.length, 1);
    assert.ok(result.issues.every((issue) => issue.code === 'official-compiler' && /ENOENT/.test(issue.message)));
  });
} finally {
  // Only remove the exact test files/directories created above, without a
  // recursive delete or a path derived from compiler output.
  fs.rmSync(path.join(temporary, 'app.wxss'), { force: true });
  fs.rmSync(path.join(pageDirectory, 'page.wxss'), { force: true });
  if (fs.existsSync(pageDirectory)) fs.rmdirSync(pageDirectory);
  if (fs.existsSync(path.join(temporary, 'outputs'))) fs.rmdirSync(path.join(temporary, 'outputs'));
  fs.rmdirSync(temporary);
}

console.log(`WXSS guard tests: ${checks} passed (selector boundaries, generated CSS, missing outputs and official compiler failures).`);
