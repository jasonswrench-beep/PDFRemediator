'use strict';

// End-to-end check of the real page against the real service, driven through the DevTools protocol of a headless Edge/Chrome with
// its own scratch profile. Nothing is installed, no window appears on the screen, no file of yours is changed: the service runs from
// this work copy on a scratch data folder, PDFs are copied there by the page's own upload, and everything is deleted afterwards.
//
// Needs Node.js 22+ (built-in WebSocket) and these environment variables (the test in tests/test_e2e_browser.py skips without them):
//   PDFR_E2E_PYTHON     a Python that can run `python -m pdf_remediator serve` with this work copy's src on PYTHONPATH
//   PDFR_E2E_CONFIG     a local-runtime.toml that points at Java, OpenDataLoader and veraPDF (OCR may stay off)
//   PDFR_E2E_SHORT_PDF  a PDF that finishes in a few seconds
//   PDFR_E2E_LONG_PDF   optional: a PDF that takes a minute or more (shows the status bar, both Cancel buttons and Auto-fix)
//   PDFR_E2E_EDGE       optional: path of msedge.exe or chrome.exe
//   PDFR_E2E_ROOT       optional: another folder that holds src/ and is where the service runs (a built payload, to test the packaged Python)
const {spawn, spawnSync} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const env = process.env;
// PDFR_E2E_ROOT: run the service from another folder that holds src/ (for example a built payload, to test the packaged runtime)
const root = env.PDFR_E2E_ROOT ? path.resolve(env.PDFR_E2E_ROOT) : path.resolve(__dirname, '..');
for (const name of ['PDFR_E2E_PYTHON', 'PDFR_E2E_CONFIG', 'PDFR_E2E_SHORT_PDF']) {
  if (!env[name]) { console.error('Missing environment variable ' + name); process.exit(2); }
}
const SHORT = path.resolve(env.PDFR_E2E_SHORT_PDF), LONG = env.PDFR_E2E_LONG_PDF ? path.resolve(env.PDFR_E2E_LONG_PDF) : null;
const edgeCandidates = [env.PDFR_E2E_EDGE, 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe', 'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe'].filter(Boolean);
const EDGE = edgeCandidates.find(candidate => fs.existsSync(candidate));
if (!EDGE) { console.error('No Edge or Chrome found'); process.exit(2); }

const work = fs.mkdtempSync(path.join(os.tmpdir(), 'pdfr-e2e-'));
const dataDir = path.join(work, 'data'), profile = path.join(work, 'edge-profile'), sessionFile = path.join(work, 'session.json');
fs.mkdirSync(dataDir); fs.mkdirSync(profile);

const results = [];
const problems = [];
function record(step, ok, detail = '') {
  results.push({step, ok, detail});
  console.log((ok ? 'PASS ' : 'FAIL ') + step + (detail ? '  -- ' + detail : ''));
}
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

class Cdp {
  constructor(url) { this.url = url; this.id = 0; this.pending = new Map(); this.handlers = new Map(); }
  open() {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.url);
      this.ws.addEventListener('open', () => resolve());
      this.ws.addEventListener('error', () => reject(new Error('DevTools socket error')));
      this.ws.addEventListener('message', event => this.onMessage(typeof event.data === 'string' ? event.data : event.data.toString()));
    });
  }
  onMessage(text) {
    const message = JSON.parse(text);
    if (message.id !== undefined) {
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message)); else pending.resolve(message.result);
    } else for (const handler of this.handlers.get(message.method) || []) handler(message.params);
  }
  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({id, method, params}));
    return new Promise((resolve, reject) => this.pending.set(id, {resolve, reject}));
  }
  on(method, handler) { this.handlers.set(method, [...(this.handlers.get(method) || []), handler]); }
}

let cdp = null, service = null, browser = null;
async function ev(expression) {
  const answer = await cdp.send('Runtime.evaluate', {expression, returnByValue: true, awaitPromise: true});
  if (answer.exceptionDetails) throw new Error('page script failed: ' + (answer.exceptionDetails.exception?.description || answer.exceptionDetails.text));
  return answer.result.value;
}
async function waitFor(expression, timeoutMs, label) {
  const deadline = Date.now() + timeoutMs;
  let last;
  while (Date.now() < deadline) {
    try { last = await ev(expression); if (last) return last; } catch (error) { last = error.message; }
    await sleep(200);
  }
  throw new Error('timed out after ' + Math.round(timeoutMs / 1000) + ' s waiting for ' + label + (last ? ' (last: ' + JSON.stringify(last) + ')' : ''));
}
const text = id => ev(`(document.getElementById(${JSON.stringify(id)}) || {}).textContent`);
const hidden = id => ev(`document.getElementById(${JSON.stringify(id)}).hidden`);
const click = id => ev(`document.getElementById(${JSON.stringify(id)}).click(), true`);

async function choose(...files) {
  const document = await cdp.send('DOM.getDocument', {depth: 0});
  const input = await cdp.send('DOM.querySelector', {nodeId: document.root.nodeId, selector: '#files'});
  await cdp.send('DOM.setFileInputFiles', {nodeId: input.nodeId, files});
  await waitFor(`document.getElementById('selected-files').children.length === ${files.length}`, 5000, 'the chosen files to be listed');
}
let expectNetworkErrors = false;
async function watchBars() {
  await ev(`(function () {
    window.__seen = {bar: false, barSteps: [], barClocks: 0, barLabel: '', barBottomGap: null, barGapScrolled: null, auto: false, autoSteps: [], autoClocks: 0};
    var lastBarClock = '', lastAutoClock = '';
    function tick() {
      var bar = document.getElementById('job-bar'), auto = document.getElementById('auto-status'), s = window.__seen;
      if (!bar.hidden) {
        s.bar = true; s.barLabel = document.getElementById('job-label').textContent;
        var step = document.getElementById('job-step').textContent; if (step && s.barSteps.indexOf(step) < 0) s.barSteps.push(step);
        var clock = document.getElementById('job-clock').textContent; if (clock !== lastBarClock) { lastBarClock = clock; s.barClocks++; }
        if (s.barBottomGap === null) s.barBottomGap = Math.round(innerHeight - bar.getBoundingClientRect().bottom);
      }
      if (!auto.hidden) {
        s.auto = true;
        var a = document.getElementById('auto-step').textContent; if (a && s.autoSteps.indexOf(a) < 0) s.autoSteps.push(a);
        var c = document.getElementById('auto-clock').textContent; if (c !== lastAutoClock) { lastAutoClock = c; s.autoClocks++; }
      }
    }
    if (window.__seenTimer) clearInterval(window.__seenTimer);
    window.__seenTimer = setInterval(tick, 100);
  })()`);
}
const seen = () => ev('JSON.parse(JSON.stringify(window.__seen))');

// What a screen reader is given: every control that can be used must have a name; ids must be unique; the page needs a language,
// a title, one main area and one visible top heading; no positive tabindex.
async function accessibilityAudit() {
  const tree = await cdp.send('Accessibility.getFullAXTree');
  const controls = new Set(['button', 'link', 'textbox', 'combobox', 'checkbox', 'radio', 'switch', 'tab', 'searchbox', 'spinbutton', 'slider', 'menuitem', 'listbox']);
  const unnamed = tree.nodes.filter(node => !node.ignored && node.role && controls.has(node.role.value) && !(node.name && node.name.value && String(node.name.value).trim()));
  const described = [];
  for (const node of unnamed.slice(0, 8)) {
    try { const info = await cdp.send('DOM.describeNode', {backendNodeId: node.backendDOMNodeId}); const attrs = info.node.attributes || []; described.push(info.node.nodeName.toLowerCase() + '#' + (attrs[attrs.indexOf('id') + 1] || '?')); }
    catch (error) { described.push('(unknown ' + node.role.value + ')'); }
  }
  const page = await ev(`(function () {
    var ids = Array.from(document.querySelectorAll('[id]')).map(function (e) { return e.id; });
    var duplicates = ids.filter(function (id, i) { return ids.indexOf(id) !== i; });
    var visible = function (e) { return !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length); };
    var headings = Array.from(document.querySelectorAll('h1')).filter(visible).length;
    var noAlt = Array.from(document.querySelectorAll('img')).filter(function (e) { return !e.hasAttribute('alt'); }).map(function (e) { return e.src.slice(-30); });
    var positive = Array.from(document.querySelectorAll('[tabindex]')).filter(function (e) { return Number(e.getAttribute('tabindex')) > 0; }).length;
    return {lang: document.documentElement.lang, title: document.title, main: document.querySelectorAll('main').length, visibleH1: headings, duplicates: duplicates, noAlt: noAlt, positiveTabindex: positive};
  })()`);
  const faults = [];
  if (unnamed.length) faults.push(unnamed.length + ' control(s) with no accessible name: ' + described.join(', '));
  if (!page.lang) faults.push('no page language');
  if (!page.title) faults.push('no page title');
  if (page.main !== 1) faults.push(page.main + ' main areas');
  if (page.visibleH1 !== 1) faults.push(page.visibleH1 + ' visible top-level headings');
  if (page.duplicates.length) faults.push('duplicate ids: ' + page.duplicates.slice(0, 5).join(', '));
  if (page.noAlt.length) faults.push('images with no alt attribute: ' + page.noAlt.join(', '));
  if (page.positiveTabindex) faults.push(page.positiveTabindex + ' positive tabindex value(s)');
  if (faults.length) throw new Error(faults.join('; '));
  return tree.nodes.filter(node => !node.ignored && node.role && controls.has(node.role.value)).length + ' named controls checked';
}
// Reflow: at 320 CSS pixels wide (what 400% zoom of a 1280 px window gives) the screen must not scroll sideways.
async function reflowCheck(width) {
  await cdp.send('Emulation.setDeviceMetricsOverride', {width, height: 900, deviceScaleFactor: 1, mobile: false});
  await sleep(400);
  if (env.PDFR_E2E_SHOTS) {
    const metrics = await cdp.send('Page.getLayoutMetrics');
    const shot = await cdp.send('Page.captureScreenshot', {format: 'png', captureBeyondViewport: true,
      clip: {x: 0, y: 0, width: metrics.cssContentSize.width, height: Math.min(metrics.cssContentSize.height, 3000), scale: 1}});
    fs.mkdirSync(env.PDFR_E2E_SHOTS, {recursive: true});
    fs.writeFileSync(path.join(env.PDFR_E2E_SHOTS, 'reflow-' + width + '-' + Date.now() + '.png'), Buffer.from(shot.data, 'base64'));
  }
  const found = await ev(`(function () {
    var overflow = document.documentElement.scrollWidth - document.documentElement.clientWidth;
    var wide = Array.from(document.querySelectorAll('body *')).filter(function (e) { var r = e.getBoundingClientRect(); return r.width > 0 && r.right > document.documentElement.clientWidth + 1 && getComputedStyle(e).position !== 'fixed'; })
      .slice(0, 6).map(function (e) { return e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.className && typeof e.className === 'string' ? '.' + e.className.split(' ')[0] : ''); });
    var bar = document.getElementById('job-bar');
    return {overflow: overflow, wide: wide, topBarHeight: Math.round(document.querySelector('header').getBoundingClientRect().height)};
  })()`);
  await cdp.send('Emulation.clearDeviceMetricsOverride');
  if (found.overflow > 1) throw new Error('the screen scrolls sideways by ' + found.overflow + ' px at ' + width + ' px wide; widest: ' + found.wide.join(', '));
  return 'no sideways scrolling at ' + width + ' px (top bar ' + found.topBarHeight + ' px tall)';
}

// Keyboard only: press Tab through the whole screen. Every stop must be a real, visible control that shows a focus indicator and is on
// screen (and not behind the bottom bar); the tour must come back to where it started instead of getting stuck.
async function keyboardTour(maxStops) {
  await ev(`window.scrollTo(0, 0); if (document.activeElement) document.activeElement.blur(); document.body.tabIndex = -1; document.body.focus(); document.body.removeAttribute('tabindex'); document.querySelectorAll('*').forEach(function (e) { delete e.__tab; }); window.__tabCount = 0; true`);
  const stops = [], problems = [], seenTokens = new Set();
  let wrapped = false;
  for (let i = 0; i < maxStops; i++) {
    await cdp.send('Input.dispatchKeyEvent', {type: 'rawKeyDown', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9});
    await cdp.send('Input.dispatchKeyEvent', {type: 'keyUp', key: 'Tab', code: 'Tab', windowsVirtualKeyCode: 9});
    const stop = await ev(`(function () {
      var e = document.activeElement;
      if (!e || e === document.body || e === document.documentElement) return {body: true};
      if (!e.__tab) e.__tab = ++window.__tabCount;
      var r = e.getBoundingClientRect(), cs = getComputedStyle(e), bar = document.getElementById('job-bar');
      var behindBar = bar && !bar.hidden && r.bottom > bar.getBoundingClientRect().top && r.top < bar.getBoundingClientRect().bottom;
      var label = (e.getAttribute('aria-label') || e.textContent || e.value || e.placeholder || e.id || '').replace(/\s+/g, ' ').trim().slice(0, 50);
      return {token: e.__tab, id: e.id, tag: e.tagName.toLowerCase(), type: e.type || '', label: label, focusVisible: e.matches(':focus-visible'),
        outline: cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0, shadow: cs.boxShadow !== 'none', width: Math.round(r.width), height: Math.round(r.height),
        onScreen: r.top >= -1 && r.bottom <= innerHeight + 1 && r.left >= -1 && r.right <= innerWidth + 1, behindBar: !!behindBar, visibility: cs.visibility, display: cs.display};
    })()`);
    if (stop.body) { wrapped = true; break; }
    if (seenTokens.has(stop.token)) { wrapped = true; break; }
    seenTokens.add(stop.token);
    stops.push(stop);
    const where = stop.tag + (stop.id ? '#' + stop.id : '') + ' "' + stop.label + '"';
    if (!stop.focusVisible) problems.push(where + ' was reached by keyboard but is not :focus-visible');
    if (!stop.outline && !stop.shadow) problems.push(where + ' shows no focus indicator');
    if (stop.width < 2 || stop.height < 2 || stop.visibility !== 'visible' || stop.display === 'none') problems.push(where + ' is focusable but not visible');
    if (!stop.onScreen) problems.push(where + ' was not scrolled into view');
    if (stop.behindBar) problems.push(where + ' is hidden behind the status bar');
  }
  const skipped = await ev(`Array.from(document.querySelectorAll('a[href], button, input, select, textarea, summary, [tabindex]')).filter(function (e) {
    if (e.__tab || e.disabled || e.hidden || e.closest('[hidden], [inert]') || Number(e.getAttribute('tabindex')) < 0 || e.type === 'hidden') return false;
    for (var d = e.closest('details'); d; d = d.parentElement && d.parentElement.closest('details')) {
      if (!d.open && !(e.tagName === 'SUMMARY' && e.parentElement === d)) return false;
    }
    var cs = getComputedStyle(e), r = e.getBoundingClientRect(); return cs.visibility === 'visible' && cs.display !== 'none' && r.width > 1 && r.height > 1;
  }).slice(0, 8).map(function (e) { return e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + ' "' + (e.getAttribute('aria-label') || e.textContent || e.value || '').replace(/\s+/g, ' ').trim().slice(0, 30) + '"'; })`);
  if (skipped.length) problems.push('Tab never reached ' + skipped.length + '+ visible control(s) that can be focused: ' + skipped.join(', '));
  if (!wrapped) problems.push('the tour never came back to its start after ' + maxStops + ' stops (a keyboard trap?)');
  if (!stops.length) problems.push('Tab reached nothing');
  if (problems.length && env.PDFR_E2E_DEBUG) console.log('     (tab stops: ' + JSON.stringify(stops.map(stop => stop.tag + (stop.id ? '#' + stop.id : ''))) + '; the next press gave: ' +
    JSON.stringify(await ev(`(function () { var back = document.getElementById('back'), r = back.getBoundingClientRect(); return {active: document.activeElement && (document.activeElement.id || document.activeElement.tagName), backHidden: back.hidden, backDisabled: back.disabled, backInHiddenParent: !!back.closest('[hidden]'), backRect: [Math.round(r.top), Math.round(r.width), Math.round(r.height)], reviewHidden: document.getElementById('review').hidden, dashboardHidden: document.getElementById('dashboard').hidden}; })()`)) + ')');
  if (problems.length) throw new Error(problems.slice(0, 6).join('; ') + (problems.length > 6 ? ' ...(' + problems.length + ' in all)' : ''));
  return stops.length + ' tab stops, in order: ' + stops.slice(0, 8).map(stop => stop.id || stop.tag).join(' > ') + (stops.length > 8 ? ' > ...' : '');
}

async function startService() {
  const child = spawn(env.PDFR_E2E_PYTHON, ['-B', '-m', 'pdf_remediator', 'serve', '--data-dir', dataDir, '--no-open', '--session-file', sessionFile, '--config', path.resolve(env.PDFR_E2E_CONFIG)],
    {cwd: root, env: {...env, PYTHONPATH: path.join(root, 'src')}, stdio: ['ignore', fs.openSync(path.join(work, 'service.log'), 'a'), fs.openSync(path.join(work, 'service.log'), 'a')]});
  child.exited = new Promise(resolve => child.on('exit', code => resolve(code)));
  const deadline = Date.now() + 60000;
  while (Date.now() < deadline) {
    if (fs.existsSync(sessionFile)) { try { const session = JSON.parse(fs.readFileSync(sessionFile, 'utf8')); if (session.url) return {child, url: session.url}; } catch (error) { /* still being written */ } }
    await sleep(250);
  }
  throw new Error('the service did not write its session file in 60 s');
}
async function startBrowser() {
  const child = spawn(EDGE, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0', '--remote-allow-origins=*',
    '--user-data-dir=' + profile, '--window-size=1400,1000', 'about:blank'], {stdio: 'ignore'});
  const portFile = path.join(profile, 'DevToolsActivePort');
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline && !fs.existsSync(portFile)) await sleep(200);
  if (!fs.existsSync(portFile)) throw new Error('the browser did not open its debugging port');
  const port = fs.readFileSync(portFile, 'utf8').split(/\r?\n/)[0];
  let target = null;
  for (let attempt = 0; attempt < 50 && !target; attempt++) {
    const list = await (await fetch('http://127.0.0.1:' + port + '/json/list')).json();
    target = list.find(item => item.type === 'page');
    if (!target) await sleep(200);
  }
  if (!target) throw new Error('no browser page to drive');
  return {child, wsUrl: target.webSocketDebuggerUrl};
}
function cleanUp() {
  // only the browser processes that were started with this run's own scratch profile, and the service this run started
  spawnSync('powershell', ['-NoProfile', '-Command',
    `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*${path.basename(work)}*' -and $_.ProcessId -ne $PID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }`], {stdio: 'ignore'});
}

async function step(name, body) {
  try { const detail = await body(); record(name, true, detail || ''); }
  catch (error) { record(name, false, error.message); }
}

async function main() {
  const started = await startService(); service = started.child;
  browser = await startBrowser();
  cdp = new Cdp(browser.wsUrl); await cdp.open();
  cdp.on('Runtime.exceptionThrown', params => problems.push('script error: ' + (params.exceptionDetails.exception?.description || params.exceptionDetails.text)));
  cdp.on('Runtime.consoleAPICalled', params => { if (params.type === 'error' && !expectNetworkErrors) problems.push('console error: ' + params.args.map(arg => arg.value || arg.description).join(' ')); });
  cdp.on('Log.entryAdded', params => { if (params.entry.level === 'error' && !expectNetworkErrors && !/favicon/i.test(params.entry.url || '')) problems.push('log error: ' + params.entry.text + ' ' + (params.entry.url || '')); });
  cdp.on('Page.javascriptDialogOpening', params => { problems.push('the page opened a dialog: ' + params.message); cdp.send('Page.handleJavaScriptDialog', {accept: true}).catch(() => {}); });
  for (const domain of ['Page', 'Runtime', 'Log', 'DOM', 'Accessibility']) await cdp.send(domain + '.enable');

  if (env.PDFR_E2E_ONLY === 'cancel-rescan') {
    // a scan of the long PDF is cancelled and the same PDF is scanned again; optionally after the short scanned file went through OCR first
    if (!LONG) throw new Error('this scenario needs PDFR_E2E_LONG_PDF');
    await cdp.send('Page.navigate', {url: started.url});
    await waitFor(`document.title === 'PDF Remediator' && !document.getElementById('dashboard').hidden`, 30000, 'the start screen');
    if (env.PDFR_E2E_PRE_OCR) {
      await choose(SHORT);
      await ev(`document.getElementById('new-ocr').value = 'textless'; document.getElementById('new-ocr').dispatchEvent(new Event('change')); true`);
      await click('process');
      await waitFor(`!document.getElementById('review').hidden`, 300000, 'the OCR review');
      await waitFor(`document.getElementById('opening-note').hidden`, 120000, 'the OCR review to finish opening');
      await click('home-button'); await waitFor(`!document.getElementById('dashboard').hidden`, 10000, 'the start screen');
      await ev(`document.getElementById('new-ocr').value = 'off'; document.getElementById('new-ocr').dispatchEvent(new Event('change')); true`);
      await click('reset-button'); await waitFor(`/Start screen reset/.test(document.getElementById('notice').textContent)`, 10000, 'the reset');
    }
    if (env.PDFR_E2E_LONG_OCR) await ev(`document.getElementById('new-ocr').value = 'textless'; document.getElementById('new-ocr').dispatchEvent(new Event('change')); true`);
    await choose(LONG);
    await click('process');
    await waitFor(`!document.getElementById('job-bar').hidden`, 10000, 'the status bar');
    await sleep(Number(env.PDFR_E2E_CANCEL_AFTER_MS || 3000));
    await click('job-cancel');
    const cancelClicked = Date.now();
    try { await waitFor(`document.getElementById('job-bar').hidden && /cancelled/.test(document.getElementById('notice').textContent)`, 240000, 'the cancelled notice'); console.log('     (cancel took ' + Math.round((Date.now() - cancelClicked) / 100) / 10 + ' s after ' + (env.PDFR_E2E_CANCEL_AFTER_MS || 3000) + ' ms)'); }
    catch (error) { throw new Error(error.message + ' | page said: ' + JSON.stringify(await ev(`({notice: document.getElementById('notice').textContent, isError: document.getElementById('notice').classList.contains('error'), barHidden: document.getElementById('job-bar').hidden, step: document.getElementById('job-step').textContent, cancelButton: document.getElementById('job-cancel').textContent, review: !document.getElementById('review').hidden})`))); }
    await click('home-button'); await waitFor(`!document.getElementById('dashboard').hidden`, 10000, 'the start screen');
    if (env.PDFR_E2E_LONG_OCR) await ev(`document.getElementById('new-ocr').value = 'textless'; document.getElementById('new-ocr').dispatchEvent(new Event('change')); true`);
    await choose(LONG);
    await click('process');
    const t0 = Date.now();
    await waitFor(`!document.getElementById('review').hidden || document.getElementById('notice').classList.contains('error')`, 400000, 'the second scan to end');
    const outcome = await ev(`({review: !document.getElementById('review').hidden, notice: document.getElementById('notice').textContent, error: document.getElementById('notice').classList.contains('error')})`);
    record('the same long PDF can be scanned again after a cancelled scan' + (env.PDFR_E2E_PRE_OCR ? ' (after an OCR run)' : ''), outcome.review && !outcome.error,
      Math.round((Date.now() - t0) / 1000) + ' s; ' + JSON.stringify(outcome).slice(0, 300));
    return;
  }
  if (env.PDFR_E2E_ONLY === 'crash') {
    if (!LONG) throw new Error('the crash scenario needs PDFR_E2E_LONG_PDF');
    await cdp.send('Page.navigate', {url: started.url});
    await waitFor(`document.title === 'PDF Remediator' && !document.getElementById('dashboard').hidden`, 30000, 'the start screen');
    await choose(LONG);
    await watchBars();
    await click('process');
    await waitFor(`!document.getElementById('job-bar').hidden`, 10000, 'the status bar');
    await sleep(3000);
    expectNetworkErrors = true;
    service.kill();
    await Promise.race([service.exited, sleep(10000)]);
    await sleep(6000);
    const state = await ev(`({notice: document.getElementById('notice').textContent, isError: document.getElementById('notice').classList.contains('error'), bar: document.getElementById('job-bar').hidden,
      barStep: document.getElementById('job-step').textContent, clock: document.getElementById('job-clock').textContent, cancelOff: document.getElementById('job-cancel').disabled,
      process: document.getElementById('process').disabled, files: document.getElementById('selected-files').children.length})`);
    console.log('     (after the service vanished: ' + JSON.stringify(state) + ')');
    await sleep(3000);
    const later = await ev(`document.getElementById('job-clock').textContent`);
    record('when the service disappears mid-job the page says so and stops claiming the job is running', /lost|stopp|not respond|reach|connect|failed to fetch/i.test(state.notice) && state.isError && state.bar,
      'notice: ' + JSON.stringify(state.notice) + ' | bar hidden: ' + state.bar + ' | clock text a few seconds later: ' + JSON.stringify(later));
    return;
  }
  await step('the page opens with the private launch address and shows the start screen', async () => {
    await cdp.send('Page.navigate', {url: started.url});
    await waitFor(`document.title === 'PDF Remediator' && document.getElementById('documents').children.length > 0 && !document.getElementById('dashboard').hidden`, 30000, 'the start screen');
    return 'title and document list present';
  });
  await step('the top bar has Home and Reset; the old Processing activity section is gone', async () => {
    const found = await ev(`({home: document.getElementById('home-button').textContent, reset: document.getElementById('reset-button').textContent,
      oldSection: !!document.getElementById('jobs-section') || !!document.getElementById('review-activity') || document.body.textContent.includes('Processing activity'),
      homeVisible: document.getElementById('home-button').getBoundingClientRect().width > 0, resetVisible: document.getElementById('reset-button').getBoundingClientRect().width > 0})`);
    if (found.home !== 'Home' || found.reset !== 'Reset' || !found.homeVisible || !found.resetVisible) throw new Error(JSON.stringify(found));
    if (found.oldSection) throw new Error('the old Processing activity section is still on the page');
  });
  await step('the start screen explains Reset choices in plain words', async () => {
    const note = await text('reset-note'), button = await text('reset-start');
    if (button !== 'Reset choices' || !/clears the PDFs you chose and puts every option back to its normal setting/.test(note) || !/saved documents are not touched/.test(note)) throw new Error(button + ' | ' + note);
    if (!(await ev(`document.getElementById('reset-note').getBoundingClientRect().height > 0`))) throw new Error('the explanation is not visible');
  });
  await step('start screen: every control has an accessible name and the page structure is sound', () => accessibilityAudit());
  await step('start screen: no sideways scrolling at 320 px wide (400% zoom)', () => reflowCheck(320));
  await step('start screen: Tab visits every control in order, each shows a focus indicator and is on screen', () => keyboardTour(120));
  await step('choosing a PDF then Reset choices clears the file and every option', async () => {
    await choose(SHORT);
    await ev(`document.getElementById('new-title').value = 'A title I typed'; document.getElementById('new-language').value = 'fr-FR'; document.getElementById('new-regroup').checked = true; true`);
    if (await ev(`document.getElementById('process').disabled`)) throw new Error('Process stayed disabled after a file was chosen');
    await click('reset-start');
    const after = await ev(`({files: document.getElementById('selected-files').children.length, process: document.getElementById('process').disabled, title: document.getElementById('new-title').value,
      language: document.getElementById('new-language').value, regroup: document.getElementById('new-regroup').checked, input: document.getElementById('files').value, notice: document.getElementById('notice').textContent})`);
    if (after.files !== 0 || !after.process || after.title !== '' || after.language !== 'en-US' || after.regroup || after.input !== '' || !/Start screen reset/.test(after.notice)) throw new Error(JSON.stringify(after));
  });
  await step('Letter dictionary box: asks first, locks the options it cannot be combined with, Escape leaves it off, Reset frees it', async () => {
    const read = () => ev(`({checked: document.getElementById('new-ocrmap').checked, disabled: document.getElementById('new-ocrmap').disabled, ocr: document.getElementById('new-ocr').value,
      ocrLocked: document.getElementById('new-ocr').disabled, mappingLocked: document.getElementById('new-mapping').disabled})`);
    if ((await read()).disabled) return 'skipped: the OCR components are not available in this setup';
    await ev(`document.getElementById('new-ocrmap').click(), true`);
    await waitFor(`document.getElementById('ocrmap-dialog').open`, 3000, 'the explanation dialog');
    await cdp.send('Input.dispatchKeyEvent', {type: 'rawKeyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27});
    await cdp.send('Input.dispatchKeyEvent', {type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27});
    await waitFor(`!document.getElementById('ocrmap-dialog').open && !document.getElementById('new-ocrmap').checked`, 3000, 'the dialog to close and the box to switch off');
    let state = await read();
    if (state.checked || state.ocrLocked || state.mappingLocked) throw new Error('Escape did not leave it off: ' + JSON.stringify(state));
    await ev(`document.getElementById('new-ocrmap').click(), true`);
    await waitFor(`document.getElementById('ocrmap-dialog').open`, 3000, 'the dialog again');
    await ev(`document.querySelector('#ocrmap-dialog button[value="allow"]').click(), true`);
    await waitFor(`!document.getElementById('ocrmap-dialog').open && document.getElementById('new-ocr').disabled`, 3000, 'the dialog to close and the other options to lock after yes');
    state = await read();
    if (!state.checked || state.ocr !== 'off' || !state.ocrLocked || !state.mappingLocked) throw new Error('Yes did not switch the other options off: ' + JSON.stringify(state));
    await click('reset-start');
    state = await read();
    if (state.checked || state.ocrLocked || state.mappingLocked) throw new Error('Reset choices did not free the options: ' + JSON.stringify(state));
  });
  await step('Process with nothing chosen is refused politely', async () => {
    await ev(`document.getElementById('process').disabled = false; document.getElementById('process').click(); true`);
    await waitFor(`document.getElementById('notice').textContent === 'Choose at least one PDF first.'`, 3000, 'the refusal message');
  });
  await step('a short PDF is processed and its review opens; the status bar goes away', async () => {
    await choose(SHORT);
    await watchBars();
    await click('process');
    const clicked = Date.now();
    await waitFor(`!document.getElementById('review').hidden`, 180000, 'the review to open');
    const opened = Date.now();
    await waitFor(`/Processing finished|ready to inspect/.test(document.getElementById('notice').textContent) && document.getElementById('opening-note').hidden`, 120000, 'the finished notice and the review to finish opening');
    const settled = Date.now();
    if (!(await hidden('job-bar'))) throw new Error('the status bar is still showing after the job ended');
    const s = await seen();
    return 'scan ' + Math.round((opened - clicked) / 1000) + ' s, review fully open ' + Math.round((settled - opened) / 1000) + ' s later; bar seen while running: ' + s.bar + (s.bar ? ' (' + JSON.stringify(s.barLabel) + ', ' + s.barSteps.length + ' step(s), clock changed ' + s.barClocks + ' time(s))' : ' (the job was too quick to catch)');
  });
  await step('Home in the top bar returns to the document list; the document is listed and reopens', async () => {
    await click('home-button');
    await waitFor(`!document.getElementById('dashboard').hidden && document.getElementById('review').hidden`, 10000, 'the start screen');
    const listed = await ev(`document.getElementById('documents').querySelectorAll('button').length`);
    if (listed < 1) throw new Error('no document is listed');
    await ev(`document.getElementById('documents').querySelector('button').click(), true`);
    await waitFor(`!document.getElementById('review').hidden && document.getElementById('opening-note').hidden`, 90000, 'the review to reopen');
  });
  await step('review screen: every control has an accessible name and the page structure is sound', () => accessibilityAudit());
  await step('review screen: no sideways scrolling at 320 px wide (400% zoom)', () => reflowCheck(320));
  await step('review screen: Tab visits every control in order, each shows a focus indicator and is on screen', () => keyboardTour(400));
  await step('Unsaved fields: leaving a review asks first; Escape stays, "Leave without saving" goes', async () => {
    const changed = await ev(`(function () {
      var cards = Array.prototype.slice.call(document.getElementById('decisions').children);
      for (var i = 0; i < cards.length; i++) {
        var card = cards[i];
        if (typeof card.hasUnsavedDecision !== 'function') continue;
        var field = card.querySelector('textarea, input[type=text], input:not([type]), select');
        if (!field) continue;
        if (field.tagName === 'SELECT') {
          var other = Array.prototype.find.call(field.options, function (option) { return option.value !== field.value; });
          if (!other) continue;
          field.value = other.value;
        } else field.value = field.value + ' edited';
        field.dispatchEvent(new Event('input', {bubbles: true})); field.dispatchEvent(new Event('change', {bubbles: true}));
        return card.hasUnsavedDecision();
      }
      return null;
    })()`);
    if (changed === null) return 'skipped: this review has no editable decision field';
    if (!changed) throw new Error('the changed field was not counted as unsaved');
    // a small log of what the dialog and the network do, so a failure below can show the order of events
    await ev(`(function () { window.__leaveLog = []; var stamp = function () { return Math.round(performance.now()); }; var d = document.getElementById('leave-dialog');
      ['cancel', 'close'].forEach(function (name) { d.addEventListener(name, function () { window.__leaveLog.push(name + ' value=' + d.returnValue + ' open=' + d.open + ' @' + stamp()); }, true); });
      var original = window.fetch; window.fetch = function (url) { window.__leaveLog.push('fetch ' + String(url).slice(0, 50) + ' @' + stamp()); return original.apply(this, arguments); };
      document.getElementById('back').addEventListener('click', function () { window.__leaveLog.push('back clicked @' + stamp()); }, true); return true; })()`);
    await click('back');
    await waitFor(`document.getElementById('leave-dialog').open`, 3000, 'the leave dialog');
    await cdp.send('Input.dispatchKeyEvent', {type: 'rawKeyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27});
    await cdp.send('Input.dispatchKeyEvent', {type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27});
    await waitFor(`!document.getElementById('leave-dialog').open`, 3000, 'the dialog to close');
    await sleep(300);
    if (await ev(`document.getElementById('review').hidden`)) throw new Error('Escape left the review');
    await click('back');
    await waitFor(`document.getElementById('leave-dialog').open`, 3000, 'the leave dialog again');
    await ev(`document.querySelector('#leave-dialog button[value="leave"]').click(), true`);
    const leftAt = Date.now();
    try { await waitFor(`!document.getElementById('dashboard').hidden && document.getElementById('review').hidden`, 30000, 'the document list'); }
    catch (error) {
      const state = await ev(`({dialogOpen: document.getElementById('leave-dialog').open, dialogReturn: document.getElementById('leave-dialog').returnValue, reviewHidden: document.getElementById('review').hidden,
        dashboardHidden: document.getElementById('dashboard').hidden, notice: document.getElementById('notice').textContent.slice(0, 160), active: document.activeElement && (document.activeElement.id || document.activeElement.tagName),
        bar: !document.getElementById('job-bar').hidden, opening: !document.getElementById('opening-note').hidden, log: window.__leaveLog, now: Math.round(performance.now())})`);
      throw new Error(error.message + ' | page state: ' + JSON.stringify(state));
    }
    console.log('     (the document list appeared ' + Math.round((Date.now() - leftAt) / 100) / 10 + ' s after "Leave without saving")');
    await ev(`document.getElementById('documents').querySelector('button').click(), true`);
    await waitFor(`!document.getElementById('review').hidden && document.getElementById('opening-note').hidden`, 90000, 'the review to reopen');
  });
  await step('Reset in the top bar, from a review, goes to the start screen and clears it', async () => {
    await ev(`document.getElementById('new-title').value = 'typed before Reset'; true`);
    await click('reset-button');
    await waitFor(`!document.getElementById('dashboard').hidden && document.getElementById('review').hidden && /Start screen reset/.test(document.getElementById('notice').textContent)`, 30000, 'the start screen to be reset');
    const after = await ev(`({title: document.getElementById('new-title').value, notice: document.getElementById('notice').textContent})`);
    if (after.title !== '' || !/Start screen reset/.test(after.notice)) throw new Error(JSON.stringify(after));
  });
  await step('Auto-fix on the short review shows a result message and clears its status line', async () => {
    await ev(`document.getElementById('documents').querySelector('button').click(), true`);
    await waitFor(`!document.getElementById('review').hidden && document.getElementById('opening-note').hidden`, 90000, 'the review to reopen');
    await watchBars();
    await click('auto-fix');
    await waitFor(`/^Automatic processing/.test(document.getElementById('notice').textContent)`, 180000, 'the Auto-fix result message');
    await sleep(600);
    if (!(await hidden('auto-status'))) throw new Error('the Auto-fix line is still showing after the job ended');
    const s = await seen();
    return 'message: ' + (await text('notice')).slice(0, 140) + ' | line seen while running: ' + s.auto;
  });

  await step('a file that is not a PDF is refused politely: a clear error, nothing left running, the page still works', async () => {
    const fake = path.join(work, 'not-really-a-pdf.pdf');
    fs.writeFileSync(fake, 'This is plain text pretending to be a PDF.');
    await ev(`document.getElementById('reset-button').click(), true`);
    await waitFor(`!document.getElementById('dashboard').hidden && /Start screen reset/.test(document.getElementById('notice').textContent)`, 10000, 'the start screen to be reset');
    await choose(fake);
    expectNetworkErrors = true;
    try {
      await click('process');
      await waitFor(`!/^Sending your PDFs/.test(document.getElementById('notice').textContent) && document.getElementById('notice').textContent.length > 0`, 90000, 'any message after the file was sent');
      await sleep(2500);
    } finally { expectNetworkErrors = false; }
    const shown = await ev(`({notice: document.getElementById('notice').textContent, isError: document.getElementById('notice').classList.contains('error'), bar: document.getElementById('job-bar').hidden,
      process: document.getElementById('process').disabled, startVisible: !document.getElementById('dashboard').hidden, reviewVisible: !document.getElementById('review').hidden,
      status: (document.getElementById('document-status') || {}).textContent || '', banner: (document.getElementById('review-banner') || {}).textContent || ''})`);
    console.log('     (not-a-PDF outcome: ' + JSON.stringify(shown).slice(0, 700) + ')');
    if (!shown.bar) throw new Error('the status bar is still showing: ' + JSON.stringify(shown));
    if (/Traceback|Exception|undefined|\[object/.test(shown.notice + shown.banner)) throw new Error('the message exposes internals: ' + shown.notice);
    if (!shown.isError && !shown.reviewVisible) throw new Error('neither an error message nor a review explaining the failure: ' + JSON.stringify(shown));
    return 'message: ' + shown.notice.slice(0, 160);
  });
  await step('two PDFs at once become one job named for both, and both documents are listed', async () => {
    const second = path.join(work, 'second-copy.pdf');
    fs.copyFileSync(SHORT, second);
    await ev(`document.getElementById('reset-button').click(), true`);
    await waitFor(`!document.getElementById('dashboard').hidden && /Start screen reset/.test(document.getElementById('notice').textContent)`, 10000, 'the start screen to be reset');
    const before = await ev(`document.getElementById('documents').querySelectorAll('button').length`);
    await choose(SHORT, second);
    await watchBars();
    await click('process');
    await waitFor(`!document.getElementById('review').hidden`, 240000, 'the review to open');
    await waitFor(`document.getElementById('opening-note').hidden`, 120000, 'the review to finish opening');
    const s = await seen();
    await click('home-button');
    await waitFor(`!document.getElementById('dashboard').hidden`, 10000, 'the start screen');
    const after = await ev(`document.getElementById('documents').querySelectorAll('button').length`);
    if (after < before + 2) throw new Error('documents listed before: ' + before + ', after: ' + after);
    if (s.bar && !/2 selected PDF/.test(s.barLabel)) throw new Error('the bar named the job ' + JSON.stringify(s.barLabel));
    return 'documents ' + before + ' -> ' + after + '; bar label ' + JSON.stringify(s.barLabel);
  });

  await step('OCR: the scanned test file is processed with "Add text only on wholly scanned pages" and the page shows the outcome', async () => {
    await ev(`document.getElementById('reset-button').click(), true`);
    await waitFor(`!document.getElementById('dashboard').hidden && /Start screen reset/.test(document.getElementById('notice').textContent)`, 10000, 'the start screen to be reset');
    const offered = await ev(`(function () { var o = document.getElementById('new-ocr').querySelector('option[value="textless"]'); return !!o && !o.disabled; })()`);
    if (!offered) return 'skipped: OCR is not available in this setup (the option is switched off)';
    await choose(SHORT);
    await ev(`document.getElementById('new-ocr').value = 'textless'; document.getElementById('new-ocr').dispatchEvent(new Event('change')); true`);
    if (await ev(`document.getElementById('new-ocr-profile').disabled`)) throw new Error('the scan layout stayed switched off after OCR was chosen');
    await watchBars();
    const clicked = Date.now();
    await click('process');
    await waitFor(`!document.getElementById('review').hidden || document.getElementById('notice').classList.contains('error')`, 600000, 'the OCR run to finish');
    const seconds = Math.round((Date.now() - clicked) / 1000);
    if (await ev(`document.getElementById('notice').classList.contains('error')`)) throw new Error('OCR run ended in an error: ' + (await text('notice')));
    await waitFor(`document.getElementById('opening-note').hidden`, 120000, 'the review to finish opening');
    const seen1 = await seen();
    if (!(await hidden('job-bar'))) throw new Error('the bar is still showing after the run');
    // the proposed result of an OCR run must be drawable: its page picture has to load (it once could not, because the pipeline's form check
    // disagreed with the inspector's about the invisible OCR text streams)
    const picture = await ev(`fetch('/api/workspaces/' + currentId + '/page?kind=candidate&page=1', {headers: {'X-Review-Token': token}}).then(function (r) { return {status: r.status, type: r.headers.get('content-type')}; })`);
    if (picture.status !== 200 || !/image\/png/.test(picture.type || '')) throw new Error('the proposed page of the OCR result could not be drawn: ' + JSON.stringify(picture));
    // leave the start options as they were, so the long-PDF scenarios below run with OCR off as intended
    if (!env.PDFR_E2E_KEEP_OCR) await ev(`document.getElementById('new-ocr').value = 'off'; document.getElementById('new-ocr').dispatchEvent(new Event('change')); true`);
    return 'finished in ' + seconds + ' s; steps seen: ' + JSON.stringify(seen1.barSteps);
  });

  if (LONG) {
    await step('a long PDF: the bottom bar appears at once, stays at the bottom edge, follows the steps and keeps a clock', async () => {
      await click('home-button');
      await waitFor(`!document.getElementById('dashboard').hidden`, 10000, 'the start screen');
      await choose(LONG);
      await watchBars();
      await click('process');
      await waitFor(`!document.getElementById('job-bar').hidden`, 5000, 'the status bar to appear');
      await sleep(2500);
      const geometry = await ev(`(function () {
        var barEl = document.getElementById('job-bar'), footer = document.querySelector('footer');
        var gap = function () { return Math.round(innerHeight - barEl.getBoundingClientRect().bottom); };
        var max = document.documentElement.scrollHeight - innerHeight;
        window.scrollTo(0, 0); var top = gap();
        var mid = null; if (max > 40) { window.scrollTo(0, Math.floor(max / 2)); mid = gap(); }
        window.scrollTo(0, max); var coversFooter = footer ? barEl.getBoundingClientRect().bottom > footer.getBoundingClientRect().top + 1 : false;
        window.scrollTo(0, 0);
        return {top: top, mid: mid, scrollable: max > 40, coversFooter: coversFooter, height: Math.round(barEl.getBoundingClientRect().height)};
      })()`);
      if (geometry.top !== 0 || (geometry.mid !== null && geometry.mid !== 0)) throw new Error('the bar is not stuck to the bottom edge: ' + JSON.stringify(geometry));
      if (geometry.coversFooter) throw new Error('at the end of the page the bar covers the footer (Stop application): ' + JSON.stringify(geometry));
      const shown = await ev(`({label: document.getElementById('job-label').textContent, step: document.getElementById('job-step').textContent, clock: document.getElementById('job-clock').textContent,
        cancel: document.getElementById('job-cancel').textContent, cancelOff: document.getElementById('job-cancel').disabled})`);
      if (!shown.label || !shown.step || !/^Working for \d+:\d\d\. Please keep this window open\./.test(shown.clock) || shown.cancel !== 'Cancel' || shown.cancelOff) throw new Error(JSON.stringify(shown));
      return JSON.stringify(shown);
    });
    await step('Cancel in the bar cancels the scan: "Cancelling...", then the bar goes and the notice says it was cancelled', async () => {
      await click('job-cancel');
      const asked = await ev(`({text: document.getElementById('job-cancel').textContent, off: document.getElementById('job-cancel').disabled})`);
      if (asked.text !== 'Cancelling…' || !asked.off) throw new Error(JSON.stringify(asked));
      await waitFor(`document.getElementById('job-bar').hidden`, 60000, 'the bar to go away after Cancel');
      await waitFor(`/cancelled/.test(document.getElementById('notice').textContent)`, 10000, 'the cancelled notice');
      const ready = await ev(`({text: document.getElementById('job-cancel').textContent, off: document.getElementById('job-cancel').disabled})`);
      if (ready.text !== 'Cancel' || ready.off) throw new Error('Cancel was not ready again: ' + JSON.stringify(ready));
    });
    await step('the long PDF is processed to the end and its review opens', async () => {
      await click('home-button');
      await waitFor(`!document.getElementById('dashboard').hidden`, 10000, 'the start screen');
      await choose(LONG);
      await click('process');
      try { await waitFor(`!document.getElementById('review').hidden || document.getElementById('notice').classList.contains('error')`, 600000, 'the long review to open'); }
      catch (error) {
        const where = await ev(`({label: document.getElementById('job-label').textContent, step: document.getElementById('job-step').textContent, clock: document.getElementById('job-clock').textContent, barHidden: document.getElementById('job-bar').hidden, notice: document.getElementById('notice').textContent})`);
        throw new Error(error.message + ' | page said: ' + JSON.stringify(where));
      }
      if (await ev(`document.getElementById('review').hidden`)) throw new Error('the long scan ended in an error instead of opening a review: ' + (await text('notice')));
      await waitFor(`document.getElementById('opening-note').hidden`, 180000, 'the long review to finish opening');
      await sleep(600);
      if (!(await hidden('job-bar'))) throw new Error('the status bar is still showing');
      const s = await seen();
      return 'bar steps seen: ' + JSON.stringify(s.barSteps) + ', clock changed ' + s.barClocks + ' time(s)';
    });
    await step('Auto-fix on the long review: its own line (not the bottom bar) with a clock, and Cancel beside it works', async () => {
      await watchBars();
      await click('auto-fix');
      if (await hidden('auto-status')) throw new Error('nothing was shown at the click');
      const first = await text('auto-step');
      const sent = Date.now();
      await waitFor(`!/^Sending your request/.test(document.getElementById('auto-step').textContent)`, 120000, 'the service to accept the request');
      const waited = Math.round((Date.now() - sent) / 1000);
      await sleep(3000);
      const shown = await ev(`({bar: document.getElementById('job-bar').hidden, step: document.getElementById('auto-step').textContent, clock: document.getElementById('auto-clock').textContent,
        cancel: document.getElementById('auto-cancel').textContent})`);
      if (!shown.bar) throw new Error('the bottom bar was showing too, so one job was announced twice');
      if (!shown.step || !/^Working for \d+:\d\d\./.test(shown.clock) || shown.cancel !== 'Cancel') throw new Error(JSON.stringify(shown));
      await click('auto-cancel');
      if ((await text('auto-cancel')) !== 'Cancelling…') throw new Error('the Cancel button did not change to Cancelling...');
      await waitFor(`document.getElementById('auto-status').hidden`, 120000, 'the Auto-fix line to go away');
      await waitFor(`/cancelled/.test(document.getElementById('notice').textContent)`, 10000, 'the cancelled notice');
      return 'at the click: ' + JSON.stringify(first) + '; the service took ' + waited + ' s to accept it; then ' + JSON.stringify(shown);
    });
  }

  await step('Stop application stops the service and the page says so', async () => {
    await click('stop');
    await waitFor(`/has stopped/.test(document.getElementById('notice').textContent)`, 10000, 'the stopped notice');
    const code = await Promise.race([service.exited, sleep(20000).then(() => 'still running')]);
    if (code === 'still running') throw new Error('the service was still running 20 s after Stop application');
    if (!(await hidden('job-bar')) || !(await hidden('auto-status'))) throw new Error('a status line is still showing after Stop');
    return 'service exited with code ' + code;
  });
  record('the page raised no script errors, console errors or dialogs', problems.length === 0, problems.slice(0, 5).join(' | '));
}

main().catch(error => record('the run itself', false, error.message)).finally(() => {
  const failed = results.filter(item => !item.ok);
  console.log('\n' + results.length + ' checks, ' + failed.length + ' failed.');
  fs.writeFileSync(path.join(work, 'results.json'), JSON.stringify({results, problems}, null, 1));
  if (service && service.exitCode === null) { try { service.kill(); } catch (error) { /* already gone */ } }
  cleanUp();
  if (!failed.length) { try { fs.rmSync(work, {recursive: true, force: true}); } catch (error) { console.log('could not remove ' + work); } }
  else console.log('Kept for inspection: ' + work);
  process.exit(failed.length ? 1 : 0);
});
