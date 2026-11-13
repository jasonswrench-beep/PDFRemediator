'use strict';

if (Number(process.versions.node.split('.')[0]) < 20) throw new Error('Node.js 20 or newer is required for the web-asset contract tests.');

// Standalone developer regression: real complete app.js, named DOM/HTTP doubles.
// This does not run a browser, bind a service, process a PDF, or call a provider.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const appPath = process.argv[2] || path.resolve(__dirname, '../src/pdf_remediator/web_assets/app.js');
const appBytes = fs.readFileSync(appPath);
const applicationScript = new vm.Script(appBytes.toString('utf8'), {filename: path.resolve(appPath)});
const TOKEN_KEY = 'pdf-review-token';
const VALID = 'authored-current-private-token';
const STALE = 'authored-previous-private-token';
const WRONG = 'authored-wrong-private-token';
const NO_TOKEN_NOTICE = 'Open the private launch link printed by PDF Remediator to start this review session.';
const REFUSAL_NOTICE = 'Open the private launch link to use this review session.';
console.info('Web-asset contracts: complete shipped app.js with named DOM/HTTP doubles; no browser, service, PDF engine, or provider.');

function nodeDouble(tag = 'div', environment = {}) {
  const classes = new Set();
  let value = '', identifier = '', selectedValue = null;
  let selectionStart = 0, selectionEnd = 0, selectionDirection = 'none';
  const textControl = () => tag.toUpperCase() === 'TEXTAREA' || (tag.toUpperCase() === 'INPUT' && node.type !== 'checkbox');
  const node = {
    tagName: tag.toUpperCase(), textContent: '', hidden: false,
    disabled: false, checked: false, children: [], dataset: {}, attributes: {},
    parentNode: null, style: {},
    listeners: new Map(),
    classList: {
      add(...values) { values.forEach(value => classes.add(value)); },
      remove(...values) { values.forEach(value => classes.delete(value)); },
      toggle(value, force) {
        const enabled = force === undefined ? !classes.has(value) : Boolean(force);
        if (enabled) classes.add(value); else classes.delete(value);
        return enabled;
      },
      contains(value) { return classes.has(value); },
    },
    append(...children) {
      for (const child of children) {
        child.parentNode = this;
        this.children.push(child);
      }
    },
    replaceChildren(...children) {
      // Browsers move focus to body when the focused descendant is removed.
      // Model that consequence so retaining a detached old button cannot pass.
      for (let focused = environment.document?.activeElement; focused && focused !== this; focused = focused.parentNode) {
        if (this.children.includes(focused)) {
          environment.document.activeElement = environment.document.body;
          break;
        }
      }
      this.children.forEach(child => { child.parentNode = null; });
      this.children = [];
      selectedValue = null;
      this.append(...children);
    },
    replaceWith(replacement) {
      if (this.parentNode) {
        const index = this.parentNode.children.indexOf(this);
        assert.notEqual(index, -1);
        this.parentNode.children[index] = replacement;
        replacement.parentNode = this.parentNode;
        this.parentNode = null;
      }
      if (identifier && environment.nodes?.get(identifier) === this) environment.nodes.set(identifier, replacement);
    },
    addEventListener(event, handler) {
      if (!this.listeners.has(event)) this.listeners.set(event, []);
      this.listeners.get(event).push(handler);
    },
    setAttribute(key, value) { this.attributes[key] = String(value); },
    getAttribute(key) { return this.attributes[key] ?? null; },
    removeAttribute(key) { delete this.attributes[key]; },
    querySelectorAll(selector) {
      const tags = selector.split(',').map(value => value.trim().toUpperCase());
      assert(tags.every(value => ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(value)),
        'The named element double supports only explicit native form-control tags.');
      return descendants(this).slice(1).filter(child => tags.includes(child.tagName));
    },
    closest(selector) {
      if (selector === 'label') return this; // Retain the original named static-label double.
      assert.equal(selector, 'article');
      for (let candidate = this; candidate; candidate = candidate.parentNode) if (candidate.tagName === 'ARTICLE') return candidate;
      return null;
    },
    before() {},
    focus() {
      if (environment.document) environment.document.activeElement = this;
      environment.focusEvents?.push(this.id);
    },
    setSelectionRange(start, end, direction = 'none') {
      assert(textControl(), 'Only authored text-input/textarea doubles support text selection.');
      selectionEnd = Math.max(0, Math.min(this.value.length, end));
      selectionStart = Math.max(0, Math.min(selectionEnd, start));
      selectionDirection = ['forward', 'backward'].includes(direction) ? direction : 'none';
    },
  };
  Object.defineProperties(node, {
    id: {
      get() { return identifier; },
      set(next) { identifier = String(next); if (identifier) environment.nodes?.set(identifier, this); },
    },
    value: {
      get() {
        if (this.tagName !== 'SELECT') return value;
        if (selectedValue === null) return this.children[0]?.value || '';
        return this.children.some(option => option.value === selectedValue) ? selectedValue : '';
      },
      set(next) {
        const string = String(next);
        if (this.tagName === 'SELECT') selectedValue = string;
        else {
          value = this.tagName === 'INPUT' ? string.replace(/[\r\n]/g, '') : this.tagName === 'TEXTAREA' ? string.replace(/\r\n?/g, '\n') : string;
          if (textControl()) { selectionStart = selectionEnd = value.length; selectionDirection = 'none'; }
        }
      },
    },
    selectionStart: {get() { return textControl() ? selectionStart : null; }},
    selectionEnd: {get() { return textControl() ? selectionEnd : null; }},
    selectionDirection: {get() { return textControl() ? selectionDirection : null; }},
    // Rendering user text through HTML is outside the allowed contract.
    innerHTML: {set() { assert.fail('The named DOM double forbids innerHTML; render authored text as text/value.'); }},
  });
  return node;
}

async function settle() { await new Promise(resolve => setImmediate(resolve)); }

async function boot({hash = '', stored, accepted = VALID, denied = false, documents = [], jobs = [], bundles = [], workspaces = {}, capabilities,
    expectedMutations = [], expectedReads = [], expectedUploads = [], captureTimers = false, updateCheck} = {}) {
  const nodes = new Map();
  const focusEvents = [];
  const environment = {nodes, focusEvents};
  const createNode = tag => nodeDouble(tag, environment);
  const selectIds = new Set(['group-choice', 'bundle-choice', 'preview-layout', 'new-kind', 'new-ocr', 'new-ocr-profile']);
  const getNode = id => {
    if (!nodes.has(id)) {
      const node = createNode(selectIds.has(id) ? 'select' : 'div');
      node.id = id;
    }
    return nodes.get(id);
  };
  getNode('notice').hidden = true;
  getNode('new-ocr-profile').disabled = true;
  for (const mode of ['off', 'textless', 'skip', 'redo']) {
    const option = createNode('option'); option.value = mode; option.disabled = mode !== 'off';
    getNode('new-ocr').append(option);
  }
  for (const profile of ['standard', 'table-lines', 'angles', 'turns']) {
    const option = createNode('option'); option.value = profile;
    getNode('new-ocr-profile').append(option);
  }
  const body = createNode('body');
  const document = {
    body, activeElement: body,
    getElementById: getNode,
    createElement: createNode,
    createTextNode: text => ({textContent: String(text)}),
    querySelectorAll(selector) {
      const selected = [];
      for (const clause of selector.split(',').map(value => value.trim())) {
        const scope = /^#([a-z0-9-]+)(?: (input|textarea|select|button))?$/.exec(clause);
        if (scope) {
          selected.push(...(scope[2] ? descendants(getNode(scope[1])).slice(1).filter(node => node.tagName === scope[2].toUpperCase()) : [getNode(scope[1])]));
          continue;
        }
        const attribute = /^\[data-(manual|ai)-id\]:(checked|not\(:disabled\))$/.exec(clause);
        assert(attribute, 'The named DOM double must explicitly support the actual selector: ' + clause);
        const all = [...new Set([...nodes.values()].flatMap(descendants))];
        selected.push(...all.filter(node => node.dataset?.[attribute[1] + 'Id'] !== undefined
          && (attribute[2] === 'checked' ? node.checked : !node.disabled)));
      }
      return [...new Set(selected)];
    },
  };
  environment.document = document;
  const storage = new Map(stored === undefined ? [] : [[TOKEN_KEY, stored]]);
  const storageWrites = [];
  const sessionStorage = {
    getItem(key) { return storage.has(key) ? storage.get(key) : null; },
    setItem(key, value) { storageWrites.push([key, String(value)]); storage.set(key, String(value)); },
  };
  const location = {hash, pathname: '/', search: ''};
  const replacements = [];
  const history = {
    replaceState(state, title, url) {
      replacements.push({state, title, url});
      const parsed = new URL(url, 'http://127.0.0.1:49152');
      Object.assign(location, {pathname: parsed.pathname, search: parsed.search, hash: parsed.hash});
    },
  };
  const requests = [];
  const unexpectedRequests = [];
  const mutationRequests = [];
  const uploadRequests = [];
  const remainingUploads = [...expectedUploads];
  const remainingMutations = [...expectedMutations];
  const remainingReads = [...expectedReads];
  const fetch = async (url, options) => {
    requests.push({url, token: options.headers['X-Review-Token']});
    if (url === '/api/upload') {
      const expected = remainingUploads.shift();
      if (!expected) {
        unexpectedRequests.push({url, method: options.method});
        assert.fail('No upload is permitted without an explicitly authored file expectation.');
      }
      assert.equal(options.method, 'POST');
      assert.equal(denied, false);
      assert.equal(options.headers['X-Review-Token'], accepted);
      assert.equal(options.headers['Content-Type'], 'application/pdf');
      assert.equal(options.headers['X-File-Name'], encodeURIComponent(expected.file.name));
      assert.equal(options.body, expected.file, 'Only the exact selected authored file double may be uploaded.');
      uploadRequests.push({url, name: expected.file.name});
      return {ok: true, async json() { return {id: expected.id}; }};
    }
    if (options.method && options.method !== 'GET') {
      const expected = remainingMutations[0];
      if (!expected || options.method !== 'POST' || !(url === '/api/stop' || url === '/api/process' || /^\/api\/jobs\/[A-Za-z0-9_-]+\/cancel$/.test(url) || /\/api\/workspaces\/[a-z0-9]+\/(edit|approve|auto-fix|review|group|retry|ocr-edit|ocr-approve|ocr-apply|ocr-insert|ocr-remove)$/.test(url) || (expected.allowApply === true && url === expected.url && /^\/api\/workspaces\/[a-z0-9]+\/apply$/.test(url)) || (expected.allowCredentialCopy === true && url === expected.url && /^\/api\/workspaces\/[a-z0-9]+\/credential-copy$/.test(url)))) {
        unexpectedRequests.push({url, method: options.method});
        assert.fail('The named HTTP double forbids unauthored mutation requests: ' + options.method + ' ' + url);
      }
      assert.equal(denied, false);
      assert.equal(options.headers['X-Review-Token'], accepted);
      assert.equal(options.headers['Content-Type'], 'application/json');
      assert.equal(url, expected.url, 'Only the explicitly authored mutation endpoint is available.');
      const payload = JSON.parse(options.body);
      assert.deepEqual(payload, expected.payload, 'The explicit operation must bind its exact authored value and current revision.');
      remainingMutations.shift();
      mutationRequests.push({url, payload});
      return {ok: expected.ok !== false, async json() { return expected.response; }};
    }
    const authorized = !denied && options.headers['X-Review-Token'] === accepted;
    if (!authorized) return {ok: false, async json() { return {error: REFUSAL_NOTICE}; }};
    if (remainingReads[0]?.url === url) {
      const expected = remainingReads.shift();
      if (expected.fetchFails) throw new TypeError('Failed to fetch');
      const match = /^\/api\/workspaces\/([a-z0-9]+)(?:\/(context|page|ocr)\?(.*))?$/.exec(url);
      assert(url === '/api/dashboard' || (match && workspaces[match[1]]), 'Only an exact authored dashboard/workspace read can be delayed.');
      if (match?.[2]) {
        const query = new URLSearchParams(match[3]), saved = workspaces[match[1]], page = Number(query.get('page'));
        assert(Number.isInteger(page) && page >= 1 && page <= saved.page_count);
        const keys = [...query.keys()].sort();
        if (match[2] === 'ocr' && query.has('profile')) {
          assert.deepEqual(keys, ['page', 'profile']);
          assert.equal(query.get('profile'), 'expanded-v2');
        } else assert.deepEqual(keys, match[2] === 'page' ? ['kind', 'page'] : ['page']);
        if (match[2] === 'page') assert(['original', 'candidate'].includes(query.get('kind')));
      }
      return {ok: expected.ok !== false, async json() { return expected.response; }, async blob() {
        assert.equal(match?.[2], 'page', 'Only an authored page response has a delayed blob.');
        return expected.response;
      }};
    }
    let payload;
    if (url === '/api/dashboard') payload = {documents, jobs, ...(capabilities === undefined ? {} : {capabilities})};
    else if (url === '/api/bundles') payload = {bundles};
    else if (url === '/api/update-check') {
      if (updateCheck === undefined) {
        unexpectedRequests.push({url, method: 'GET'});
        assert.fail('An update check needs an authored answer.');
      }
      payload = updateCheck;
    }
    else {
      const match = /^\/api\/workspaces\/([a-z0-9]+)(?:\/(context|page|ocr)\?(.*))?$/.exec(url);
      const saved = match && workspaces[match[1]];
      if (!saved) {
        unexpectedRequests.push({url, method: 'GET'});
        assert.fail('Unexpected request outside the named workspace HTTP double: ' + url);
      }
      if (!match[2]) payload = saved;
      else {
        const query = new URLSearchParams(match[3]);
        const page = Number(query.get('page'));
        assert(Number.isInteger(page) && page >= 1 && page <= saved.page_count, 'Only an authored workspace page is available.');
        if (match[2] === 'ocr') {
          unexpectedRequests.push({url, method: 'GET'});
          assert.fail('OCR inventory reads require an exact authored response.');
        } else if (match[2] === 'context') {
          assert.deepEqual([...query.keys()], ['page']);
          payload = {text: 'Authored DOM/HTTP-double context on page ' + page};
        } else {
          assert(['original', 'candidate'].includes(query.get('kind')));
          assert.deepEqual([...query.keys()].sort(), ['kind', 'page']);
          return {ok: true, async blob() { return {authoredImagePlaceholder: true}; }};
        }
      }
    }
    return {
      ok: true,
      async json() { return payload; },
    };
  };
  const objectUrls = [];
  class DoubleURL extends URL {
    static createObjectURL(blob) {
      assert.equal(blob.authoredImagePlaceholder, true);
      const url = 'blob:authored-dom-double-' + objectUrls.length;
      objectUrls.push(url);
      return url;
    }
    static revokeObjectURL(url) { assert(objectUrls.includes(url)); }
  }
  const scheduledTimers = [];
  const schedule = captureTimers ? ((callback, delay) => {
    const timer = {callback, delay, cancelled: false};
    scheduledTimers.push(timer);
    return timer;
  }) : setTimeout;
  const unschedule = captureTimers ? (timer => { timer.cancelled = true; }) : clearTimeout;
  const context = vm.createContext({document, location, history, sessionStorage, fetch, URL: DoubleURL,
    setTimeout: schedule, clearTimeout: unschedule});
  // Execute the entire shipped script, including its real startup API/error paths.
  applicationScript.runInContext(context, {timeout: 1000});
  await settle();
  const dispatch = async (nodeOrId, type, properties = {}) => {
    const node = typeof nodeOrId === 'string' ? getNode(nodeOrId) : nodeOrId;
    const event = {type, target: node, currentTarget: node, defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true; }, ...properties};
    if (!(type === 'click' && node.disabled)) {
      for (const handler of node.listeners.get(type) || []) await handler(event);
    }
    await settle();
    assert.deepEqual(unexpectedRequests, [], 'No request may escape the explicit DOM/HTTP test boundary.');
    return event;
  };
  return {nodes, getNode, document, context, focusEvents, dispatch, storage, storageWrites, location,
    replacements, requests, unexpectedRequests, objectUrls, mutationRequests, remainingMutations, remainingReads, scheduledTimers,
    uploadRequests, remainingUploads};
}

function successful(result, expected = VALID) {
  assert.deepEqual(result.requests, [{url: '/api/dashboard', token: expected}]);
  assert.equal(result.nodes.get('notice').hidden, true);
  assert.equal(result.nodes.get('documents').children[0].textContent, 'No documents yet. Choose a PDF to begin.');
}

function rejected(result, expected) {
  assert.deepEqual(result.requests, [{url: '/api/dashboard', token: expected}]);
  assert.equal(result.nodes.get('notice').textContent, REFUSAL_NOTICE);
  assert.equal(result.nodes.get('notice').hidden, false);
  assert.equal(result.nodes.get('notice').classList.contains('error'), true);
}

test('cold private launch uses, stores and removes supplied authority', async () => {
  const result = await boot({hash: '#' + VALID});
  successful(result);
  assert.equal(result.storage.get(TOKEN_KEY), VALID);
  assert.deepEqual(result.storageWrites, [[TOKEN_KEY, VALID]]);
  assert.equal(result.location.hash, '');
  assert.equal(result.replacements.length, 1);
});

test('bare reload uses the authority stored by a prior launch', async () => {
  const launched = await boot({hash: '#' + VALID});
  const result = await boot({stored: launched.storage.get(TOKEN_KEY)});
  successful(result);
  assert.equal(result.storage.get(TOKEN_KEY), VALID);
});

test('skip target reload retains authority and the navigation fragment', async () => {
  const result = await boot({hash: '#main', stored: VALID});
  successful(result);
  assert.equal(result.storage.get(TOKEN_KEY), VALID);
  assert.deepEqual(result.storageWrites, []);
  assert.equal(result.location.hash, '#main');
  assert.deepEqual(result.replacements, []);
});

test('repeated skip target reload never turns the target into authority', async () => {
  let result = {storage: new Map([[TOKEN_KEY, VALID]])};
  for (let count = 0; count < 3; count++) {
    result = await boot({hash: '#main', stored: result.storage.get(TOKEN_KEY)});
    successful(result);
    assert.equal(result.storage.get(TOKEN_KEY), VALID);
  }
});

test('bare page without saved authority makes no API request and asks for private link', async () => {
  const result = await boot();
  assert.deepEqual(result.requests, []);
  assert.equal(result.nodes.get('notice').textContent, NO_TOKEN_NOTICE);
  assert.equal(result.nodes.get('notice').classList.contains('error'), true);
  assert.equal(result.storage.has(TOKEN_KEY), false);
});

test('skip target without saved authority makes no API request and asks for private link', async () => {
  const result = await boot({hash: '#main'});
  assert.deepEqual(result.requests, []);
  assert.equal(result.nodes.get('notice').textContent, NO_TOKEN_NOTICE);
  assert.equal(result.nodes.get('notice').classList.contains('error'), true);
  assert.equal(result.storage.has(TOKEN_KEY), false);
  assert.equal(result.location.hash, '#main');
});

for (const supplied of [WRONG, 'A'.repeat(43), 'not-valid%20authority', 'stop']) {
  test('explicit non-navigation authority is never replaced by stored valid authority: ' + supplied, async () => {
    const result = await boot({hash: '#' + supplied, stored: VALID});
    rejected(result, supplied);
    assert.equal(result.storage.get(TOKEN_KEY), supplied);
    assert.equal(result.location.hash, '');
  });
}

test('new private launch replaces stale stored authority', async () => {
  const result = await boot({hash: '#' + VALID, stored: STALE});
  successful(result);
  assert.equal(result.storage.get(TOKEN_KEY), VALID);
});

test('stale saved authority with skip navigation still receives the server refusal', async () => {
  const result = await boot({hash: '#main', stored: STALE});
  rejected(result, STALE);
  assert.equal(result.storage.get(TOKEN_KEY), STALE);
});

test('valid-looking supplied authority does not suppress an explicit server refusal', async () => {
  const result = await boot({hash: '#' + VALID, stored: STALE, denied: true});
  rejected(result, VALID);
});

test('saved dashboard row labels prior status and asks to check files without claiming fresh automation', async () => {
  const row = {
    id: 'a'.repeat(24), title: 'Authored <literal> & saved review.pdf', status: 'candidate',
    page_count: 2000, stale: false, artifacts_checked: false,
    counts: {manual_pending: 42, manual_pending_actionable: 0, automated_count: 99},
  };
  const result = await boot({hash: '#' + VALID, documents: [row]});
  assert.deepEqual(result.requests, [{url: '/api/dashboard', token: VALID}]);
  assert.equal(result.nodes.get('notice').hidden, true);
  const cards = result.nodes.get('documents').children;
  assert.equal(cards.length, 1);
  const [title, status, hint] = cards[0].children;
  assert.equal(title.textContent, row.title);
  assert.equal(status.textContent, 'Saved: Ready for review');
  assert.equal(hint.textContent, 'Saved review. Open to check current files.');
  assert.equal(cards[0].listeners.get('click').length, 1);
  assert.equal(row.status, 'candidate', 'Rendering must not mutate the saved server snapshot.');
});

test('saved corrupt-state attention row remains clearly saved and unchecked without counts', async () => {
  const row = {
    id: 'b'.repeat(24), title: 'Review needs attention', status: 'needs-manual',
    error: 'Workspace state changed outside its atomic review operations', artifacts_checked: false,
  };
  const result = await boot({stored: VALID, documents: [row]});
  assert.deepEqual(result.requests, [{url: '/api/dashboard', token: VALID}]);
  assert.equal(result.nodes.get('notice').hidden, true);
  const cards = result.nodes.get('documents').children;
  assert.equal(cards.length, 1);
  const [title, status, hint] = cards[0].children;
  assert.equal(title.textContent, 'Review needs attention');
  assert.equal(status.textContent, 'Saved: Needs attention');
  assert.equal(status.classList.contains('warning'), true);
  assert.equal(hint.textContent, 'Saved review. Open to check current files.');
});

test('saved failed result does not imply a new processing assessment', async () => {
  const result = await boot({stored: VALID, documents: [{
    id: 'c'.repeat(24), title: 'authored-failed-workload.pdf', status: 'failed',
    artifacts_checked: false, page_count: 2000, counts: {manual_pending: 0},
  }]});
  assert.deepEqual(result.requests, [{url: '/api/dashboard', token: VALID}]);
  const [, status, hint] = result.nodes.get('documents').children[0].children;
  assert.equal(status.textContent, 'Saved: Processing failed');
  assert.equal(status.classList.contains('danger'), true);
  assert.equal(hint.textContent, 'Saved review. Open to check current files.');
});

for (const artifacts_checked of [false, true]) {
  test('a confirmed cancelled run has its own saved/current card label: ' + artifacts_checked, async () => {
    const row = {id: 'c'.repeat(24), title: 'authored-reading.pdf', status: 'failed', cancelled: true,
      artifacts_checked, counts: {manual_pending: 0}, page_count: 1};
    const before = JSON.stringify(row);
    const result = await boot({stored: VALID, documents: [row]});
    const [, status, hint] = result.getNode('documents').children[0].children;
    assert.equal(status.textContent, (artifacts_checked ? '' : 'Saved: ') + 'Processing cancelled');
    assert.equal(status.classList.contains('danger'), false);
    if (!artifacts_checked) assert.equal(hint.textContent, 'Saved review. Open to check current files.');
    assert.equal(JSON.stringify(row), before, 'Display metadata must not change the saved processing result.');
    assert.deepEqual(result.mutationRequests, []);
  });
}

for (const cancelled of [undefined, false, 1, 'true']) {
  test('failed cards require a literal confirmed cancellation flag: ' + cancelled, async () => {
    const result = await boot({stored: VALID, documents: [{id: 'c'.repeat(24),
      title: 'filename-says-cancelled.pdf', status: 'failed', cancelled, artifacts_checked: false}]});
    const status = result.getNode('documents').children[0].children[1];
    assert.equal(status.textContent, 'Saved: Processing failed');
    assert.equal(status.classList.contains('danger'), true);
  });
}

for (const [status, expected] of [['candidate', 'Ready for review'], ['needs-manual', 'Needs attention'], ['verified', 'Historical verification']]) {
  test('cancellation metadata cannot override another saved disposition: ' + status, async () => {
    const result = await boot({stored: VALID, documents: [{id: 'c'.repeat(24), title: 'reading.pdf',
      status, cancelled: true, artifacts_checked: false}]});
    assert.equal(result.getNode('documents').children[0].children[1].textContent, 'Saved: ' + expected);
  });
}

test('existing-results choices distinguish cancelled runs and real failures without changing their paths', async () => {
  const bundles = [{name: 'reading.pdf', path: '/authored/cancelled-run', status: 'failed', cancelled: true},
    {name: 'reading.pdf', path: '/authored/failed-run', status: 'failed', cancelled: false},
    {name: 'reading.pdf', path: '/authored/candidate-run', status: 'candidate', cancelled: true}];
  const before = JSON.stringify(bundles);
  const result = await boot({stored: VALID, bundles});
  await result.dispatch('find-results', 'click');
  const options = result.getNode('bundle-choice').children;
  assert.deepEqual(options.map(option => option.textContent), ['reading.pdf · Processing cancelled',
    'reading.pdf · Processing failed', 'reading.pdf · Ready for review']);
  assert.deepEqual(options.map(option => option.value), bundles.map(item => item.path));
  assert.equal(JSON.stringify(bundles), before);
  assert.deepEqual(result.requests.map(item => item.url), ['/api/dashboard', '/api/bundles']);
  assert.deepEqual(result.mutationRequests, []);
});

test('reopened cancelled review keeps Retry available and leaves download disabled', async () => {
  const saved = savedReviewFixture();
  Object.assign(saved, {status: 'failed', historical_status: 'failed', cancelled: true, output: null,
    page_count: 0, decisions: [], manual_items: [], groups: []});
  const before = JSON.stringify(saved);
  const result = await bootSavedReview(saved);
  await openSavedReview(result);
  assert.equal(result.getNode('document-status').textContent, 'Processing cancelled');
  assert.equal(result.getNode('retry').hidden, false);
  assert.equal(result.getNode('retry').disabled, false);
  assert.equal(result.getNode('download').disabled, true);
  assert.equal(result.getNode('apply').disabled, true);
  assert.equal(JSON.stringify(saved), before);
  assert.deepEqual(result.mutationRequests, []);
});

for (const status of ['failed', 'cancelled']) {
  test('terminal job notice and empty-error text keep failure/cancellation distinct: ' + status, async () => {
    const saved = repairControlsFixture(), jobs = [];
    const url = '/api/workspaces/' + saved.workspace_id + '/auto-fix';
    const payload = {revision: 7, consent: true, use_ai: false, ai_consent: false,
      endpoint: '', model: '', include_images: false, reasoning_effort: null};
    const result = await bootSavedReview(saved, {jobs, captureTimers: true,
      expectedMutations: [{url, payload, response: {job_id: 'authored-terminal-job'}}]});
    await openSavedReview(result);
    await result.dispatch('auto-fix', 'click');
    jobs.push({id: 'authored-terminal-job', label: 'Authored processing job', status, progress: [], error: null});
    const before = JSON.stringify(jobs);
    await result.scheduledTimers[0].callback();
    await settle();
    const notice = result.getNode('notice');
    assert.equal(notice.textContent, status === 'cancelled' ? 'Processing was cancelled; no unfinished result was released.'
      : 'Processing failed and no reason was reported. Try again; if it keeps failing, application.log in the review-app folder has the details.');
    assert.equal(notice.classList.contains('error'), status === 'failed');
    assert.equal(result.getNode('auto-status').hidden, true);
    assert.equal(result.getNode('job-bar').hidden, true);
    assert.equal(JSON.stringify(jobs), before);
    assert.deepEqual(result.mutationRequests, [{url, payload}]);
    assert.deepEqual(result.remainingMutations, []);
    assert.deepEqual(result.unexpectedRequests, []);
  });
}

test('a scan whose saved evidence no longer matches is explained in plain words, with the detail kept', async () => {
  const saved = repairControlsFixture(), jobs = [];
  const url = '/api/workspaces/' + saved.workspace_id + '/auto-fix';
  const payload = {revision: 7, consent: true, use_ai: false, ai_consent: false,
    endpoint: '', model: '', include_images: false, reasoning_effort: null};
  const result = await bootSavedReview(saved, {jobs, captureTimers: true,
    expectedMutations: [{url, payload, response: {job_id: 'stale-evidence-job'}}]});
  await openSavedReview(result);
  await result.dispatch('auto-fix', 'click');
  jobs.push({id: 'stale-evidence-job', label: 'Authored processing job', status: 'failed', progress: [],
    error: 'Cannot import stale evidence: Prepared PDF decision occurrence context changed'});
  await result.scheduledTimers[0].callback();
  await settle();
  const notice = result.getNode('notice');
  assert.equal(notice.textContent, 'The scan finished, but its result could not be opened safely because the saved checks no longer matched the processed file. '
    + 'Nothing was changed or released. Process the PDF again. (Detail: Prepared PDF decision occurrence context changed)');
  assert.equal(notice.classList.contains('error'), true);
  assert.equal(notice.textContent.includes('Cannot import stale evidence'), false);
});

test('a worker that dies without a report is explained in plain words', async () => {
  const saved = repairControlsFixture(), jobs = [];
  const url = '/api/workspaces/' + saved.workspace_id + '/auto-fix';
  const payload = {revision: 7, consent: true, use_ai: false, ai_consent: false,
    endpoint: '', model: '', include_images: false, reasoning_effort: null};
  const result = await bootSavedReview(saved, {jobs, captureTimers: true,
    expectedMutations: [{url, payload, response: {job_id: 'worker-gone-job'}}]});
  await openSavedReview(result);
  await result.dispatch('auto-fix', 'click');
  jobs.push({id: 'worker-gone-job', label: 'Authored processing job', status: 'failed', progress: [],
    error: 'The document worker ended without a completed report.'});
  await result.scheduledTimers[0].callback();
  await settle();
  const notice = result.getNode('notice');
  assert.equal(notice.textContent, 'The part of the program that reads PDFs stopped unexpectedly before it finished. Nothing was changed or released. '
    + 'Try again; if it keeps happening, restart the computer and try once more.');
  assert.equal(notice.classList.contains('error'), true);
});

test('Letter dictionary HTML: the box starts off and the dialog explains the repair in plain words with both choices', () => {
  const html = fs.readFileSync(path.join(path.dirname(appPath), 'index.html'), 'utf8');
  assert.match(html, /<input id="new-ocrmap" type="checkbox"[^>]*>/);
  assert.doesNotMatch(html, /id="new-ocrmap"[^>]*checked/);
  const dialog = /<dialog id="ocrmap-dialog"[\s\S]*?<\/dialog>/.exec(html);
  assert(dialog, 'The explanation dialog is part of the page.');
  assert.match(dialog[0], /<form method="dialog">/);
  assert.match(dialog[0], /No page picture or page box changes, and your original PDF is never changed\./);
  assert.match(dialog[0], /The result is an inference from the reading, not a fact\./);
  assert.match(dialog[0], /<button value="allow" class="primary">Rebuild the dictionary<\/button>/);
  assert.match(dialog[0], /<button value="keep" class="secondary">Not now<\/button>/);
});

test('Letter dictionary: needs the OCR components, so the box is off and switched off without them', async () => {
  const without = await boot({stored: VALID, capabilities: ocrCapability(false)});
  assert.equal(without.getNode('new-ocrmap').disabled, true);
  const withOcr = await boot({stored: VALID, capabilities: ocrCapability(true)});
  assert.equal(withOcr.getNode('new-ocrmap').disabled, false);
});

test('Letter dictionary consent: the box stays checked only after the dialog answers yes; every other way out unchecks it', async () => {
  const result = await boot({stored: VALID, capabilities: ocrCapability(true)});
  const dialog = result.getNode('ocrmap-dialog'), box = result.getNode('new-ocrmap');
  let shown = 0;
  dialog.showModal = () => { shown += 1; };
  box.checked = true;
  await result.dispatch('new-ocrmap', 'change');
  assert.equal(shown, 1, 'Checking the box opens the explanation.');
  dialog.returnValue = 'allow';
  await result.dispatch('ocrmap-dialog', 'close');
  assert.equal(box.checked, true);
  box.checked = false;
  await result.dispatch('new-ocrmap', 'change');
  for (const answer of ['keep', '']) {
    box.checked = true;
    await result.dispatch('new-ocrmap', 'change');
    dialog.returnValue = answer;
    await result.dispatch('ocrmap-dialog', 'close');
    assert.equal(box.checked, false, 'Answer "' + answer + '" must leave the letter dictionary alone.');
    assert.equal(result.getNode('new-ocr').disabled, false);
  }
  assert.equal(shown, 3, 'Unchecking never opens the dialog.');
});

test('Letter dictionary consent: a browser that cannot show the dialog leaves it alone and says so', async () => {
  const result = await boot({stored: VALID, capabilities: ocrCapability(true)});
  const box = result.getNode('new-ocrmap');
  box.checked = true;
  await result.dispatch('new-ocrmap', 'change');
  assert.equal(box.checked, false);
  assert.match(result.getNode('notice').textContent, /left alone/);
});

test('Letter dictionary works on its own: while it is on, scanned-text reading and mapping corrections are off and locked; off again frees them', async () => {
  const result = await boot({stored: VALID, capabilities: ocrCapability(true)});
  const dialog = result.getNode('ocrmap-dialog'), box = result.getNode('new-ocrmap');
  dialog.showModal = () => {};
  result.getNode('new-ocr').value = 'textless';
  result.getNode('new-mapping').checked = true;
  box.checked = true;
  await result.dispatch('new-ocrmap', 'change');
  dialog.returnValue = 'allow';
  await result.dispatch('ocrmap-dialog', 'close');
  assert.equal(result.getNode('new-ocr').value, 'off');
  assert.equal(result.getNode('new-ocr').disabled, true);
  assert.equal(result.getNode('new-mapping').checked, false);
  assert.equal(result.getNode('new-mapping').disabled, true);
  assert.equal(result.getNode('new-ocr-profile').disabled, true);
  box.checked = false;
  await result.dispatch('new-ocrmap', 'change');
  assert.equal(result.getNode('new-ocr').disabled, false);
  assert.equal(result.getNode('new-mapping').disabled, false);
});

test('Letter dictionary: Reset choices switches it off and frees the other options', async () => {
  const result = await boot({stored: VALID, capabilities: ocrCapability(true)});
  const dialog = result.getNode('ocrmap-dialog'), box = result.getNode('new-ocrmap');
  dialog.showModal = () => {};
  box.checked = true;
  await result.dispatch('new-ocrmap', 'change');
  dialog.returnValue = 'allow';
  await result.dispatch('ocrmap-dialog', 'close');
  assert.equal(result.getNode('new-ocr').disabled, true);
  await result.dispatch('reset-start', 'click');
  await settle();
  assert.equal(box.checked, false);
  assert.equal(result.getNode('new-ocr').disabled, false);
  assert.equal(result.getNode('new-mapping').disabled, false);
});

test('Letter dictionary consent: an allowed repair travels in the exact process request, alone', async () => {
  const file = {name: 'Authored odd symbols.pdf', size: 64, authoredFileDouble: true};
  const payload = {inputs: ['authored-ocrmap-id'], options: {language: 'en-US', document_kind: 'unknown', ocr_mode: 'off', ocr_profile: 'standard',
    allow_tag_regrouping: false, repair_source_mappings: false, remove_cidset: false, repair_ocr_mappings: true}};
  const result = await boot({stored: VALID, capabilities: ocrCapability(true), captureTimers: true,
    expectedUploads: [{file, id: 'authored-ocrmap-id'}],
    expectedMutations: [{url: '/api/process', payload, response: {job_id: 'authored-ocrmap-job'}}]});
  const dialog = result.getNode('ocrmap-dialog');
  dialog.showModal = () => {};
  result.getNode('files').files = [file];
  await result.dispatch('files', 'change');
  result.getNode('new-language').value = 'en-US';
  const kind = result.document.createElement('option'); kind.value = 'unknown';
  result.getNode('new-kind').append(kind);
  result.getNode('new-ocrmap').checked = true;
  await result.dispatch('new-ocrmap', 'change');
  dialog.returnValue = 'allow';
  await result.dispatch('ocrmap-dialog', 'close');
  await result.dispatch('process', 'click');
  assert.deepEqual(result.mutationRequests, [{url: '/api/process', payload}]);
  assert.deepEqual(result.remainingMutations, []);
});

for (const profile of ['angles', 'turns']) {
  test('OCR ' + profile + ' layout with the mixed-page option is refused on the page before anything is sent', async () => {
    const file = {name: 'Authored sideways scan.pdf', size: 64, authoredFileDouble: true};
    const result = await boot({stored: VALID, capabilities: ocrCapability(true)});
    result.getNode('new-ocr').value = 'redo';
    await result.dispatch('new-ocr', 'change');
    result.getNode('new-ocr-profile').value = profile;
    result.getNode('files').files = [file];
    await result.dispatch('files', 'change');
    await result.dispatch('process', 'click');
    await settle();
    assert.match(result.getNode('notice').textContent, /choose the wholly scanned pages or scan-only OCR option/);
    assert.equal(result.getNode('notice').classList.contains('error'), true);
    assert.deepEqual(result.mutationRequests, []);
  });
}

test('Leave dialog HTML: stays by default, explains the loss and keeps saved work', () => {
  const html = fs.readFileSync(path.join(path.dirname(appPath), 'index.html'), 'utf8');
  const dialog = /<dialog id="leave-dialog"[\s\S]*?<\/dialog>/.exec(html);
  assert(dialog, 'The dialog is part of the page.');
  assert.match(dialog[0], /Some fields in this review have been changed but not saved\. If you leave now, those changes are lost\. Anything you already saved or accepted stays\./);
  assert.match(dialog[0], /<button value="stay" class="primary" autofocus>Stay and keep editing<\/button>/);
  assert.match(dialog[0], /<button value="leave" class="secondary">Leave without saving<\/button>/);
});

for (const control of ['back', 'home-button', 'home-link', 'reset-button']) {
  test('Unsaved fields: ' + control + ' asks first and stays when the answer is not "leave"', async () => {
    const result = await bootSavedReview(savedReviewFixture());
    await openSavedReview(result);
    const card = result.document.createElement('div');
    card.hasUnsavedDecision = () => true;
    result.getNode('decisions').append(card);
    const dialog = result.getNode('leave-dialog');
    let shown = 0;
    dialog.showModal = () => { shown += 1; };
    for (const answer of ['stay', '']) {
      const pending = result.dispatch(control, 'click');
      await settle();
      dialog.returnValue = answer;
      await result.dispatch('leave-dialog', 'close');
      await pending;
      await settle();
      assert.equal(result.getNode('review').hidden, false, 'Answer "' + answer + '" must leave the review open.');
    }
    assert.equal(shown, 2, 'Each click asked once.');
    assert.deepEqual(result.mutationRequests, [], 'Staying sends nothing to the service.');
  });
}

for (const control of ['back', 'home-button', 'reset-button']) {
  test('Unsaved fields: ' + control + ' leaves only after "Leave without saving"', async () => {
    const result = await bootSavedReview(savedReviewFixture());
    await openSavedReview(result);
    const card = result.document.createElement('div');
    card.hasUnsavedDecision = () => true;
    result.getNode('decisions').append(card);
    const dialog = result.getNode('leave-dialog');
    dialog.showModal = () => {};
    const pending = result.dispatch(control, 'click');
    await settle();
    dialog.returnValue = 'leave';
    await result.dispatch('leave-dialog', 'close');
    await pending;
    await settle();
    assert.equal(result.getNode('review').hidden, true);
    assert.equal(result.getNode('dashboard').hidden, false);
  });
}

test('Unsaved fields: with nothing unsaved, leaving never opens the dialog', async () => {
  const result = await bootSavedReview(savedReviewFixture());
  await openSavedReview(result);
  const dialog = result.getNode('leave-dialog');
  let shown = 0;
  dialog.showModal = () => { shown += 1; };
  await result.dispatch('back', 'click');
  await settle();
  assert.equal(shown, 0);
  assert.equal(result.getNode('review').hidden, true);
});

test('Unsaved fields: a browser that cannot show the dialog keeps the review open and says why', async () => {
  const result = await bootSavedReview(savedReviewFixture());
  await openSavedReview(result);
  const card = result.document.createElement('div');
  card.hasUnsavedDecision = () => true;
  result.getNode('decisions').append(card);
  await result.dispatch('back', 'click');
  await settle();
  assert.equal(result.getNode('review').hidden, false);
  assert.match(result.getNode('notice').textContent, /unsaved fields in this review/);
});

for (const artifacts_checked of [true, undefined]) {
  test('only explicit artifacts_checked false changes dashboard labeling: ' + artifacts_checked, async () => {
    const result = await boot({stored: VALID, documents: [{
      id: 'd'.repeat(24), title: 'ordinary-row.pdf', status: 'candidate', page_count: 1,
      artifacts_checked, counts: {manual_pending_actionable: 5, automated_count: 2},
    }]});
    const [, status, hint] = result.nodes.get('documents').children[0].children;
    assert.equal(status.textContent, 'Ready for review');
    assert.equal(hint.textContent, '1 pages · 5 checks waiting · 2 handled automatically');
  });
}

function savedReviewFixture() {
  const manual = [
    {id: 'figure-occurrence-a', category: 'figure-meaning', subject: 'Repeated figure',
      status: 'blocked', notes: 'First occurrence: the vertical scale is unexplained.', resolved_pages: [1],
      detail: 'Authored first-page occurrence', evidence: {occurrence: 'page-1-image-2'}, automatic_handled: false},
    {id: 'figure-occurrence-b', category: 'figure-meaning', subject: 'Repeated figure',
      status: 'pending', notes: 'Second occurrence: check its different nearby explanation.', resolved_pages: [2],
      detail: 'Authored second-page occurrence', evidence: {occurrence: 'page-2-image-1'}, automatic_handled: false},
    {id: 'reading-order-c', category: 'reading-order', subject: 'Reading order',
      status: 'blocked', notes: 'The caption should follow this paragraph.', resolved_pages: [2],
      detail: 'Authored reading-order occurrence', evidence: {occurrence: 'page-2-paragraph-3'}, automatic_handled: false},
  ];
  const group = (id, category, items) => ({id, category, kind: 'manual', label: category,
    pattern: {}, member_ids: items.map(item => item.id), membership_digest: 'authored-' + id,
    counts: {total: items.length, pending: items.filter(item => item.status === 'pending').length},
    pages: [...new Set(items.flatMap(item => item.resolved_pages))]});
  return {
    workspace_id: 'e'.repeat(24), revision: 7, status: 'needs-manual', historical_status: 'candidate',
    source: {path: '/authored/notes-review.pdf'}, output: {path: '/authored/candidate.pdf'},
    stale: false, page_count: 2, banner: 'Authored saved review; human verification is still separate.',
    counts: {manual_pending: 1, manual_approved: 0}, decisions: [], unapplied_decisions: [],
    blockers: [], suggestions: [], manual_items: manual,
    groups: [group('figures', 'figure-meaning', manual.slice(0, 2)), group('order', 'reading-order', manual.slice(2))],
  };
}

async function bootSavedReview(saved, options = {}) {
  return boot({stored: VALID, documents: [{id: saved.workspace_id, title: 'Authored saved notes.pdf',
    status: saved.status, page_count: saved.page_count, counts: saved.counts, artifacts_checked: false}],
    workspaces: {[saved.workspace_id]: saved}, ...options});
}

async function openSavedReview(result) {
  assert.equal(result.nodes.get('documents').children.length, 1);
  await result.dispatch(result.nodes.get('documents').children[0], 'click');
  assert.equal(result.nodes.get('notice').hidden, true, 'Opening must not hide a renderer/API error in a notice.');
  assert.equal(result.nodes.get('dashboard').hidden, true);
  assert.equal(result.nodes.get('review').hidden, false);
}

function manualCards(result) { return result.nodes.get('manual-items').children; }

function notesInput(card) {
  const matches = card.children.filter(node => node.tagName === 'INPUT' && node.placeholder === 'Describe a problem you found');
  assert.equal(matches.length, 1, 'Each actual rendered occurrence has one problem-note input.');
  return matches[0];
}

function assertSavedNotes(result, items) {
  const cards = manualCards(result);
  assert.equal(cards.length, items.length);
  for (const [index, item] of items.entries()) {
    const card = cards[index];
    assert.equal(card.dataset.reviewId, item.id);
    const note = notesInput(card);
    assert.equal(note.value, item.notes ?? '', 'Saved note must render for ' + item.id);
    assert.equal(note.attributes['aria-label'], 'Problem notes for ' + (item.subject || item.id));
    assert.equal(card.children[0].children[1].textContent, item.status);
    assert.equal(card.children[0].children[0].children[0].checked, false, 'Rendering cannot silently select an occurrence for approval.');
  }
  assert.equal(result.nodes.get('review-confirm').checked, false);
  assert.deepEqual(result.unexpectedRequests, []);
  assert(result.requests.every(request => request.token === VALID));
}

function assertSavedSnapshotUnchanged(result, saved, before) {
  assert.equal(JSON.stringify(saved), before, 'Rendering/navigation cannot mutate the supplied saved-review API snapshot.');
  assert.deepEqual(result.unexpectedRequests, [], 'Rendering/navigation cannot make review, approval, Apply or provider requests.');
}

test('DOM/HTTP doubles: opening saved same-subject occurrences renders each note and blocked/pending status without approval', async () => {
  const saved = savedReviewFixture(), before = JSON.stringify(saved);
  const result = await bootSavedReview(saved);
  await openSavedReview(result);
  assert.equal(result.nodes.get('group-choice').value, 'figures');
  assertSavedNotes(result, saved.manual_items.slice(0, 2));
  assert.equal(result.nodes.get('review-count').textContent, '1 pending · 0 approved checks');
  assert.deepEqual(result.requests.map(request => request.url), [
    '/api/dashboard', '/api/workspaces/' + saved.workspace_id,
    '/api/workspaces/' + saved.workspace_id + '/page?kind=original&page=1',
    '/api/workspaces/' + saved.workspace_id + '/page?kind=candidate&page=1',
    '/api/workspaces/' + saved.workspace_id + '/context?page=1',
  ]);
  assertSavedSnapshotUnchanged(result, saved, before);
});

test('DOM/HTTP doubles: actual group-change listeners recreate the right notes and reset selection/confirmation', async () => {
  const saved = savedReviewFixture(), before = JSON.stringify(saved);
  const result = await bootSavedReview(saved);
  await openSavedReview(result);
  const oldCards = [...manualCards(result)];
  oldCards[0].children[0].children[0].children[0].checked = true;
  result.nodes.get('review-confirm').checked = true;
  const requestCount = result.requests.length;
  result.nodes.get('group-choice').value = 'order';
  await result.dispatch('group-choice', 'change');
  assertSavedNotes(result, saved.manual_items.slice(2));
  result.nodes.get('review-confirm').checked = true;
  result.nodes.get('group-choice').value = 'figures';
  await result.dispatch('group-choice', 'change');
  assertSavedNotes(result, saved.manual_items.slice(0, 2));
  assert.notEqual(manualCards(result)[0], oldCards[0], 'The test must inspect newly rendered cards rather than retained old DOM.');
  assert.equal(result.requests.length, requestCount, 'Changing a group is read-only local rendering.');
  assertSavedSnapshotUnchanged(result, saved, before);
});

test('DOM/HTTP doubles: group refresh through actual automatic-filter listener retains saved notes in the selected group', async () => {
  const saved = savedReviewFixture(), before = JSON.stringify(saved);
  const result = await bootSavedReview(saved);
  await openSavedReview(result);
  result.nodes.get('group-choice').value = 'order';
  await result.dispatch('group-choice', 'change');
  const previous = manualCards(result)[0];
  result.nodes.get('show-automatic').checked = true;
  await result.dispatch('show-automatic', 'change');
  assert.equal(result.nodes.get('group-choice').value, 'order');
  assertSavedNotes(result, saved.manual_items.slice(2));
  assert.notEqual(manualCards(result)[0], previous);
  assertSavedSnapshotUnchanged(result, saved, before);
});

test('DOM/HTTP doubles: dashboard Back and Open fetch saved notes again without changing review revision/statuses', async () => {
  const saved = savedReviewFixture(), before = JSON.stringify(saved);
  const result = await bootSavedReview(saved);
  await openSavedReview(result);
  assertSavedNotes(result, saved.manual_items.slice(0, 2));
  const first = manualCards(result)[0];
  await result.dispatch('back', 'click');
  assert.equal(result.nodes.get('dashboard').hidden, false);
  assert.equal(result.nodes.get('review').hidden, true);
  assert.equal(result.focusEvents.at(-1), 'main');
  await openSavedReview(result);
  assertSavedNotes(result, saved.manual_items.slice(0, 2));
  assert.notEqual(manualCards(result)[0], first);
  assert.equal(result.requests.filter(request => request.url === '/api/workspaces/' + saved.workspace_id).length, 2);
  assert.equal(saved.revision, 7);
  assertSavedSnapshotUnchanged(result, saved, before);
});

test('DOM/HTTP doubles: a fresh script boot after skip-target reload retrieves saved occurrence notes', async () => {
  const saved = savedReviewFixture(), before = JSON.stringify(saved);
  const first = await bootSavedReview(saved, {hash: '#' + VALID});
  await openSavedReview(first);
  const reloaded = await bootSavedReview(saved, {hash: '#main', stored: first.storage.get(TOKEN_KEY)});
  await openSavedReview(reloaded);
  assertSavedNotes(reloaded, saved.manual_items.slice(0, 2));
  assert.notEqual(notesInput(manualCards(reloaded)[0]), notesInput(manualCards(first)[0]));
  assert.equal(reloaded.location.hash, '#main');
  assert.deepEqual(reloaded.storageWrites, []);
  assertSavedSnapshotUnchanged(first, saved, before);
  assertSavedSnapshotUnchanged(reloaded, saved, before);
});

test('DOM/HTTP doubles: absent, null and empty saved notes render empty without borrowing another occurrence value', async () => {
  const saved = savedReviewFixture();
  delete saved.manual_items[0].notes;
  saved.manual_items[1].notes = null;
  saved.manual_items[2].notes = '';
  const before = JSON.stringify(saved), result = await bootSavedReview(saved);
  await openSavedReview(result);
  assertSavedNotes(result, saved.manual_items.slice(0, 2));
  result.nodes.get('group-choice').value = 'order';
  await result.dispatch('group-choice', 'change');
  assertSavedNotes(result, saved.manual_items.slice(2));
  assertSavedSnapshotUnchanged(result, saved, before);
});

test('DOM/HTTP doubles: HTML-looking saved notes remain exact literal input text without HTML children', async () => {
  const saved = savedReviewFixture();
  saved.manual_items[0].notes = '<img src=x onerror="throw new Error(\'authored\')"> & "quoted" <script>authored()</script>';
  const before = JSON.stringify(saved), result = await bootSavedReview(saved);
  await openSavedReview(result);
  assertSavedNotes(result, saved.manual_items.slice(0, 2));
  assert.deepEqual(notesInput(manualCards(result)[0]).children, []);
  assertSavedSnapshotUnchanged(result, saved, before);
});

async function selectedTab(name) {
  const result = await boot({stored: VALID});
  // The double does not parse index.html: establish selection through the real
  // click listener, then focus the event target before testing keyboard behavior.
  await result.dispatch('tab-' + name, 'click');
  result.getNode('tab-' + name).focus();
  result.focusEvents.length = 0;
  return result;
}

function tabSnapshot(result) {
  return {
    tabs: ['decisions', 'checks'].map(name => ({
      selected: result.getNode('tab-' + name).attributes['aria-selected'],
      tabIndex: result.getNode('tab-' + name).tabIndex,
      panelHidden: result.getNode('panel-' + name).hidden,
    })),
    focused: result.document.activeElement.id,
    focusEvents: [...result.focusEvents],
  };
}

function keyEvent(key, modifiers = {}) {
  return {key, ctrlKey: false, altKey: false, metaKey: false, shiftKey: false,
    ...modifiers, preventionCount: 0,
    preventDefault() { this.defaultPrevented = true; this.preventionCount++; }};
}

const bareTabKeys = [
  ['decisions', 'ArrowLeft', 'checks'], ['decisions', 'ArrowRight', 'checks'],
  ['decisions', 'Home', 'decisions'], ['decisions', 'End', 'checks'],
  ['checks', 'ArrowLeft', 'decisions'], ['checks', 'ArrowRight', 'decisions'],
  ['checks', 'Home', 'decisions'], ['checks', 'End', 'checks'],
];
for (const [from, key, target] of bareTabKeys) {
  test(`DOM keyboard events: bare ${key} from ${from} selects/focuses ${target} with one tab stop`, async () => {
    const result = await selectedTab(from);
    const event = await result.dispatch('tab-' + from, 'keydown', keyEvent(key));
    assert.equal(event.defaultPrevented, true);
    assert.equal(event.preventionCount, 1);
    for (const name of ['decisions', 'checks']) {
      const selected = name === target;
      assert.equal(result.getNode('tab-' + name).attributes['aria-selected'], String(selected));
      assert.equal(result.getNode('tab-' + name).tabIndex, selected ? 0 : -1);
      assert.equal(result.getNode('panel-' + name).hidden, !selected);
    }
    assert.equal(result.document.activeElement, result.getNode('tab-' + target));
    assert.deepEqual(result.focusEvents, ['tab-' + target]);
  });
}

for (const modifier of ['ctrlKey', 'altKey', 'metaKey', 'shiftKey']) {
  test(`DOM keyboard events: ${modifier} shortcuts retain browser/assistive-technology handling`, async () => {
    for (const from of ['decisions', 'checks']) {
      for (const key of ['ArrowLeft', 'ArrowRight', 'Home', 'End']) {
        const result = await selectedTab(from), before = tabSnapshot(result);
        const event = await result.dispatch('tab-' + from, 'keydown', keyEvent(key, {[modifier]: true}));
        assert.equal(event.defaultPrevented, false, `${modifier} + ${key} from ${from}`);
        assert.equal(event.preventionCount, 0);
        assert.deepEqual(tabSnapshot(result), before, 'A modified shortcut must not move focus, select a tab or change a panel.');
      }
    }
  });
}

test('DOM keyboard events: combined modifiers pass through without tab or focus changes', async () => {
  const result = await selectedTab('checks'), before = tabSnapshot(result);
  const event = await result.dispatch('tab-checks', 'keydown', keyEvent('Home', {ctrlKey: true, shiftKey: true}));
  assert.equal(event.defaultPrevented, false);
  assert.equal(event.preventionCount, 0);
  assert.deepEqual(tabSnapshot(result), before);
});

test('DOM keyboard events: unrelated keys remain untouched on both tabs', async () => {
  for (const from of ['decisions', 'checks']) {
    for (const key of ['Tab', 'Enter', 'Escape', 'ArrowUp', 'ArrowDown', 'PageUp', 'PageDown', 'a', ' ']) {
      const result = await selectedTab(from), before = tabSnapshot(result);
      const event = await result.dispatch('tab-' + from, 'keydown', keyEvent(key));
      assert.equal(event.defaultPrevented, false, `${key} from ${from}`);
      assert.equal(event.preventionCount, 0);
      assert.deepEqual(tabSnapshot(result), before);
    }
  }
});

// Authored current/legacy review views for the new bounded repair controls.
// The double allows exact named edit/approve responses and a mechanical-only
// job-start placeholder only when a case supplies them. It never implements
// Apply, provider requests, PDF writes or unrequested approvals. All controls
// are reached through the real startup/listeners.
const LITERAL_CONTEXT = '<img src=x onerror="authored()"> & <script>authored()</script>';

function repairControlsFixture() {
  const saved = savedReviewFixture();
  const common = {status: 'pending', human_touched: false, context_sha256: 'a'.repeat(64),
    references: [{page: 1, stream: 'page', mcid: 3}], structure_path: 'root/K/0'};
  saved.decisions = [
    {id: 'title-control', kind: 'title', current: 'Authored title', value: 'Authored title', status: 'pending'},
    {id: 'language-control', kind: 'language', current: 'en-US', value: 'en-US', status: 'pending'},
    {...common, id: 'heading-one', kind: 'heading-tag', page: 1, current: 'P', value: 'H2',
      structural_eligible: true, structural_limitations: [], context_text: LITERAL_CONTEXT},
    {...common, id: 'table-one', kind: 'table-header', page: 1,
      current: '{"role":"TD","scope":null}', value: '{"role":"TD","scope":null}',
      structural_eligible: true, structural_limitations: [], context_text: 'Authored first-page table cell'},
    {...common, id: 'heading-two', kind: 'heading-tag', page: 2, current: 'H3', value: 'H3',
      structural_eligible: true, structural_limitations: [], context_text: 'Authored second-page heading'},
    {...common, id: 'table-two', kind: 'table-header', page: 2,
      current: '{"role":"TH","scope":"Row"}', value: '{"role":"TH","scope":"Row"}',
      structural_eligible: true, structural_limitations: [], context_text: 'Authored second-page table cell'},
    {...common, id: 'unsafe-heading', kind: 'heading-tag', page: 1, current: 'H8', value: 'H8',
      structural_eligible: false, structural_limitations: ['Ambiguous content references: ' + LITERAL_CONTEXT],
      context_text: 'Unsafe source element'},
  ];
  saved.repair_findings = [
    {id: 'language-correctness', status: 'fail', evidence: {suggested_language: 'es',
      scope: 'Authored supported mismatch only', literal: LITERAL_CONTEXT}},
    {id: 'contrast', status: 'needs-review', evidence: {measurements: [
      {status: 'fail', ratio: 2.25, minimum_ratio: 4.5, page: 2,
        source_edit_suggestion: {suggested_foreground_rgb: [0, 0, 0], suggested_ratio: 21,
          minimum_ratio: 4.5, review_required: true, automatically_applied: false}},
    ], complete_document_coverage: false, literal: LITERAL_CONTEXT}},
  ];
  return saved;
}

function descendants(node) { return [node, ...(node.children || []).flatMap(descendants)]; }
function decisionCards(result) { return result.getNode('decisions').children.filter(node => node.dataset.decisionId); }
function cardFor(result, id) {
  const cards = decisionCards(result).filter(node => node.dataset.decisionId === id);
  assert.equal(cards.length, 1, 'Exactly one rendered decision is bound to ' + id);
  return cards[0];
}
function selectsFor(card) { return descendants(card).filter(node => node.tagName === 'SELECT'); }
function buttonNamed(root, text) {
  const matches = descendants(root).filter(node => node.tagName === 'BUTTON' && node.textContent === text);
  assert.equal(matches.length, 1, 'Exactly one button has the authored label: ' + text);
  return matches[0];
}
async function showStructure(result, checked = true) {
  result.getNode('show-structure').checked = checked;
  await result.dispatch('show-structure', 'change');
}
function editedView(saved, id, value, revision = saved.revision + 1) {
  const response = structuredClone(saved);
  response.revision = revision;
  const decision = response.decisions.find(item => item.id === id);
  decision.value = value;
  decision.status = 'pending';
  decision.human_touched = true;
  response.unapplied_decisions = [id];
  return response;
}
function expectOnlyMutations(result, mutations) {
  assert.deepEqual(result.mutationRequests, mutations);
  assert.deepEqual(result.remainingMutations, [], 'Every explicitly authored mutation must be reached.');
  assert.deepEqual(result.unexpectedRequests, []);
  assert(!result.requests.some(item => /\/(apply|group|auto-fix|accept-draft)$|\/models/.test(item.url)),
    'These controls never apply, group-approve, invoke automatic fixes or contact a provider.');
}

test('DOM repair controls: legacy views without repair_findings retain old notes and do not invent repairs', async () => {
  const saved = savedReviewFixture(), before = JSON.stringify(saved);
  const result = await bootSavedReview(saved);
  await openSavedReview(result);
  assert.equal(result.getNode('repair-findings').hidden, true);
  assert.deepEqual(result.getNode('repair-findings').children, []);
  assert.match(result.getNode('structure-summary').textContent, /no structure repair controls/);
  assertSavedNotes(result, saved.manual_items.slice(0, 2));
  assertSavedSnapshotUnchanged(result, saved, before);
  expectOnlyMutations(result, []);
});

test('DOM repair controls: collapse and actual page listeners filter structural controls without saving or accepting', async () => {
  const saved = repairControlsFixture(), before = JSON.stringify(saved);
  const result = await bootSavedReview(saved);
  await openSavedReview(result);
  assert.deepEqual(decisionCards(result).map(card => card.dataset.decisionId), ['title-control', 'language-control']);
  assert.match(result.getNode('structure-summary').textContent, /^3 structure controls on page 1\./);
  await showStructure(result);
  assert.deepEqual(decisionCards(result).map(card => card.dataset.decisionId),
    ['title-control', 'language-control', 'heading-one', 'table-one', 'unsafe-heading']);
  await result.dispatch('next-page', 'click');
  assert.equal(result.getNode('page-number').value, '2');
  assert.match(result.getNode('structure-summary').textContent, /^2 structure controls on page 2\./);
  assert.deepEqual(decisionCards(result).map(card => card.dataset.decisionId),
    ['title-control', 'language-control', 'heading-two', 'table-two']);
  assert.deepEqual(selectsFor(cardFor(result, 'table-two')).map(select => select.value), ['TH', 'Row']);
  await result.dispatch('previous-page', 'click');
  assert.equal(cardFor(result, 'heading-one').dataset.decisionId, 'heading-one');
  await showStructure(result, false);
  assert.deepEqual(decisionCards(result).map(card => card.dataset.decisionId), ['title-control', 'language-control']);
  assertSavedSnapshotUnchanged(result, saved, before);
  expectOnlyMutations(result, []);
});

test('DOM repair controls: heading select retains the saved draft and sends the exact value only on Save edit', async () => {
  const saved = repairControlsFixture(), before = JSON.stringify(saved);
  const url = '/api/workspaces/' + saved.workspace_id + '/edit';
  const payload = {revision: 7, id: 'heading-one', value: 'H3'};
  const response = editedView(saved, 'heading-one', 'H3');
  const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response}]});
  await openSavedReview(result);
  await showStructure(result);
  const card = cardFor(result, 'heading-one'), [select] = selectsFor(card);
  assert.equal(select.value, 'H2', 'The draft selects H2 even though the current artifact role is P.');
  assert.deepEqual(select.children.map(option => option.value), ['P', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6']);
  select.value = 'H3';
  await result.dispatch(select, 'change');
  assert.deepEqual(result.mutationRequests, [], 'Changing a select is not a save or an approval.');
  await result.dispatch(buttonNamed(card, 'Save edit'), 'click');
  assert.equal(selectsFor(cardFor(result, 'heading-one'))[0].value, 'H3');
  assert.equal(response.decisions.find(item => item.id === 'heading-one').status, 'pending');
  assert.equal(result.getNode('apply').disabled, true);
  assert.match(result.getNode('notice').textContent, /Draft saved/);
  assertSavedSnapshotUnchanged(result, saved, before);
  expectOnlyMutations(result, [{url, payload}]);
});

test('DOM repair controls: explicit heading acceptance edits first then binds approval to the returned revision and name', async () => {
  const saved = repairControlsFixture(), before = JSON.stringify(saved);
  const prefix = '/api/workspaces/' + saved.workspace_id;
  const edited = editedView(saved, 'heading-one', 'H4');
  const accepted = structuredClone(edited);
  accepted.revision = 9;
  Object.assign(accepted.decisions.find(item => item.id === 'heading-one'),
    {status: 'approved', approved_by: 'Authored control reviewer'});
  const expected = [
    {url: prefix + '/edit', payload: {revision: 7, id: 'heading-one', value: 'H4'}, response: edited},
    {url: prefix + '/approve', payload: {revision: 8, id: 'heading-one', reviewer: 'Authored control reviewer'}, response: accepted},
  ];
  const result = await bootSavedReview(saved, {expectedMutations: expected});
  await openSavedReview(result);
  await showStructure(result);
  const card = cardFor(result, 'heading-one');
  selectsFor(card)[0].value = 'H4';
  result.getNode('reviewer').value = ' Authored control reviewer ';
  assert.deepEqual(result.mutationRequests, []);
  await result.dispatch(buttonNamed(card, 'Accept this value'), 'click');
  assert.equal(result.getNode('apply').disabled, false, 'Acceptance enables the separate Apply action without invoking it.');
  assert.equal(selectsFor(cardFor(result, 'heading-one'))[0].value, 'H4');
  assertSavedSnapshotUnchanged(result, saved, before);
  expectOnlyMutations(result, expected.map(({url, payload}) => ({url, payload})));
});

test('DOM repair controls: acceptance without a reviewer refuses before saving or approving a changed heading', async () => {
  const saved = repairControlsFixture(), before = JSON.stringify(saved);
  const result = await bootSavedReview(saved);
  await openSavedReview(result);
  await showStructure(result);
  const card = cardFor(result, 'heading-one');
  selectsFor(card)[0].value = 'H4';
  await result.dispatch(buttonNamed(card, 'Accept this value'), 'click');
  assert.match(result.getNode('notice').textContent, /Enter your name/);
  assert.equal(result.getNode('notice').classList.contains('error'), true);
  assertSavedSnapshotUnchanged(result, saved, before);
  expectOnlyMutations(result, []);
});

for (const [role, scope, expectedValue] of [
  ['TH', 'Column', '{"role":"TH","scope":"Column"}'],
  ['TH', 'Both', '{"role":"TH","scope":"Both"}'],
  ['TH', '', '{"role":"TH","scope":null}'],
  ['TD', 'Row', '{"role":"TD","scope":null}'],
]) {
  test(`DOM repair controls: table Save serializes canonical ${role}/${scope || 'existing-links'} without approval`, async () => {
    const saved = repairControlsFixture(), before = JSON.stringify(saved);
    const url = '/api/workspaces/' + saved.workspace_id + '/edit';
    const payload = {revision: 7, id: 'table-one', value: expectedValue};
    const response = editedView(saved, 'table-one', expectedValue);
    const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response}]});
    await openSavedReview(result);
    await showStructure(result);
    const card = cardFor(result, 'table-one'), [roleSelect, scopeSelect] = selectsFor(card);
    assert.equal(roleSelect.value, 'TD');
    assert.equal(scopeSelect.value, '');
    assert.deepEqual(roleSelect.children.map(option => option.value), ['TD', 'TH']);
    assert.deepEqual(scopeSelect.children.map(option => option.value), ['', 'Column', 'Row', 'Both']);
    roleSelect.value = role;
    scopeSelect.value = scope;
    await result.dispatch(roleSelect, 'change');
    await result.dispatch(scopeSelect, 'change');
    assert.deepEqual(result.mutationRequests, []);
    await result.dispatch(buttonNamed(card, 'Save edit'), 'click');
    assert.equal(response.decisions.find(item => item.id === 'table-one').status, 'pending');
    assert.equal(result.getNode('apply').disabled, true);
    assertSavedSnapshotUnchanged(result, saved, before);
    expectOnlyMutations(result, [{url, payload}]);
  });
}

test('DOM repair controls: unsafe heading controls and stale workspace controls are disabled with no mutation', async () => {
  for (const stale of [false, true]) {
    const saved = repairControlsFixture();
    saved.stale = stale;
    const before = JSON.stringify(saved), result = await bootSavedReview(saved);
    await openSavedReview(result);
    await showStructure(result);
    const unsafe = cardFor(result, 'unsafe-heading');
    assert.equal(selectsFor(unsafe)[0].value, 'H8', 'An unsafe existing role must not disappear from the disabled select.');
    assert.equal(selectsFor(unsafe)[0].disabled, true);
    for (const label of ['Save edit', 'Accept this value']) {
      const button = buttonNamed(unsafe, label);
      assert.equal(button.disabled, true);
      await result.dispatch(button, 'click');
    }
    assert.equal(selectsFor(cardFor(result, 'heading-one'))[0].disabled, stale);
    for (const select of selectsFor(cardFor(result, 'table-one'))) assert.equal(select.disabled, stale);
    const suggestion = buttonNamed(result.getNode('repair-findings'), 'Use es as a language draft');
    assert.equal(suggestion.disabled, stale);
    if (stale) await result.dispatch(suggestion, 'click');
    assertSavedSnapshotUnchanged(result, saved, before);
    expectOnlyMutations(result, []);
  }
});

test('DOM repair controls: a language suggestion copies an exact pending draft and never accepts or applies it', async () => {
  const saved = repairControlsFixture(), before = JSON.stringify(saved);
  const url = '/api/workspaces/' + saved.workspace_id + '/edit';
  const payload = {revision: 7, id: 'language-control', value: 'es'};
  const response = editedView(saved, 'language-control', 'es');
  const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response}]});
  await openSavedReview(result);
  assert.equal(result.getNode('repair-findings').hidden, false);
  assert.deepEqual(result.mutationRequests, []);
  await result.dispatch(buttonNamed(result.getNode('repair-findings'), 'Use es as a language draft'), 'click');
  const input = descendants(cardFor(result, 'language-control')).find(node => node.tagName === 'INPUT');
  assert.equal(input.value, 'es');
  assert.equal(response.decisions.find(item => item.kind === 'language').status, 'pending');
  assert.equal(result.getNode('apply').disabled, true);
  assert.equal(result.getNode('tab-decisions').attributes['aria-selected'], 'true');
  assert.match(result.getNode('notice').textContent, /explicitly accept it before applying/);
  assertSavedSnapshotUnchanged(result, saved, before);
  expectOnlyMutations(result, [{url, payload}]);
});

for (const [status, suggested] of [['needs-review', 'es'], ['pass', 'es'], ['fail', null]]) {
  test(`DOM repair controls: language ${status}/${suggested || 'no-suggestion'} never invents a draft-copy action`, async () => {
    const saved = repairControlsFixture(), before = JSON.stringify(saved);
    saved.repair_findings = [{id: 'language-correctness', status, evidence: {suggested_language: suggested}}];
    const snapshot = JSON.stringify(saved), result = await bootSavedReview(saved);
    await openSavedReview(result);
    assert.equal(descendants(result.getNode('repair-findings')).filter(node => node.tagName === 'BUTTON').length, 0);
    assert.equal(result.getNode('repair-findings').hidden, status === 'pass');
    assertSavedSnapshotUnchanged(result, saved, snapshot);
    expectOnlyMutations(result, []);
    assert.notEqual(before, snapshot, 'The authored status variation must actually be exercised.');
  });
}

test('DOM repair controls: HTML-looking context and evidence remain literal text; measured page links are read-only', async () => {
  const saved = repairControlsFixture(), before = JSON.stringify(saved);
  const result = await bootSavedReview(saved);
  await openSavedReview(result);
  await showStructure(result);
  const heading = cardFor(result, 'heading-one');
  const context = heading.children.find(node => node.textContent === LITERAL_CONTEXT);
  assert(context);
  assert.deepEqual(context.children, []);
  const evidence = descendants(result.getNode('repair-findings')).filter(node => node.tagName === 'PRE');
  assert.equal(evidence.length, 2);
  assert(evidence.every(node => node.textContent.includes('<img src=x') && node.textContent.includes('<script>authored()</script>')));
  assert(evidence.every(node => node.children.length === 0));
  assert.equal(descendants(result.getNode('repair-findings')).filter(node => ['IMG', 'SCRIPT'].includes(node.tagName)).length, 0);
  const advice = descendants(result.getNode('repair-findings')).find(node => node.textContent.startsWith('Source-edit suggestion:'));
  assert(advice);
  assert.equal(advice.textContent, 'Source-edit suggestion: text color RGB 0, 0, 0 gives 21.00:1 against the measured background. Review it before editing the source and reprocessing.');
  assert.deepEqual(advice.children, []);
  assert.equal(descendants(result.getNode('repair-findings')).filter(node => node.tagName === 'BUTTON').length, 2,
    'Contrast color advice has no Apply/accept action: only the separate language draft and read-only page link are buttons.');
  await result.dispatch(buttonNamed(result.getNode('repair-findings'), 'Page 2'), 'click');
  assert.equal(result.getNode('page-number').value, '2');
  assert.equal(cardFor(result, 'heading-two').dataset.decisionId, 'heading-two');
  assertSavedSnapshotUnchanged(result, saved, before);
  expectOnlyMutations(result, []);
});

function deferredResponse() {
  let resolve, reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return {promise, resolve, reject};
}

function navigationFixtures() {
  const first = repairControlsFixture(), second = repairControlsFixture();
  first.source.path = '/authored/workspace-A.pdf';
  second.workspace_id = 'f'.repeat(24);
  second.source.path = '/authored/workspace-B.pdf';
  // Deliberately coinciding metadata IDs/revisions reproduce the risk: server
  // revision checks alone cannot distinguish a wrongly redirected approval.
  for (const saved of [first, second]) {
    saved.decisions.find(item => item.kind === 'title').value = saved.source.path.split('/').at(-1);
  }
  second.decisions.find(item => item.kind === 'language').value = 'de';
  return {first, second};
}

async function bootNavigation(first, second, options = {}) {
  return boot({stored: VALID,
    documents: [first, second].map(saved => ({id: saved.workspace_id, title: saved.source.path.split('/').at(-1),
      status: saved.status, page_count: saved.page_count, counts: saved.counts})),
    workspaces: {[first.workspace_id]: first, [second.workspace_id]: second}, ...options});
}

function workspaceCard(result, title) {
  const cards = result.getNode('documents').children.filter(card => card.children[0]?.textContent === title);
  assert.equal(cards.length, 1, 'The real dashboard must contain the exact authored workspace card: ' + title);
  return cards[0];
}

async function openNamedWorkspace(result, title) {
  await result.dispatch(workspaceCard(result, title), 'click');
  assert.equal(result.getNode('notice').hidden, true);
  assert.equal(result.getNode('document-title').textContent, title);
  assert.equal(result.getNode('review').hidden, false);
}

function assertVisibleWorkspace(result, title, language) {
  assert.equal(result.getNode('document-title').textContent, title);
  assert.equal(result.getNode('dashboard').hidden, true);
  assert.equal(result.getNode('review').hidden, false);
  const languageInput = descendants(cardFor(result, 'language-control')).find(node => node.tagName === 'INPUT');
  assert.equal(languageInput.value, language);
  assert.equal(result.getNode('notice').hidden, true, 'An old successful mutation must not place its completion notice on another view.');
}

test('DOM navigation races: a delayed language draft response cannot overwrite a subsequently opened workspace', async () => {
  const {first, second} = navigationFixtures();
  const before = [JSON.stringify(first), JSON.stringify(second)];
  const delayed = deferredResponse();
  const url = '/api/workspaces/' + first.workspace_id + '/edit';
  const payload = {revision: 7, id: 'language-control', value: 'es'};
  const result = await bootNavigation(first, second, {expectedMutations: [{url, payload, response: delayed.promise}]});
  await openNamedWorkspace(result, 'workspace-A.pdf');
  const saving = result.dispatch(buttonNamed(result.getNode('repair-findings'), 'Use es as a language draft'), 'click');
  await settle();
  assert.deepEqual(result.mutationRequests, [{url, payload}]);
  await result.dispatch('back', 'click');
  await openNamedWorkspace(result, 'workspace-B.pdf');
  delayed.resolve(editedView(first, 'language-control', 'es'));
  await saving;
  assertVisibleWorkspace(result, 'workspace-B.pdf', 'de');
  assert.equal(JSON.stringify(first), before[0]);
  assert.equal(JSON.stringify(second), before[1]);
  expectOnlyMutations(result, [{url, payload}]);
});

test('DOM navigation races: delayed generic Save remains an A draft without replacing the displayed B view', async () => {
  const {first, second} = navigationFixtures();
  const delayed = deferredResponse();
  const url = '/api/workspaces/' + first.workspace_id + '/edit';
  const payload = {revision: 7, id: 'heading-one', value: 'H3'};
  const result = await bootNavigation(first, second, {expectedMutations: [{url, payload, response: delayed.promise}]});
  await openNamedWorkspace(result, 'workspace-A.pdf');
  await showStructure(result);
  const card = cardFor(result, 'heading-one');
  selectsFor(card)[0].value = 'H3';
  const saving = result.dispatch(buttonNamed(card, 'Save edit'), 'click');
  await settle();
  await result.dispatch('back', 'click');
  await openNamedWorkspace(result, 'workspace-B.pdf');
  delayed.resolve(editedView(first, 'heading-one', 'H3'));
  await saving;
  assertVisibleWorkspace(result, 'workspace-B.pdf', 'de');
  assert.equal(selectsFor(cardFor(result, 'heading-one'))[0].value, 'H2', 'B retains its own saved structural draft.');
  expectOnlyMutations(result, [{url, payload}]);
});

for (const returnToA of [false, true]) {
  test('DOM navigation races: pending Accept aborts approval after ' + (returnToA ? 'A to B to A' : 'A to B'), async () => {
    const {first, second} = navigationFixtures();
    const before = [JSON.stringify(first), JSON.stringify(second)];
    const delayed = deferredResponse();
    const url = '/api/workspaces/' + first.workspace_id + '/edit';
    const payload = {revision: 7, id: 'title-control', value: 'An explicit A title draft'};
    const result = await bootNavigation(first, second, {expectedMutations: [{url, payload, response: delayed.promise}]});
    await openNamedWorkspace(result, 'workspace-A.pdf');
    result.getNode('reviewer').value = 'Authored race-control reviewer';
    const card = cardFor(result, 'title-control');
    descendants(card).find(node => node.tagName === 'TEXTAREA').value = payload.value;
    const accepting = result.dispatch(buttonNamed(card, 'Accept this value'), 'click');
    await settle();
    assert.deepEqual(result.mutationRequests, [{url, payload}]);
    await result.dispatch('back', 'click');
    await openNamedWorkspace(result, 'workspace-B.pdf');
    if (returnToA) {
      await result.dispatch('back', 'click');
      await openNamedWorkspace(result, 'workspace-A.pdf');
    }
    const response = editedView(first, 'title-control', payload.value);
    delayed.resolve(response);
    await accepting;
    assert.equal(response.decisions.find(item => item.kind === 'title').status, 'pending');
    assertVisibleWorkspace(result, returnToA ? 'workspace-A.pdf' : 'workspace-B.pdf', returnToA ? 'en-US' : 'de');
    const visibleTitle = descendants(cardFor(result, 'title-control')).find(node => node.tagName === 'TEXTAREA').value;
    assert.equal(visibleTitle, returnToA ? 'workspace-A.pdf' : 'workspace-B.pdf');
    assert(!result.requests.some(request => request.url.endsWith('/approve')),
      'Navigation ends the original acceptance intent even if the same workspace is reopened.');
    assert.equal(JSON.stringify(first), before[0]);
    assert.equal(JSON.stringify(second), before[1]);
    expectOnlyMutations(result, [{url, payload}]);
  });
}

test('DOM navigation races: a delayed Open A cannot replace a newer completed Open B', async () => {
  const {first, second} = navigationFixtures();
  const delayed = deferredResponse();
  const url = '/api/workspaces/' + first.workspace_id;
  const result = await bootNavigation(first, second, {expectedReads: [{url, response: delayed.promise}]});
  const opening = result.dispatch(workspaceCard(result, 'workspace-A.pdf'), 'click');
  await settle();
  assert.equal(result.getNode('review').hidden, true, 'Pending Open hides the old interactive review.');
  assert.equal(result.getNode('dashboard').hidden, false);
  await openNamedWorkspace(result, 'workspace-B.pdf');
  delayed.resolve(first);
  await opening;
  assertVisibleWorkspace(result, 'workspace-B.pdf', 'de');
  assert.deepEqual(result.remainingReads, []);
  assert(!result.requests.some(request => request.url.startsWith(url + '/page?')),
    'An obsolete Open response must not start previews for the discarded workspace.');
  expectOnlyMutations(result, []);
});

test('DOM active-job guards: manual filters, structural toggle and page navigation cannot restore mutable controls', async () => {
  const saved = repairControlsFixture(), before = JSON.stringify(saved);
  const url = '/api/workspaces/' + saved.workspace_id + '/auto-fix';
  const payload = {revision: 7, consent: true, use_ai: false, ai_consent: false,
    endpoint: '', model: '', include_images: false, reasoning_effort: null};
  const result = await bootSavedReview(saved, {captureTimers: true,
    expectedMutations: [{url, payload, response: {job_id: 'authored-mechanical-job'}}]});
  await openSavedReview(result);
  await showStructure(result);
  assert.equal(result.getNode('approve-group').disabled, false, 'This authored current artifact can be reviewed before a job starts.');
  await result.dispatch('auto-fix', 'click');
  assert.equal(result.scheduledTimers.length, 1, 'The real job listener scheduled polling through a captured timer, not a real service.');
  assert.equal(result.scheduledTimers[0].delay, 300);
  const assertManualDisabled = () => {
    for (const id of ['approve-group', 'select-group', 'review-confirm']) assert.equal(result.getNode(id).disabled, true, id);
    const mutable = descendants(result.getNode('manual-items')).filter(node => node.tagName === 'INPUT'
      || node.tagName === 'BUTTON' && node.className !== 'item-page');
    assert(mutable.length > 0);
    assert(mutable.every(node => node.disabled), 'Every current manual note, checkbox and action remains disabled.');
  };
  assertManualDisabled();
  result.getNode('group-choice').value = 'order';
  await result.dispatch('group-choice', 'change');
  assertManualDisabled();
  result.getNode('show-automatic').checked = true;
  await result.dispatch('show-automatic', 'change');
  assertManualDisabled();
  result.getNode('group-choice').value = 'figures';
  await result.dispatch('group-choice', 'change');
  assertManualDisabled();
  await showStructure(result, false);
  await showStructure(result, true);
  assert(descendants(result.getNode('decisions')).filter(node => ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(node.tagName)).every(node => node.disabled));
  await result.dispatch('next-page', 'click');
  assert.equal(selectsFor(cardFor(result, 'heading-two'))[0].disabled, true);
  assertManualDisabled();
  const calls = result.requests.length;
  await result.dispatch('approve-group', 'click');
  await result.dispatch(buttonNamed(manualCards(result)[0], 'Report a problem'), 'click');
  await result.dispatch(buttonNamed(result.getNode('repair-findings'), 'Use es as a language draft'), 'click');
  assert.equal(result.requests.length, calls, 'Disabled controls cannot emit mutation requests.');
  assert.equal(JSON.stringify(saved), before);
  assert.deepEqual(result.mutationRequests, [{url, payload}]);
  assert.deepEqual(result.remainingMutations, []);
  assert(!result.requests.some(request => /\/(review|group|approve|apply|assist)$/.test(request.url)));
  assert.deepEqual(result.unexpectedRequests, []);
});

function autoFixBoot(saved, jobs, jobId, extraMutations = []) {
  const url = '/api/workspaces/' + saved.workspace_id + '/auto-fix';
  const payload = {revision: 7, consent: true, use_ai: false, ai_consent: false,
    endpoint: '', model: '', include_images: false, reasoning_effort: null};
  return bootSavedReview(saved, {jobs, captureTimers: true,
    expectedMutations: [{url, payload, response: {job_id: jobId}}, ...extraMutations]});
}

test('Auto-fix shows a live status line beside the button: the step now running, a running clock, cleared when the job ends', async () => {
  const saved = repairControlsFixture(), jobs = [], id = 'authored-live-job';
  const result = await autoFixBoot(saved, jobs, id);
  await openSavedReview(result);
  assert.equal(result.getNode('auto-status').hidden, true, 'Nothing is shown before a job starts.');
  await result.dispatch('auto-fix', 'click');
  assert.equal(result.getNode('auto-status').hidden, false, 'The status line appears the moment the job is accepted.');
  assert.match(result.getNode('auto-step').textContent, /^Starting\. This can take a few minutes\.$/);
  assert.match(result.getNode('auto-clock').textContent, /^Working for 0:\d\d\. Please keep this window open\.$/);
  const first = 'Trying the supported layout repairs from the unchanged original.';
  const second = 'Applying authorized automatic choices and rerunning every release check.';
  jobs.push({id, label: 'Authored automatic job', status: 'running', progress: [first], error: null});
  await result.scheduledTimers[0].callback(); await settle();
  assert.equal(result.getNode('auto-status').hidden, false);
  assert.equal(result.getNode('auto-step').textContent, first);
  jobs[0].progress.push(second);
  await result.scheduledTimers.at(-1).callback(); await settle();
  assert.equal(result.getNode('auto-step').textContent, second, 'The line follows the latest step, not the first one.');
  assert.match(result.getNode('auto-clock').textContent, /^Working for \d+:\d\d\. Please keep this window open\.$/);
  jobs[0].status = 'done';
  jobs[0].result = {auto_fix: {status: 'needs-attention', automatically_handled: 0, automatic_decisions_applied: 0,
    remaining_checks: 12, warnings: []}};
  await result.scheduledTimers.at(-1).callback(); await settle();
  assert.equal(result.getNode('auto-status').hidden, true, 'The status line is gone once the job ends.');
  assert.equal(result.getNode('auto-step').textContent, '');
  assert.equal(result.getNode('auto-clock').textContent, '');
  assert.equal(result.getNode('notice').textContent, 'Automatic processing needs attention. Nothing here could be repaired '
    + 'automatically, so automatic mode changed nothing. The 12 remaining checks need a person to review them.');
  assert.equal(result.getNode('notice').classList.contains('error'), false);
  assert.deepEqual(result.remainingMutations, []);
  assert.deepEqual(result.unexpectedRequests, []);
});

test('Auto-fix keeps its original wording when something was repaired automatically', async () => {
  const saved = repairControlsFixture(), jobs = [], id = 'authored-repair-job';
  const result = await autoFixBoot(saved, jobs, id);
  await openSavedReview(result);
  await result.dispatch('auto-fix', 'click');
  jobs.push({id, label: 'Authored automatic job', status: 'done', progress: [], error: null,
    result: {auto_fix: {status: 'complete', automatically_handled: 3, automatic_decisions_applied: 2, remaining_checks: 5,
      warnings: ['One model answer was not used.']}}});
  await result.scheduledTimers[0].callback(); await settle();
  assert.equal(result.getNode('notice').textContent, 'Automatic processing finished. 3 repair checks handled automatically; '
    + '2 title or description choices applied; 5 other checks remain. One model answer was not used.');
  assert.equal(result.getNode('auto-status').hidden, true);
});

for (const status of ['failed', 'cancelled']) {
  test('Auto-fix status line is cleared when the job ' + status, async () => {
    const saved = repairControlsFixture(), jobs = [], id = 'authored-ended-job';
    const result = await autoFixBoot(saved, jobs, id);
    await openSavedReview(result);
    await result.dispatch('auto-fix', 'click');
    assert.equal(result.getNode('auto-status').hidden, false);
    jobs.push({id, label: 'Authored automatic job', status, progress: ['Trying the supported layout repairs from the unchanged original.'], error: null});
    await result.scheduledTimers[0].callback(); await settle();
    assert.equal(result.getNode('auto-status').hidden, true);
    assert.equal(result.getNode('auto-step').textContent, '');
    assert.equal(result.getNode('notice').classList.contains('error'), status === 'failed');
  });
}

test('Auto-fix status line markup: live step, silent clock, placed under the button and before the explanation', () => {
  const html = fs.readFileSync(path.join(path.dirname(appPath), 'index.html'), 'utf8');
  assert.match(html, /<p id="auto-status" class="auto-status" hidden>/);
  assert.match(html, /<strong id="auto-step" role="status" aria-live="polite"><\/strong>/);
  assert.match(html, /<span id="auto-clock" role="timer" aria-live="off"><\/span>/);
  const button = html.indexOf('id="auto-fix"'), line = html.indexOf('id="auto-status"'), note = html.indexOf('Automatic choices are not human approvals');
  assert(button > 0 && button < line && line < note, 'The line sits between the button and its explanation.');
});

async function startScan(jobs, jobId, extraMutations = []) {
  const file = {name: 'Authored one-page PDF.pdf', size: 64, authoredFileDouble: true};
  const payload = {inputs: ['authored-upload-id'], options: {language: 'en-US', document_kind: 'unknown', ocr_mode: 'off', ocr_profile: 'standard',
    allow_tag_regrouping: false, repair_source_mappings: false, remove_cidset: false}};
  const result = await boot({stored: VALID, capabilities: ocrCapability(false), captureTimers: true, jobs,
    expectedUploads: [{file, id: 'authored-upload-id'}],
    expectedMutations: [{url: '/api/process', payload, response: {job_id: jobId}}, ...extraMutations]});
  result.getNode('files').files = [file];
  await result.dispatch('files', 'change');
  result.getNode('new-language').value = 'en-US';
  const kind = result.document.createElement('option'); kind.value = 'unknown';
  result.getNode('new-kind').append(kind);
  result.getNode('new-ocr').value = 'off';
  await result.dispatch('process', 'click');
  return result;
}

test('A first scan shows a bar that stays on screen: what is running, the step now, a running clock, cleared when it ends', async () => {
  const jobs = [], id = 'authored-scan-job';
  const result = await startScan(jobs, id);
  jobs.push({id, label: 'Authored scan of one PDF', status: 'running', progress: [], error: null});
  await result.scheduledTimers[0].callback(); await settle();
  assert.equal(result.getNode('job-bar').hidden, false);
  assert.equal(result.getNode('job-label').textContent, 'Authored scan of one PDF');
  assert.equal(result.getNode('job-step').textContent, 'Starting. This can take a few minutes.');
  assert.match(result.getNode('job-clock').textContent, /^Working for 0:\d\d\. Please keep this window open\.$/);
  jobs[0].progress.push('Reading the document structure.');
  await result.scheduledTimers.at(-1).callback(); await settle();
  assert.equal(result.getNode('job-step').textContent, 'Reading the document structure.');
  jobs[0].progress.push('Checking the result with the strict validator.');
  await result.scheduledTimers.at(-1).callback(); await settle();
  assert.equal(result.getNode('job-step').textContent, 'Checking the result with the strict validator.');
  jobs[0].status = 'done'; jobs[0].result = {};
  await result.scheduledTimers.at(-1).callback(); await settle();
  assert.equal(result.getNode('job-bar').hidden, true, 'The bar is gone once the job ends.');
  assert.equal(result.getNode('job-label').textContent, '');
  assert.equal(result.getNode('job-step').textContent, '');
  assert.equal(result.getNode('job-clock').textContent, '');
  assert.match(result.getNode('notice').textContent, /Processing finished/);
  assert.deepEqual(result.remainingMutations, []);
  assert.deepEqual(result.unexpectedRequests, []);
});

for (const status of ['failed', 'cancelled']) {
  test('The job bar is cleared when a scan ' + status, async () => {
    const jobs = [], id = 'authored-ended-scan';
    const result = await startScan(jobs, id);
    jobs.push({id, label: 'Authored scan', status: 'running', progress: ['Reading the document structure.'], error: null});
    await result.scheduledTimers[0].callback(); await settle();
    assert.equal(result.getNode('job-bar').hidden, false);
    jobs[0].status = status;
    await result.scheduledTimers.at(-1).callback(); await settle();
    assert.equal(result.getNode('job-bar').hidden, true);
    assert.equal(result.getNode('notice').classList.contains('error'), status === 'failed');
  });
}

test('The bar is not shown for Auto-fix, which has its own line under the button', async () => {
  const saved = repairControlsFixture(), jobs = [], id = 'authored-own-line-job';
  const result = await autoFixBoot(saved, jobs, id);
  await openSavedReview(result);
  await result.dispatch('auto-fix', 'click');
  jobs.push({id, label: 'Authored automatic job', status: 'running', progress: ['Trying the supported layout repairs from the unchanged original.'], error: null});
  await result.scheduledTimers[0].callback(); await settle();
  assert.equal(result.getNode('auto-status').hidden, false);
  assert.equal(result.getNode('job-bar').hidden, true, 'One job is never announced in two places.');
});

test('Stopping the application hides the status lines', async () => {
  const jobs = [], id = 'authored-stop-scan';
  const result = await startScan(jobs, id, [stopExpectation()]);
  jobs.push({id, label: 'Authored scan', status: 'running', progress: [], error: null});
  await result.scheduledTimers[0].callback(); await settle();
  assert.equal(result.getNode('job-bar').hidden, false);
  await result.dispatch('stop', 'click');
  assertStoppedNotice(result);
  assert.equal(result.getNode('job-bar').hidden, true, 'A stopped application shows no running job.');
  assert.equal(result.getNode('auto-status').hidden, true);
});

test('Job bar markup: label, live step, silent clock, after the page and before the dialogs', () => {
  const html = fs.readFileSync(path.join(path.dirname(appPath), 'index.html'), 'utf8');
  assert.match(html, /<div id="job-bar" class="job-bar" hidden>/);
  assert.match(html, /<span id="job-step" role="status" aria-live="polite"><\/span>/);
  assert.match(html, /<span id="job-clock" role="timer" aria-live="off"><\/span>/);
  const main = html.indexOf('</main>'), bar = html.indexOf('id="job-bar"'), dialog = html.indexOf('<dialog id="cidset-dialog"');
  assert(main > 0 && main < bar && bar < dialog, 'The bar sits right after the page content.');
});

test('Cancel in the bottom bar asks the service to cancel the job shown, once, and says so', async () => {
  const jobs = [], id = 'authored-cancel-scan', cancelUrl = '/api/jobs/' + id + '/cancel';
  const result = await startScan(jobs, id, [{url: cancelUrl, payload: {}, response: {}}]);
  jobs.push({id, label: 'Authored scan', status: 'running', progress: ['Reading the document structure.'], error: null});
  await result.scheduledTimers[0].callback(); await settle();
  assert.equal(result.getNode('job-cancel').textContent, 'Cancel');
  assert.equal(result.getNode('job-cancel').disabled, false);
  await result.dispatch('job-cancel', 'click');
  assert.deepEqual(result.mutationRequests.slice(-1), [{url: cancelUrl, payload: {}}]);
  assert.equal(result.getNode('job-cancel').disabled, true, 'A second press is not offered.');
  assert.equal(result.getNode('job-cancel').textContent, 'Cancelling…');
  await result.dispatch('job-cancel', 'click');
  assert.deepEqual(result.remainingMutations, [], 'A second press sends nothing.');
  jobs[0].status = 'cancelled';
  await result.scheduledTimers.at(-1).callback(); await settle();
  assert.equal(result.getNode('job-bar').hidden, true);
  assert.equal(result.getNode('job-cancel').textContent, 'Cancel', 'The button is ready again for the next job.');
  assert.equal(result.getNode('job-cancel').disabled, false);
  assert.equal(result.getNode('notice').textContent, 'Processing was cancelled; no unfinished result was released.');
  assert.deepEqual(result.unexpectedRequests, []);
});

test('A cancel request the service refuses can be tried again and the reason is shown', async () => {
  const jobs = [], id = 'authored-refused-cancel', cancelUrl = '/api/jobs/' + id + '/cancel';
  const result = await startScan(jobs, id, [{url: cancelUrl, payload: {}, ok: false, response: {error: 'The service could not cancel this job.'}},
    {url: cancelUrl, payload: {}, response: {}}]);
  jobs.push({id, label: 'Authored scan', status: 'running', progress: [], error: null});
  await result.scheduledTimers[0].callback(); await settle();
  await result.dispatch('job-cancel', 'click');
  assert.equal(result.getNode('notice').textContent, 'The service could not cancel this job.');
  assert.equal(result.getNode('notice').classList.contains('error'), true);
  assert.equal(result.getNode('job-cancel').disabled, false, 'A refused request leaves Cancel available.');
  assert.equal(result.getNode('job-cancel').textContent, 'Cancel');
  await result.dispatch('job-cancel', 'click');
  assert.equal(result.getNode('job-cancel').textContent, 'Cancelling…');
  assert.deepEqual(result.remainingMutations, []);
});

test('Cancel beside the Auto-fix line cancels the Auto-fix job', async () => {
  const saved = repairControlsFixture(), jobs = [], id = 'authored-auto-cancel', cancelUrl = '/api/jobs/' + id + '/cancel';
  const result = await autoFixBoot(saved, jobs, id, [{url: cancelUrl, payload: {}, response: {}}]);
  await openSavedReview(result);
  await result.dispatch('auto-fix', 'click');
  jobs.push({id, label: 'Authored automatic job', status: 'running', progress: ['Trying the supported layout repairs from the unchanged original.'], error: null});
  await result.scheduledTimers[0].callback(); await settle();
  assert.equal(result.getNode('auto-cancel').disabled, false);
  await result.dispatch('auto-cancel', 'click');
  assert.deepEqual(result.mutationRequests.slice(-1), [{url: cancelUrl, payload: {}}]);
  assert.equal(result.getNode('auto-cancel').textContent, 'Cancelling…');
  assert.equal(result.getNode('job-bar').hidden, true, 'The bar stays out of the way while the Auto-fix line is showing.');
  assert.deepEqual(result.remainingMutations, []);
});

test('When two jobs are waiting the bar shows the first, says how many more wait, and cancels the first', async () => {
  const jobs = [{id: 'authored-first', label: 'First scan', status: 'running', progress: ['Reading the document structure.']},
    {id: 'authored-second', label: 'Second scan', status: 'queued', progress: []}];
  const cancelUrl = '/api/jobs/authored-first/cancel';
  const result = await boot({stored: VALID, jobs, captureTimers: true,
    expectedMutations: [{url: cancelUrl, payload: {}, response: {}}]});
  assert.equal(result.getNode('job-bar').hidden, false, 'A job that was already running when the page opened is shown at once.');
  assert.equal(result.getNode('job-label').textContent, 'First scan');
  assert.equal(result.getNode('job-step').textContent, 'Reading the document structure.');
  assert.match(result.getNode('job-clock').textContent, /Please keep this window open\. 1 more waiting\.$/);
  await result.dispatch('job-cancel', 'click');
  assert.deepEqual(result.mutationRequests, [{url: cancelUrl, payload: {}}]);
});

test('A failed job with a reported reason shows that reason, in an error notice', async () => {
  const jobs = [], id = 'authored-reason-scan';
  const result = await startScan(jobs, id);
  jobs.push({id, label: 'Authored scan', status: 'failed', progress: [], error: 'The PDF could not be opened: it is damaged.'});
  await result.scheduledTimers[0].callback(); await settle();
  assert.equal(result.getNode('notice').textContent, 'The PDF could not be opened: it is damaged.');
  assert.equal(result.getNode('notice').classList.contains('error'), true);
  assert.equal(result.getNode('job-bar').hidden, true);
});

test('The old Processing activity section and its cards are gone; Cancel buttons are in the bar and the Auto-fix line', () => {
  const html = fs.readFileSync(path.join(path.dirname(appPath), 'index.html'), 'utf8');
  for (const gone of ['Processing activity', 'jobs-section', 'jobs-title', 'review-activity', 'id="jobs"'])
    assert(!html.includes(gone), gone + ' must no longer be in the page.');
  assert.match(html, /<button id="job-cancel" class="quiet" type="button">Cancel<\/button><\/div>/);
  assert.match(html, /<button id="auto-cancel" class="quiet" type="button">Cancel<\/button><\/p>/);
  const script = fs.readFileSync(appPath, 'utf8');
  for (const gone of ['jobs-section', 'review-activity', "$('jobs')", 'job-card'])
    assert(!script.includes(gone), gone + ' must no longer be used by the script.');
});

test('Reset clears the chosen PDFs and puts every start option back to its normal setting, without any request', async () => {
  const file = {name: 'Authored chosen PDF.pdf', size: 64, authoredFileDouble: true};
  const result = await boot({stored: VALID, capabilities: ocrCapability(true)});
  const requestsBefore = result.requests.length;
  result.getNode('files').files = [file];
  await result.dispatch('files', 'change');
  assert.equal(result.getNode('process').disabled, false);
  assert.equal(result.getNode('selected-files').children.length, 1);
  const kind = result.document.createElement('option'); kind.value = 'unknown';
  const reading = result.document.createElement('option'); reading.value = 'reading';
  result.getNode('new-kind').append(kind, reading);
  result.getNode('new-title').value = 'A title I typed';
  result.getNode('new-language').value = 'fr-FR';
  result.getNode('new-kind').value = 'reading';
  result.getNode('new-ocr').value = 'skip';
  await result.dispatch('new-ocr', 'change');
  assert.equal(result.getNode('new-ocr-profile').disabled, false, 'A scan layout can be chosen once OCR is on.');
  result.getNode('new-ocr-profile').value = 'angles';
  for (const id of ['new-regroup', 'new-mapping', 'new-cidset']) result.getNode(id).checked = true;
  await result.dispatch('reset-start', 'click');
  assert.equal(result.getNode('selected-files').children.length, 0);
  assert.equal(result.getNode('files').value, '');
  assert.equal(result.getNode('process').disabled, true, 'Nothing is chosen, so there is nothing to process.');
  assert.equal(result.getNode('new-title').value, '');
  assert.equal(result.getNode('new-language').value, 'en-US');
  assert.equal(result.getNode('new-kind').value, 'unknown');
  assert.equal(result.getNode('new-ocr').value, 'off');
  assert.equal(result.getNode('new-ocr-profile').value, 'standard');
  assert.equal(result.getNode('new-ocr-profile').disabled, true, 'With OCR off the scan layout is off again.');
  for (const id of ['new-regroup', 'new-mapping', 'new-cidset']) assert.equal(result.getNode(id).checked, false, id);
  assert.equal(result.getNode('notice').textContent, 'Start screen reset: no PDFs are chosen and every option is back to its normal setting.');
  assert.equal(result.getNode('notice').classList.contains('error'), false);
  assert.equal(result.requests.length, requestsBefore, 'Reset only changes the start screen; nothing is sent.');
  assert.deepEqual(result.mutationRequests, []);
  assert.deepEqual(result.uploadRequests, []);
});

test('After Reset the same start screen processes only what is chosen next, with the normal options', async () => {
  const first = {name: 'Authored first PDF.pdf', size: 64, authoredFileDouble: true};
  const second = {name: 'Authored second PDF.pdf', size: 64, authoredFileDouble: true};
  const payload = {inputs: ['authored-second-id'], options: {language: 'en-US', document_kind: 'unknown', ocr_mode: 'off', ocr_profile: 'standard',
    allow_tag_regrouping: false, repair_source_mappings: false, remove_cidset: false}};
  const result = await boot({stored: VALID, capabilities: ocrCapability(false), captureTimers: true,
    expectedUploads: [{file: second, id: 'authored-second-id'}],
    expectedMutations: [{url: '/api/process', payload, response: {job_id: 'authored-after-reset-job'}}]});
  const kind = result.document.createElement('option'); kind.value = 'unknown';
  result.getNode('new-kind').append(kind);
  result.getNode('files').files = [first];
  await result.dispatch('files', 'change');
  result.getNode('new-regroup').checked = true;
  await result.dispatch('reset-start', 'click');
  result.getNode('files').files = [second];
  await result.dispatch('files', 'change');
  await result.dispatch('process', 'click');
  assert.deepEqual(result.uploadRequests, [{url: '/api/upload', name: second.name}], 'The first chosen PDF is not uploaded.');
  assert.deepEqual(result.mutationRequests, [{url: '/api/process', payload}]);
  assert.deepEqual(result.remainingMutations, []);
});

test('Home in the top bar does what the logo does: it returns to the document list', async () => {
  for (const control of ['home-button', 'home-link']) {
    const saved = repairControlsFixture();
    const result = await bootSavedReview(saved);
    await openSavedReview(result);
    assert.equal(result.getNode('review').hidden, false);
    await result.dispatch(control, 'click');
    assert.equal(result.getNode('review').hidden, true, control);
    assert.equal(result.getNode('dashboard').hidden, false, control);
  }
});

test('Home is a real labelled button beside the logo in the top bar, outside every screen', () => {
  const html = fs.readFileSync(path.join(path.dirname(appPath), 'index.html'), 'utf8');
  assert.match(html, /<button id="home-button" class="quiet" type="button" title="[^"]*">Home<\/button>/);
  const header = html.slice(html.indexOf('<header'), html.indexOf('</header>'));
  assert(header.includes('id="home-link"') && header.includes('id="home-button"'), 'Both live in the top bar, outside every screen.');
});

test('Process refuses to run with nothing chosen, even if the button were enabled after a Reset', async () => {
  const file = {name: 'Authored chosen PDF.pdf', size: 64, authoredFileDouble: true};
  const result = await boot({stored: VALID, capabilities: ocrCapability(false)});
  const before = result.requests.length;
  result.getNode('files').files = [file];
  await result.dispatch('files', 'change');
  await result.dispatch('reset-start', 'click');
  result.getNode('process').disabled = false;
  await result.dispatch('process', 'click');
  assert.equal(result.getNode('notice').textContent, 'Choose at least one PDF first.');
  assert.equal(result.getNode('notice').classList.contains('error'), true);
  assert.equal(result.requests.length, before, 'No upload and no process request leave the page.');
  assert.deepEqual(result.uploadRequests, []);
  assert.deepEqual(result.mutationRequests, []);
  assert.equal(result.getNode('process').disabled, true, 'The button is off again because nothing is chosen.');
});

test('Reset in the top bar works on every screen: it goes to the start screen and clears it, without any request', async () => {
  const saved = repairControlsFixture();
  const result = await bootSavedReview(saved, {capabilities: ocrCapability(true)});
  await openSavedReview(result);
  assert.equal(result.getNode('review').hidden, false);
  result.getNode('new-title').value = 'A title I typed';
  result.getNode('new-language').value = 'fr-FR';
  result.getNode('new-regroup').checked = true;
  const requestsBefore = result.requests.length;
  await result.dispatch('reset-button', 'click');
  assert.equal(result.getNode('review').hidden, true, 'It leaves the review.');
  assert.equal(result.getNode('dashboard').hidden, false, 'It shows the start screen.');
  assert.equal(result.getNode('new-title').value, '');
  assert.equal(result.getNode('new-language').value, 'en-US');
  assert.equal(result.getNode('new-regroup').checked, false);
  assert.equal(result.getNode('process').disabled, true);
  assert.equal(result.getNode('notice').textContent, 'Start screen reset: no PDFs are chosen and every option is back to its normal setting.');
  assert.equal(result.getNode('notice').classList.contains('error'), false);
  assert.deepEqual(result.mutationRequests, [], 'Nothing is changed on the service.');
  assert.deepEqual(result.uploadRequests, []);
  assert(result.requests.slice(requestsBefore).every(item => item.url === '/api/dashboard'), 'Only the document list is refreshed.');
});

test('Reset in the top bar does not touch a running job: its bar stays up', async () => {
  const jobs = [{id: 'authored-keeps-running', label: 'Authored scan', status: 'running', progress: ['Reading the document structure.']}];
  const result = await boot({stored: VALID, jobs, captureTimers: true});
  assert.equal(result.getNode('job-bar').hidden, false);
  await result.dispatch('reset-button', 'click');
  assert.equal(result.getNode('job-bar').hidden, false, 'The job is still shown after Reset.');
  assert.equal(result.getNode('job-label').textContent, 'Authored scan');
  assert.deepEqual(result.mutationRequests, []);
});

test('Reset is explained where it is: a named button, a plain line right under it, a hover hint, and a top-bar twin', () => {
  const html = fs.readFileSync(path.join(path.dirname(appPath), 'index.html'), 'utf8');
  assert.match(html, /<button id="reset-start" class="secondary" type="button" aria-describedby="reset-note" title="[^"]*">Reset choices<\/button>/);
  assert.match(html, /<p id="reset-note" class="reset-note">Reset choices clears the PDFs you chose and puts every option back to its normal setting\. Your saved documents are not touched\.<\/p>/);
  assert.match(html, /<\/p><p class="field-note">Up to 30 files, 100 MB each\. AI assistance stays off until you request it\.<\/p>/,
    'The size note is its own line again, not mixed with the Reset explanation.');
  const header = html.slice(html.indexOf('<header'), html.indexOf('</header>'));
  assert.match(header, /<button id="reset-button" class="quiet" type="button" title="[^"]*" aria-label="Reset: [^"]*">Reset<\/button>/);
  assert(header.indexOf('id="home-button"') < header.indexOf('id="reset-button"'), 'Home first, then Reset.');
});

test('Auto-fix says something at the click, before the service has answered, and cannot be pressed twice', async () => {
  const saved = repairControlsFixture(), jobs = [], id = 'authored-slow-start', slow = deferredResponse();
  const result = await autoFixBoot(saved, jobs, id);
  await openSavedReview(result);
  // the service is busy: its answer to the request is still on the way
  result.remainingMutations[0].response = slow.promise;
  const clicking = result.dispatch('auto-fix', 'click');
  await settle();
  assert.equal(result.getNode('auto-status').hidden, false, 'The line is there straight away.');
  assert.match(result.getNode('auto-step').textContent, /^Sending your request to the service\. If it is busy preparing page pictures this can take a few seconds\.$/);
  assert.equal(result.getNode('auto-fix').disabled, true, 'A second press is not offered while the first is on its way.');
  assert.equal(result.getNode('auto-cancel').disabled, true, 'There is no job to cancel yet.');
  await result.dispatch('refresh', 'click');
  assert.equal(result.getNode('auto-status').hidden, false, 'A refresh of the job list while the request is on its way must not wipe the line.');
  assert.match(result.getNode('auto-step').textContent, /^Sending your request/);
  slow.resolve({job_id: id});
  await clicking; await settle();
  assert.match(result.getNode('auto-step').textContent, /^Starting\. This can take a few minutes\.$/);
  assert.match(result.getNode('auto-clock').textContent, /^Working for \d+:\d\d\. Please keep this window open\.$/);
  assert.equal(result.getNode('auto-cancel').disabled, false, 'Cancel is ready once the job exists.');
  assert.equal(result.getNode('auto-cancel').textContent, 'Cancel');
  assert.deepEqual(result.remainingMutations, []);
  assert.deepEqual(result.unexpectedRequests, []);
});

test('Auto-fix: if the service refuses the request, the line goes, the button is back and the reason is shown', async () => {
  const saved = repairControlsFixture(), jobs = [];
  const url = '/api/workspaces/' + saved.workspace_id + '/auto-fix';
  const payload = {revision: 7, consent: true, use_ai: false, ai_consent: false, endpoint: '', model: '', include_images: false, reasoning_effort: null};
  const result = await bootSavedReview(saved, {jobs, captureTimers: true,
    expectedMutations: [{url, payload, ok: false, response: {error: 'This document changed. Open it again.'}}]});
  await openSavedReview(result);
  await result.dispatch('auto-fix', 'click');
  assert.equal(result.getNode('notice').textContent, 'This document changed. Open it again.');
  assert.equal(result.getNode('notice').classList.contains('error'), true);
  assert.equal(result.getNode('auto-status').hidden, true, 'No line is left claiming work is going on.');
  assert.equal(result.getNode('auto-step').textContent, '');
  assert.equal(result.getNode('auto-fix').disabled, false, 'The button can be pressed again.');
  assert.equal(result.getNode('auto-cancel').disabled, false);
  assert.equal(result.scheduledTimers.length, 0, 'No job was started, so nothing is polling.');
});

test('Process says it is sending the PDFs while they go to the service, and the notice changes once the job starts', async () => {
  const file = {name: 'Authored slow PDF.pdf', size: 64, authoredFileDouble: true}, slow = deferredResponse();
  const payload = {inputs: ['authored-upload-id'], options: {language: 'en-US', document_kind: 'unknown', ocr_mode: 'off', ocr_profile: 'standard',
    allow_tag_regrouping: false, repair_source_mappings: false, remove_cidset: false}};
  const result = await boot({stored: VALID, capabilities: ocrCapability(false), captureTimers: true,
    expectedUploads: [{file, id: 'authored-upload-id'}],
    expectedMutations: [{url: '/api/process', payload, response: slow.promise}]});
  result.getNode('files').files = [file];
  await result.dispatch('files', 'change');
  result.getNode('new-language').value = 'en-US';
  const kind = result.document.createElement('option'); kind.value = 'unknown';
  result.getNode('new-kind').append(kind);
  const clicking = result.dispatch('process', 'click');
  await settle();
  assert.equal(result.getNode('notice').textContent, 'Sending your PDFs to the local service. Large files can take a moment.');
  assert.equal(result.getNode('notice').classList.contains('error'), false);
  assert.equal(result.getNode('process').disabled, true);
  slow.resolve({job_id: 'authored-slow-process'});
  await clicking; await settle();
  assert.match(result.getNode('notice').textContent, /Processing started/);
});

const SERVICE_LOST = 'The local service is not responding. If it has stopped, close this window and open PDF Remediator again; your saved documents stay on this computer.';

test('When the service disappears during a scan the page says so plainly and stops claiming the job is running', async () => {
  const jobs = [], id = 'authored-lost-scan';
  const result = await startScan(jobs, id);
  jobs.push({id, label: 'Authored scan', status: 'running', progress: ['Reading the document structure.'], error: null});
  await result.scheduledTimers[0].callback(); await settle();
  assert.equal(result.getNode('job-bar').hidden, false);
  // the service has gone: the browser reports only a failed fetch
  result.remainingReads.push({url: '/api/dashboard', fetchFails: true});
  await result.scheduledTimers.at(-1).callback(); await settle();
  assert.equal(result.getNode('notice').textContent, SERVICE_LOST);
  assert.equal(result.getNode('notice').classList.contains('error'), true);
  assert.equal(result.getNode('job-bar').hidden, true, 'A frozen bar must not keep saying the job is running.');
  assert.equal(result.getNode('job-clock').textContent, '');
  assert.equal(result.getNode('auto-status').hidden, true);
  assert.equal(result.getNode('job-cancel').disabled, false, 'Cancel is ready again for whatever is started next.');
  await result.dispatch('job-cancel', 'click');
  assert.deepEqual(result.unexpectedRequests, [], 'Cancel must not aim a request at a job that no longer exists.');
});

test('When the service disappears during Auto-fix the line goes and the message names what to do', async () => {
  const saved = repairControlsFixture(), jobs = [], id = 'authored-lost-auto';
  const result = await autoFixBoot(saved, jobs, id);
  await openSavedReview(result);
  await result.dispatch('auto-fix', 'click');
  jobs.push({id, label: 'Authored automatic job', status: 'running', progress: ['Trying the supported layout repairs from the unchanged original.'], error: null});
  await result.scheduledTimers[0].callback(); await settle();
  assert.equal(result.getNode('auto-status').hidden, false);
  result.remainingReads.push({url: '/api/dashboard', fetchFails: true});
  await result.scheduledTimers.at(-1).callback(); await settle();
  assert.equal(result.getNode('notice').textContent, SERVICE_LOST);
  assert.equal(result.getNode('auto-status').hidden, true);
  assert.equal(result.getNode('auto-step').textContent, '');
});

test('A request made after the service has gone gets the same plain message, not "Failed to fetch"', async () => {
  const saved = repairControlsFixture(), jobs = [];
  const result = await bootSavedReview(saved, {jobs, captureTimers: true});
  await openSavedReview(result);
  result.remainingReads.push({url: '/api/dashboard', fetchFails: true});
  await result.dispatch('refresh', 'click');
  assert.equal(result.getNode('notice').textContent, SERVICE_LOST);
  assert.equal(result.getNode('notice').classList.contains('error'), true);
});

test('Any other failure keeps its own message: only a vanished service gets the new wording', async () => {
  const saved = repairControlsFixture(), jobs = [];
  const result = await bootSavedReview(saved, {jobs, captureTimers: true});
  await openSavedReview(result);
  result.remainingReads.push({url: '/api/dashboard', response: {error: 'The review could not be refreshed.'}, ok: false});
  await result.dispatch('refresh', 'click');
  assert.equal(result.getNode('notice').textContent, 'The review could not be refreshed.');
});

function assertFreshFocus(result, target, previous) {
  assert.notEqual(target, previous, 'The response must actually replace the old focused node.');
  assert.equal([...result.nodes.values()].flatMap(descendants).includes(previous), false,
    'The previous control must be outside every live rendered subtree.');
  assert(result.document.activeElement === target,
    'Focus must move to the corresponding current rendered control; observed ' + result.document.activeElement?.tagName + '.');
  assert.equal(target.disabled, false);
}

for (const [id, value] of [['heading-one', 'H3'], ['table-one', '{"role":"TH","scope":"Column"}']]) {
  test('DOM focus recovery: Save restores the newly rendered control for ' + id, async () => {
    const saved = repairControlsFixture(), before = JSON.stringify(saved);
    const url = '/api/workspaces/' + saved.workspace_id + '/edit';
    const payload = {revision: 7, id, value};
    const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: editedView(saved, id, value)}]});
    await openSavedReview(result);
    await showStructure(result);
    const card = cardFor(result, id), selects = selectsFor(card);
    if (id === 'heading-one') selects[0].value = value;
    else { selects[0].value = 'TH'; selects[1].value = 'Column'; }
    const save = buttonNamed(card, 'Save edit');
    save.focus();
    await result.dispatch(save, 'click');
    assertFreshFocus(result, buttonNamed(cardFor(result, id), 'Save edit'), save);
    assert.equal(JSON.stringify(saved), before);
    expectOnlyMutations(result, [{url, payload}]);
  });
}

test('DOM focus recovery: explicit Accept restores the matching new Accept button after edit and approval', async () => {
  const saved = repairControlsFixture();
  const prefix = '/api/workspaces/' + saved.workspace_id;
  const edited = editedView(saved, 'heading-one', 'H4');
  const accepted = structuredClone(edited);
  accepted.revision = 9;
  accepted.decisions.find(item => item.id === 'heading-one').status = 'approved';
  const expected = [
    {url: prefix + '/edit', payload: {revision: 7, id: 'heading-one', value: 'H4'}, response: edited},
    {url: prefix + '/approve', payload: {revision: 8, id: 'heading-one', reviewer: 'Authored focus reviewer'}, response: accepted},
  ];
  const result = await bootSavedReview(saved, {expectedMutations: expected});
  await openSavedReview(result);
  await showStructure(result);
  const card = cardFor(result, 'heading-one');
  selectsFor(card)[0].value = 'H4';
  result.getNode('reviewer').value = 'Authored focus reviewer';
  const accept = buttonNamed(card, 'Accept this value');
  accept.focus();
  await result.dispatch(accept, 'click');
  assertFreshFocus(result, buttonNamed(cardFor(result, 'heading-one'), 'Accept this value'), accept);
  expectOnlyMutations(result, expected.map(({url, payload}) => ({url, payload})));
});

test('DOM focus recovery: copied language draft focuses its editable value in Document edits without approval', async () => {
  const saved = repairControlsFixture();
  const url = '/api/workspaces/' + saved.workspace_id + '/edit';
  const payload = {revision: 7, id: 'language-control', value: 'es'};
  const result = await bootSavedReview(saved, {expectedMutations: [{url, payload,
    response: editedView(saved, 'language-control', 'es')}]});
  await openSavedReview(result);
  await result.dispatch('tab-checks', 'click');
  const copy = buttonNamed(result.getNode('repair-findings'), 'Use es as a language draft');
  copy.focus();
  await result.dispatch(copy, 'click');
  const field = descendants(cardFor(result, 'language-control')).find(node => node.tagName === 'INPUT');
  assertFreshFocus(result, field, copy);
  assert.equal(field.value, 'es');
  assert.equal(result.getNode('panel-decisions').hidden, false);
  assert.equal(result.getNode('apply').disabled, true);
  expectOnlyMutations(result, [{url, payload}]);
});

test('DOM focus recovery: reporting a problem restores its own new Report button, preserving the other occurrence', async () => {
  const saved = repairControlsFixture();
  const response = structuredClone(saved);
  response.revision = 8;
  response.manual_items[1].status = 'blocked';
  response.manual_items[1].notes = 'Authored focus problem';
  const url = '/api/workspaces/' + saved.workspace_id + '/review';
  const payload = {revision: 7, id: 'figure-occurrence-b', status: 'blocked',
    reviewer: 'Authored focus reviewer', notes: 'Authored focus problem'};
  const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response}]});
  await openSavedReview(result);
  await result.dispatch('tab-checks', 'click');
  result.getNode('reviewer').value = 'Authored focus reviewer';
  notesInput(manualCards(result)[1]).value = payload.notes;
  const report = buttonNamed(manualCards(result)[1], 'Report a problem');
  report.focus();
  await result.dispatch(report, 'click');
  assertFreshFocus(result, buttonNamed(manualCards(result)[1], 'Report a problem'), report);
  assert.equal(notesInput(manualCards(result)[0]).value, saved.manual_items[0].notes);
  expectOnlyMutations(result, [{url, payload}]);
});

test('DOM focus recovery: Return to pending focuses that occurrence note when its Return button disappears', async () => {
  const saved = repairControlsFixture();
  const response = structuredClone(saved);
  response.revision = 8;
  response.manual_items[0].status = 'pending';
  response.manual_items[0].notes = '';
  const url = '/api/workspaces/' + saved.workspace_id + '/review';
  const payload = {revision: 7, id: 'figure-occurrence-a', status: 'pending', reviewer: 'Authored focus reviewer'};
  const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response}]});
  await openSavedReview(result);
  await result.dispatch('tab-checks', 'click');
  result.getNode('reviewer').value = 'Authored focus reviewer';
  const pending = buttonNamed(manualCards(result)[0], 'Return to pending');
  pending.focus();
  await result.dispatch(pending, 'click');
  assertFreshFocus(result, notesInput(manualCards(result)[0]), pending);
  assert.equal(notesInput(manualCards(result)[0]).value, '');
  expectOnlyMutations(result, [{url, payload}]);
});

test('DOM focus recovery: selected group approval retains the group action without selecting new members', async () => {
  const saved = repairControlsFixture();
  const response = structuredClone(saved);
  response.revision = 8;
  response.manual_items[1].status = 'approved';
  const url = '/api/workspaces/' + saved.workspace_id + '/group';
  const payload = {revision: 7, group_id: 'figures', member_ids: ['figure-occurrence-b'],
    membership_digest: 'authored-figures', reviewer: 'Authored focus reviewer'};
  const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response}]});
  await openSavedReview(result);
  await result.dispatch('tab-checks', 'click');
  result.getNode('reviewer').value = 'Authored focus reviewer';
  manualCards(result)[1].children[0].children[0].children[0].checked = true;
  result.getNode('review-confirm').checked = true;
  const approve = result.getNode('approve-group');
  approve.focus();
  await result.dispatch(approve, 'click');
  assert.equal(result.document.activeElement, approve);
  assert.equal(result.getNode('review-confirm').checked, false);
  assert(manualCards(result).every(card => !card.children[0].children[0].children[0].checked));
  assert.deepEqual(result.mutationRequests, [{url, payload}]);
  assert.deepEqual(result.remainingMutations, []);
  assert.deepEqual(result.unexpectedRequests, []);
});

test('DOM focus recovery: a delayed Save does not steal a newer focus choice in the same workspace', async () => {
  const saved = repairControlsFixture(), delayed = deferredResponse();
  const url = '/api/workspaces/' + saved.workspace_id + '/edit';
  const payload = {revision: 7, id: 'heading-one', value: 'H3'};
  const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: delayed.promise}]});
  await openSavedReview(result);
  await showStructure(result);
  const card = cardFor(result, 'heading-one');
  selectsFor(card)[0].value = 'H3';
  const save = buttonNamed(card, 'Save edit');
  save.focus();
  const saving = result.dispatch(save, 'click');
  await settle();
  const nextFocus = result.getNode('reviewer');
  nextFocus.focus();
  delayed.resolve(editedView(saved, 'heading-one', 'H3'));
  await saving;
  assert.equal(result.document.activeElement, nextFocus);
  expectOnlyMutations(result, [{url, payload}]);
});

test('DOM focus recovery: a delayed structural Save cannot focus an absent control after page navigation', async () => {
  const saved = repairControlsFixture(), delayed = deferredResponse();
  const url = '/api/workspaces/' + saved.workspace_id + '/edit';
  const payload = {revision: 7, id: 'heading-one', value: 'H3'};
  const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: delayed.promise}]});
  await openSavedReview(result);
  await showStructure(result);
  const card = cardFor(result, 'heading-one');
  selectsFor(card)[0].value = 'H3';
  const save = buttonNamed(card, 'Save edit');
  save.focus();
  const saving = result.dispatch(save, 'click');
  await settle();
  const next = result.getNode('next-page');
  next.focus();
  await result.dispatch(next, 'click');
  delayed.resolve(editedView(saved, 'heading-one', 'H3'));
  await saving;
  assert.equal(result.getNode('page-number').value, '2');
  assert.equal(result.document.activeElement, next);
  assert.equal(decisionCards(result).some(card => card.dataset.decisionId === 'heading-one'), false);
  expectOnlyMutations(result, [{url, payload}]);
});

test('DOM focus recovery: a manual response cannot move focus back to an occurrence hidden by a newer group choice', async () => {
  const saved = repairControlsFixture(), delayed = deferredResponse();
  const response = structuredClone(saved);
  response.revision = 8;
  response.manual_items[1].status = 'blocked';
  response.manual_items[1].notes = 'Deferred authored problem';
  const url = '/api/workspaces/' + saved.workspace_id + '/review';
  const payload = {revision: 7, id: 'figure-occurrence-b', status: 'blocked', reviewer: 'Authored focus reviewer', notes: 'Deferred authored problem'};
  const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: delayed.promise}]});
  await openSavedReview(result);
  await result.dispatch('tab-checks', 'click');
  result.getNode('reviewer').value = 'Authored focus reviewer';
  notesInput(manualCards(result)[1]).value = payload.notes;
  const report = buttonNamed(manualCards(result)[1], 'Report a problem');
  report.focus();
  const reporting = result.dispatch(report, 'click');
  await settle();
  const group = result.getNode('group-choice');
  group.focus();
  group.value = 'order';
  await result.dispatch(group, 'change');
  delayed.resolve(response);
  await reporting;
  assert.equal(result.getNode('group-choice').value, 'order');
  assert.equal(result.document.activeElement, group);
  assert.equal(manualCards(result)[0].dataset.reviewId, 'reading-order-c');
  expectOnlyMutations(result, [{url, payload}]);
});

for (const returnToA of [false, true]) {
test('DOM focus recovery: an obsolete language response cannot focus or alter a later field after ' + (returnToA ? 'A to B to A' : 'A to B'), async () => {
  const {first, second} = navigationFixtures(), delayed = deferredResponse();
  const url = '/api/workspaces/' + first.workspace_id + '/edit';
  const payload = {revision: 7, id: 'language-control', value: 'es'};
  const result = await bootNavigation(first, second, {expectedMutations: [{url, payload, response: delayed.promise}]});
  await openNamedWorkspace(result, 'workspace-A.pdf');
  const copy = buttonNamed(result.getNode('repair-findings'), 'Use es as a language draft');
  copy.focus();
  const copying = result.dispatch(copy, 'click');
  await settle();
  await result.dispatch('back', 'click');
  await openNamedWorkspace(result, 'workspace-B.pdf');
  if (returnToA) {
    await result.dispatch('back', 'click');
    await openNamedWorkspace(result, 'workspace-A.pdf');
  }
  const currentField = descendants(cardFor(result, 'language-control')).find(node => node.tagName === 'INPUT');
  currentField.focus();
  delayed.resolve(editedView(first, 'language-control', 'es'));
  await copying;
  assert.equal(result.document.activeElement, currentField);
  assertVisibleWorkspace(result, returnToA ? 'workspace-A.pdf' : 'workspace-B.pdf', returnToA ? 'en-US' : 'de');
  expectOnlyMutations(result, [{url, payload}]);
});
}

test('DOM focus races: delayed language copy respects a newer Review checks tab choice', async () => {
  const saved = repairControlsFixture(), delayed = deferredResponse();
  const url = '/api/workspaces/' + saved.workspace_id + '/edit';
  const payload = {revision: 7, id: 'language-control', value: 'es'};
  const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: delayed.promise}]});
  await openSavedReview(result);
  const copy = buttonNamed(result.getNode('repair-findings'), 'Use es as a language draft');
  copy.focus();
  const copying = result.dispatch(copy, 'click');
  await settle();
  const checks = result.getNode('tab-checks');
  checks.focus();
  await result.dispatch(checks, 'click');
  delayed.resolve(editedView(saved, 'language-control', 'es'));
  await copying;
  assert.equal(result.getNode('panel-checks').hidden, false);
  assert.equal(result.getNode('tab-checks').attributes['aria-selected'], 'true');
  assert.equal(result.document.activeElement, checks);
  expectOnlyMutations(result, [{url, payload}]);
});

async function pendingHeadingSave(options = {}) {
  const saved = repairControlsFixture(), delayed = deferredResponse();
  const url = '/api/workspaces/' + saved.workspace_id + '/edit';
  const payload = {revision: 7, id: 'heading-one', value: 'H3'};
  const result = await bootSavedReview(saved, {...options, expectedMutations: [
    {url, payload, response: delayed.promise}, ...(options.expectedMutations || []),
  ]});
  await openSavedReview(result);
  await showStructure(result);
  const card = cardFor(result, 'heading-one');
  selectsFor(card)[0].value = 'H3';
  const save = buttonNamed(card, 'Save edit');
  save.focus();
  const saving = result.dispatch(save, 'click');
  await settle();
  return {saved, delayed, url, payload, result, saving};
}

test('DOM focus races: delayed Save preserves a newer language field, literal draft and text selection', async () => {
  const {saved, delayed, url, payload, result, saving} = await pendingHeadingSave();
  const field = descendants(cardFor(result, 'language-control')).find(node => node.tagName === 'INPUT');
  field.focus();
  field.value = 'fr-CA <literal> & "draft"';
  field.setSelectionRange(2, 11, 'backward');
  delayed.resolve(editedView(saved, 'heading-one', 'H3'));
  await saving;
  const current = descendants(cardFor(result, 'language-control')).find(node => node.tagName === 'INPUT');
  assertFreshFocus(result, current, field);
  assert.equal(current.value, 'fr-CA <literal> & "draft"');
  assert.deepEqual([current.selectionStart, current.selectionEnd, current.selectionDirection], [2, 11, 'backward']);
  assert.equal(saved.decisions.find(item => item.id === 'language-control').value, 'en-US');
  assert.equal(result.getNode('apply').disabled, true);
  expectOnlyMutations(result, [{url, payload}]);
});

for (const draft of ['', 'An unsaved <literal> title\nwith a second line & accents: café']) {
test('DOM focus races: delayed Save preserves a newer title textarea including ' + (draft ? 'multiline text' : 'an empty draft'), async () => {
  const {saved, delayed, url, payload, result, saving} = await pendingHeadingSave();
  const field = descendants(cardFor(result, 'title-control')).find(node => node.tagName === 'TEXTAREA');
  field.focus();
  field.value = draft;
  field.setSelectionRange(0, draft.length, 'forward');
  delayed.resolve(editedView(saved, 'heading-one', 'H3'));
  await saving;
  const current = descendants(cardFor(result, 'title-control')).find(node => node.tagName === 'TEXTAREA');
  assertFreshFocus(result, current, field);
  assert.equal(current.value, draft);
  assert.deepEqual([current.selectionStart, current.selectionEnd], [0, draft.length]);
  expectOnlyMutations(result, [{url, payload}]);
});
}

test('DOM focus races: a newer same-card heading choice remains an unsaved local draft', async () => {
  const {saved, delayed, url, payload, result, saving} = await pendingHeadingSave();
  const field = selectsFor(cardFor(result, 'heading-one'))[0];
  field.focus();
  field.value = 'H5';
  delayed.resolve(editedView(saved, 'heading-one', 'H3'));
  await saving;
  const current = selectsFor(cardFor(result, 'heading-one'))[0];
  assertFreshFocus(result, current, field);
  assert.equal(current.value, 'H5');
  assert.equal(result.getNode('apply').disabled, true);
  expectOnlyMutations(result, [{url, payload}]);
});

test('DOM focus races: paired table role/scope survive an older Save and use its returned revision only after explicit Save', async () => {
  const saved = repairControlsFixture(), url = '/api/workspaces/' + saved.workspace_id + '/edit';
  const value = '{"role":"TH","scope":"Both"}';
  const secondPayload = {revision: 8, id: 'table-one', value};
  const firstResponse = editedView(saved, 'heading-one', 'H3');
  const state = await pendingHeadingSave({expectedMutations: [{url, payload: secondPayload,
    response: editedView(firstResponse, 'table-one', value, 9)}]});
  const {delayed, payload, result, saving} = state;
  const [role, scope] = selectsFor(cardFor(result, 'table-one'));
  role.value = 'TH';
  scope.focus();
  scope.value = 'Both';
  delayed.resolve(firstResponse);
  await saving;
  const current = selectsFor(cardFor(result, 'table-one'));
  assertFreshFocus(result, current[1], scope);
  assert.deepEqual(current.map(node => node.value), ['TH', 'Both']);
  assert.deepEqual(result.mutationRequests, [{url, payload}], 'Restoring a local draft cannot save or approve it.');
  const save = buttonNamed(cardFor(result, 'table-one'), 'Save edit');
  save.focus();
  await result.dispatch(save, 'click');
  expectOnlyMutations(result, [{url, payload}, {url, payload: secondPayload}]);
});

test('DOM focus races: reporting one occurrence preserves a newer different note and selection without submitting it', async () => {
  const saved = repairControlsFixture(), delayed = deferredResponse();
  const response = structuredClone(saved);
  response.revision = 8;
  response.manual_items[0].notes = 'First submitted problem';
  const url = '/api/workspaces/' + saved.workspace_id + '/review';
  const payload = {revision: 7, id: 'figure-occurrence-a', status: 'blocked', reviewer: 'Authored reviewer', notes: response.manual_items[0].notes};
  const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: delayed.promise}]});
  await openSavedReview(result);
  await result.dispatch('tab-checks', 'click');
  result.getNode('reviewer').value = 'Authored reviewer';
  notesInput(manualCards(result)[0]).value = payload.notes;
  const report = buttonNamed(manualCards(result)[0], 'Report a problem');
  report.focus();
  const reporting = result.dispatch(report, 'click');
  await settle();
  const note = notesInput(manualCards(result)[1]);
  note.focus();
  note.value = 'New unsaved <literal> & note';
  note.setSelectionRange(4, 11, 'backward');
  delayed.resolve(response);
  await reporting;
  const current = notesInput(manualCards(result)[1]);
  assertFreshFocus(result, current, note);
  assert.equal(current.value, 'New unsaved <literal> & note');
  assert.deepEqual([current.selectionStart, current.selectionEnd, current.selectionDirection], [4, 11, 'backward']);
  assert.equal(notesInput(manualCards(result)[0]).value, payload.notes);
  assert.equal(response.manual_items[1].notes, saved.manual_items[1].notes);
  expectOnlyMutations(result, [{url, payload}]);
});

test('DOM focus races: a newer page field retains its own draft without restoring the old page control', async () => {
  const {saved, delayed, url, payload, result, saving} = await pendingHeadingSave();
  await result.dispatch('next-page', 'click');
  const field = selectsFor(cardFor(result, 'heading-two'))[0];
  field.focus();
  field.value = 'H6';
  delayed.resolve(editedView(saved, 'heading-one', 'H3'));
  await saving;
  const current = selectsFor(cardFor(result, 'heading-two'))[0];
  assertFreshFocus(result, current, field);
  assert.equal(current.value, 'H6');
  assert.equal(result.getNode('page-number').value, '2');
  assert.equal(decisionCards(result).some(card => card.dataset.decisionId === 'heading-one'), false);
  expectOnlyMutations(result, [{url, payload}]);
});

test('DOM focus races: a newer selected group note remains local to that group after an older response', async () => {
  const {saved, delayed, url, payload, result, saving} = await pendingHeadingSave();
  await result.dispatch('tab-checks', 'click');
  result.getNode('group-choice').value = 'order';
  await result.dispatch('group-choice', 'change');
  const note = notesInput(manualCards(result)[0]);
  note.focus();
  note.value = 'A newer reading-order draft';
  delayed.resolve(editedView(saved, 'heading-one', 'H3'));
  await saving;
  const card = manualCards(result)[0], current = notesInput(card);
  assertFreshFocus(result, current, note);
  assert.equal(card.dataset.reviewId, 'reading-order-c');
  assert.equal(result.getNode('group-choice').value, 'order');
  assert.equal(current.value, 'A newer reading-order draft');
  assert.equal(result.getNode('panel-checks').hidden, false);
  expectOnlyMutations(result, [{url, payload}]);
});

test('DOM focus races: newly unsafe structural controls cannot receive a restored draft or focus', async () => {
  const {saved, delayed, url, payload, result, saving} = await pendingHeadingSave();
  const [role, scope] = selectsFor(cardFor(result, 'table-one'));
  role.value = 'TH';
  scope.focus();
  scope.value = 'Both';
  const response = editedView(saved, 'heading-one', 'H3');
  response.decisions.find(item => item.id === 'table-one').structural_eligible = false;
  delayed.resolve(response);
  await saving;
  const current = selectsFor(cardFor(result, 'table-one'));
  assert(current.every(node => node.disabled));
  assert.deepEqual(current.map(node => node.value), ['TD', '']);
  assert.equal(result.document.activeElement, result.document.body);
  expectOnlyMutations(result, [{url, payload}]);
});

test('DOM focus races: a job started during a pending Save keeps refreshed fields disabled and forbids focus restoration', async () => {
  const saved = repairControlsFixture(), jobUrl = '/api/workspaces/' + saved.workspace_id + '/auto-fix';
  const jobPayload = {revision: 7, consent: true, use_ai: false, ai_consent: false,
    endpoint: '', model: '', include_images: false, reasoning_effort: null};
  const {delayed, url, payload, result, saving} = await pendingHeadingSave({captureTimers: true,
    expectedMutations: [{url: jobUrl, payload: jobPayload, response: {job_id: 'authored-pending-save-job'}}]});
  const field = descendants(cardFor(result, 'language-control')).find(node => node.tagName === 'INPUT');
  field.focus();
  field.value = 'fr-CA';
  await result.dispatch('auto-fix', 'click');
  delayed.resolve(editedView(saved, 'heading-one', 'H3'));
  await saving;
  const current = descendants(cardFor(result, 'language-control')).find(node => node.tagName === 'INPUT');
  assert.equal(current.disabled, true);
  assert.equal(result.document.activeElement, result.document.body);
  assert.equal(current.value, 'en-US', 'A disabled field is never overwritten with a captured draft.');
  assert(descendants(result.getNode('decisions')).filter(node => ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(node.tagName)).every(node => node.disabled));
  assert.deepEqual(result.mutationRequests, [{url, payload}, {url: jobUrl, payload: jobPayload}]);
  assert.deepEqual(result.remainingMutations, []);
  assert.deepEqual(result.unexpectedRequests, []);
});

// Shutdown regressions exercise the complete actual script and its real
// listeners. The named Stop response is an HTTP double, never a live service
// shutdown. Deferred body reads model requests already in flight at its ack.
const STOP_NOTICE = 'PDF Remediator has stopped. You can close this window.';
function assertStoppedNotice(result) {
  assert.equal(result.getNode('notice').textContent, STOP_NOTICE);
  assert.equal(result.getNode('notice').hidden, false);
  assert.equal(result.getNode('notice').classList.contains('error'), false);
}
function stopExpectation(options = {}) {
  return {url: '/api/stop', payload: {}, response: {status: 'stopping'}, ...options};
}

for (const kind of ['original', 'candidate', 'context']) {
  for (const outcome of ['failure', 'success']) {
    test(`DOM shutdown races: late ${kind} ${outcome} cannot replace acknowledged Stop or paint stale content`, async () => {
      const saved = repairControlsFixture(), before = JSON.stringify(saved), delayed = deferredResponse();
      const url = '/api/workspaces/' + saved.workspace_id + (kind === 'context' ? '/context?page=1' : '/page?kind=' + kind + '&page=1');
      const result = await bootSavedReview(saved, {
        expectedReads: [{url, response: delayed.promise}], expectedMutations: [stopExpectation()],
      });
      const opening = result.dispatch(result.getNode('documents').children[0], 'click');
      await settle();
      assert.equal(result.remainingReads.length, 0, 'The real opening listener must have started the exact deferred read.');
      assert.equal(result.getNode('review').hidden, false);
      await result.dispatch('stop', 'click');
      assertStoppedNotice(result);
      const priorContext = result.getNode('page-context').textContent;
      const priorImage = kind === 'context' ? null : result.getNode(kind + '-page').src;
      const priorUrls = result.objectUrls.length;
      if (outcome === 'failure') delayed.reject(new Error('Failed to fetch'));
      else delayed.resolve(kind === 'context' ? {text: 'Authored late context must not paint after Stop'} : {authoredImagePlaceholder: true});
      await opening;
      assertStoppedNotice(result);
      assert.equal(result.getNode('page-context').textContent, priorContext);
      if (kind !== 'context') assert.equal(result.getNode(kind + '-page').src, priorImage);
      assert.equal(result.objectUrls.length, priorUrls, 'A late preview may not allocate a new displayed object URL after shutdown.');
      assert.equal(JSON.stringify(saved), before);
      expectOnlyMutations(result, [{url: '/api/stop', payload: {}}]);
    });
  }
}

for (const outcome of ['failure', 'running-response']) {
  test('DOM shutdown races: in-flight polling ' + outcome + ' cannot replace Stop, rerender jobs or schedule another poll', async () => {
    const saved = repairControlsFixture(), delayed = deferredResponse();
    const jobUrl = '/api/workspaces/' + saved.workspace_id + '/auto-fix';
    const jobPayload = {revision: 7, consent: true, use_ai: false, ai_consent: false,
      endpoint: '', model: '', include_images: false, reasoning_effort: null};
    const result = await bootSavedReview(saved, {captureTimers: true, expectedMutations: [
      {url: jobUrl, payload: jobPayload, response: {job_id: 'authored-shutdown-job'}}, stopExpectation(),
    ]});
    await openSavedReview(result);
    await result.dispatch('auto-fix', 'click');
    assert.equal(result.scheduledTimers.length, 1);
    result.remainingReads.push({url: '/api/dashboard', response: delayed.promise});
    const polling = result.scheduledTimers[0].callback();
    await settle();
    assert.equal(result.remainingReads.length, 0);
    await result.dispatch('stop', 'click');
    assertStoppedNotice(result);
    assert.equal(result.scheduledTimers[0].cancelled, true);
    assert.equal(result.getNode('auto-status').hidden, true);
    if (outcome === 'failure') delayed.reject(new Error('Failed to fetch'));
    else delayed.resolve({documents: [], jobs: [{id: 'authored-shutdown-job', label: 'Authored running job', status: 'running', progress: []}]});
    await polling;
    await settle();
    assertStoppedNotice(result);
    assert.equal(result.getNode('auto-status').hidden, true, 'A late response may not bring the status line back after Stop.');
    assert.equal(result.getNode('job-bar').hidden, true);
    assert.equal(result.scheduledTimers.length, 1, 'An in-flight response must not restart polling after the stop timer was cleared.');
    assert.deepEqual(result.mutationRequests, [{url: jobUrl, payload: jobPayload}, {url: '/api/stop', payload: {}}]);
    assert.deepEqual(result.remainingMutations, []);
    assert.deepEqual(result.unexpectedRequests, []);
  });
}

for (const accepting of [false, true]) {
  test('DOM shutdown races: pending ' + (accepting ? 'Accept stops before its approval request' : 'Save cannot rerender or overwrite Stop'), async () => {
    const saved = repairControlsFixture(), delayed = deferredResponse();
    const url = '/api/workspaces/' + saved.workspace_id + '/edit';
    const payload = {revision: 7, id: 'title-control', value: 'Authored pending title before shutdown'};
    const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: delayed.promise}, stopExpectation()]});
    await openSavedReview(result);
    result.getNode('reviewer').value = 'Authored shutdown test reviewer';
    const card = cardFor(result, 'title-control');
    descendants(card).find(node => node.tagName === 'TEXTAREA').value = payload.value;
    const pending = result.dispatch(buttonNamed(card, accepting ? 'Accept this value' : 'Save edit'), 'click');
    await settle();
    assert.deepEqual(result.mutationRequests, [{url, payload}]);
    await result.dispatch('stop', 'click');
    assertStoppedNotice(result);
    const priorCards = [...result.getNode('decisions').children];
    delayed.resolve(editedView(saved, 'title-control', payload.value));
    await pending;
    assertStoppedNotice(result);
    assert.deepEqual(result.getNode('decisions').children, priorCards, 'An obsolete action cannot replace controls after acknowledged shutdown.');
    expectOnlyMutations(result, [{url, payload}, {url: '/api/stop', payload: {}}]);
  });
}

for (const failure of ['network', 'refusal']) {
  test('DOM shutdown failures: ' + failure + ' stays visible and retryable without freezing ordinary actions', async () => {
    const saved = repairControlsFixture(), delayed = deferredResponse();
    const url = '/api/workspaces/' + saved.workspace_id + '/edit';
    const payload = {revision: 7, id: 'language-control', value: 'fr-CA'};
    const failureMessage = failure === 'network' ? 'Failed to fetch' : 'Authored Stop refusal';
    const result = await bootSavedReview(saved, {expectedMutations: [
      stopExpectation({response: delayed.promise, ok: failure !== 'refusal'}),
      {url, payload, response: editedView(saved, payload.id, payload.value)}, stopExpectation(),
    ]});
    await openSavedReview(result);
    const stopping = result.dispatch('stop', 'click');
    await settle();
    // Refusal/network failure must never be converted into successful shutdown.
    if (failure === 'network') delayed.reject(new Error(failureMessage));
    else delayed.resolve({error: failureMessage});
    await stopping;
    assert.equal(result.getNode('notice').textContent, failureMessage);
    assert.equal(result.getNode('notice').classList.contains('error'), true);
    assert.equal(result.getNode('stop').disabled, false);
    const card = cardFor(result, payload.id);
    descendants(card).find(node => node.tagName === 'INPUT').value = payload.value;
    await result.dispatch(buttonNamed(card, 'Save edit'), 'click');
    assert.match(result.getNode('notice').textContent, /Draft saved/);
    await result.dispatch('stop', 'click');
    assertStoppedNotice(result);
    expectOnlyMutations(result, [{url: '/api/stop', payload: {}}, {url, payload}, {url: '/api/stop', payload: {}}]);
  });
}

test('DOM shutdown races: duplicate clicks while Stop is pending send only one authored request', async () => {
  const delayed = deferredResponse();
  const result = await boot({stored: VALID, expectedMutations: [stopExpectation({response: delayed.promise})]});
  const stopping = result.dispatch('stop', 'click');
  await settle();
  try {
    assert.equal(result.getNode('stop').disabled, true);
    await result.dispatch('stop', 'click');
    assert.deepEqual(result.mutationRequests, [{url: '/api/stop', payload: {}}]);
  } finally {
    delayed.resolve({status: 'stopping'});
    await stopping;
  }
  assertStoppedNotice(result);
  expectOnlyMutations(result, [{url: '/api/stop', payload: {}}]);
});

test('DOM shutdown races: acknowledged Stop preserves its notice and refuses later wrapped navigation or refresh requests', async () => {
  const saved = repairControlsFixture();
  const result = await bootSavedReview(saved, {expectedMutations: [stopExpectation()]});
  await openSavedReview(result);
  await result.dispatch('stop', 'click');
  const requestCount = result.requests.length;
  const priorCards = [...result.getNode('decisions').children];
  await result.dispatch('back', 'click');
  await result.dispatch('refresh', 'click');
  assertStoppedNotice(result);
  assert.equal(result.requests.length, requestCount);
  assert.equal(result.getNode('review').hidden, false);
  assert.deepEqual(result.getNode('decisions').children, priorCards);
  expectOnlyMutations(result, [{url: '/api/stop', payload: {}}]);
});

const OCR_UNAVAILABLE_MESSAGE = 'OCR is not installed or configured in this copy. Keep OCR off for PDFs with selectable text. Scanned text needs an OCR-equipped setup or an accessible source document.';
const OCR_PRESENT_MESSAGE = 'OCR components are present. Their versions and preservation checks still run when OCR is requested.';
const ocrCapability = available => ({ocr: {available, message: available ? OCR_PRESENT_MESSAGE : OCR_UNAVAILABLE_MESSAGE, runtime_verified: false}});
const ocrOptions = result => Object.fromEntries(result.getNode('new-ocr').children.map(option => [option.value, option]));

async function selectAuthoredPDF(result) {
  const file = {name: 'Authored selectable text and logo.pdf', size: 64, authoredFileDouble: true};
  result.getNode('files').files = [file];
  await result.dispatch('files', 'change');
  assert.equal(result.getNode('process').disabled, false);
  return file;
}

test('OCR HTML: only off starts selectable and persistent help explains scanned text versus logos', () => {
  const html = fs.readFileSync(path.join(path.dirname(appPath), 'index.html'), 'utf8');
  const select = /<select id="new-ocr"(?=\s|>)[^>]*>([\s\S]*?)<\/select>/.exec(html);
  assert(select);
  assert.match(select[0], /aria-describedby="ocr-availability ocr-help"/);
  assert.match(select[1], /<option value="off">Leave OCR off<\/option>/);
  for (const mode of ['skip', 'textless', 'redo']) assert.match(select[1], new RegExp('<option value="' + mode + '" disabled>'));
  assert.match(html, /id="ocr-availability"[^>]*aria-live="polite"/);
  assert.match(html, /Logos and other pictures alone do not need OCR\./);
});

test('OCR HTML gives the new page selection and layout clear labels and persistent review guidance', () => {
  const html = fs.readFileSync(path.join(path.dirname(appPath), 'index.html'), 'utf8');
  assert.match(html, /<option value="textless" disabled>Add text only on wholly scanned pages<\/option>/);
  assert.match(html, /<option value="angles">Tilted or vertical text<\/option>/);
  assert.match(html, /<option value="turns">Pages stored sideways or upside down<\/option>/);
  assert.match(html, /Pages with existing text keep their text; scanned regions on those pages still need review\./);
  assert.match(html, /separate processing run/);
  assert.match(html, /Check every word, table cell and reading order/);
});

test('CIDSet HTML: the checkbox starts off and the dialog explains the removal in plain words with both choices', () => {
  const html = fs.readFileSync(path.join(path.dirname(appPath), 'index.html'), 'utf8');
  assert.match(html, /<input id="new-cidset" type="checkbox"[^>]*>/);
  assert.doesNotMatch(html, /id="new-cidset"[^>]*checked/);
  const dialog = /<dialog id="cidset-dialog"[\s\S]*?<\/dialog>/.exec(html);
  assert(dialog, 'The explanation dialog is part of the page.');
  assert.match(dialog[0], /<form method="dialog">/);
  assert.match(dialog[0], /It does not change any page picture, any text, or the drawing of any character\./);
  assert.match(dialog[0], /Your original PDF is never changed/);
  assert.match(dialog[0], /<button value="allow" class="primary">Remove the lists<\/button>/);
  assert.match(dialog[0], /<button value="keep" class="secondary">Keep the lists<\/button>/);
});

test('CIDSet consent: the box stays checked only after the dialog answers yes; every other way out unchecks it', async () => {
  const result = await boot({stored: VALID, capabilities: ocrCapability(true)});
  const dialog = result.getNode('cidset-dialog');
  const box = result.getNode('new-cidset');
  let shown = 0;
  dialog.showModal = () => { shown += 1; };
  box.checked = true;
  await result.dispatch('new-cidset', 'change');
  assert.equal(shown, 1, 'Checking the box opens the explanation.');
  assert.equal(dialog.returnValue, '');
  dialog.returnValue = 'allow';
  await result.dispatch('cidset-dialog', 'close');
  assert.equal(box.checked, true);
  for (const answer of ['keep', '']) {
    box.checked = true;
    await result.dispatch('new-cidset', 'change');
    dialog.returnValue = answer;
    await result.dispatch('cidset-dialog', 'close');
    assert.equal(box.checked, false, 'Answer "' + answer + '" must leave the lists in place.');
  }
  box.checked = false;
  await result.dispatch('new-cidset', 'change');
  assert.equal(shown, 3, 'Unchecking never opens the dialog.');
});

test('CIDSet consent: a browser that cannot show the dialog leaves the lists in place and says so', async () => {
  const result = await boot({stored: VALID, capabilities: ocrCapability(true)});
  const box = result.getNode('new-cidset');
  box.checked = true;
  await result.dispatch('new-cidset', 'change');
  assert.equal(box.checked, false);
  assert.match(result.getNode('notice').textContent, /left in place/);
});

test('CIDSet consent: an allowed removal travels in the exact process request', async () => {
  const file = {name: 'Authored font lists.pdf', size: 64, authoredFileDouble: true};
  const payload = {inputs: ['authored-cidset-id'], options: {language: 'en-US', document_kind: 'unknown', ocr_mode: 'off', ocr_profile: 'standard',
    allow_tag_regrouping: false, repair_source_mappings: false, remove_cidset: true}};
  const result = await boot({stored: VALID, capabilities: ocrCapability(true), captureTimers: true,
    expectedUploads: [{file, id: 'authored-cidset-id'}],
    expectedMutations: [{url: '/api/process', payload, response: {job_id: 'authored-cidset-job'}}]});
  const dialog = result.getNode('cidset-dialog');
  dialog.showModal = () => {};
  result.getNode('files').files = [file];
  await result.dispatch('files', 'change');
  result.getNode('new-language').value = 'en-US';
  const kind = result.document.createElement('option'); kind.value = 'unknown';
  result.getNode('new-kind').append(kind);
  result.getNode('new-cidset').checked = true;
  await result.dispatch('new-cidset', 'change');
  dialog.returnValue = 'allow';
  await result.dispatch('cidset-dialog', 'close');
  await result.dispatch('process', 'click');
  assert.deepEqual(result.mutationRequests, [{url: '/api/process', payload}]);
  assert.deepEqual(result.remainingMutations, []);
});

test('OCR startup: without session authority no request runs and non-off choices remain disabled', async () => {
  const result = await boot();
  assert.deepEqual(result.requests, []);
  const options = ocrOptions(result);
  assert.equal(options.off.disabled, false);
  assert.equal(options.skip.disabled, true);
  assert.equal(options.textless.disabled, true);
  assert.equal(options.redo.disabled, true);
  assert.equal(result.getNode('new-ocr').value, 'off');
  assert.equal(result.getNode('new-ocr-profile').disabled, true);
  assert.match(result.getNode('ocr-availability').textContent, /availability is not confirmed/);
});

test('OCR unavailable: metadata disables only non-off choices and gives actionable local guidance', async () => {
  const result = await boot({stored: VALID, capabilities: ocrCapability(false)});
  const options = ocrOptions(result);
  assert.equal(options.off.disabled, false);
  assert.equal(options.skip.disabled, true);
  assert.equal(options.textless.disabled, true);
  assert.equal(options.redo.disabled, true);
  assert.equal(result.getNode('new-ocr').disabled, false, 'Selectable-text processing remains available.');
  assert.equal(result.getNode('new-ocr').value, 'off');
  assert.equal(result.getNode('new-ocr-profile').disabled, true);
  assert.equal(result.getNode('ocr-availability').textContent, OCR_UNAVAILABLE_MESSAGE);
  assert.equal(result.getNode('notice').hidden, true, 'Availability guidance is separate from an action failure.');
  assert.deepEqual(result.requests, [{url: '/api/dashboard', token: VALID}]);
});

for (const mode of ['off', 'skip', 'textless', 'redo']) {
  test('OCR process: explicit ' + mode + ' stays unchanged in the exact authored upload/process request', async () => {
    const file = {name: 'Authored one-page PDF.pdf', size: 64, authoredFileDouble: true};
    const payload = {inputs: ['authored-upload-id'], options: {language: 'en-US', document_kind: 'unknown', ocr_mode: mode, ocr_profile: 'standard',
      allow_tag_regrouping: false, repair_source_mappings: false, remove_cidset: false}};
    const result = await boot({stored: VALID, capabilities: ocrCapability(mode !== 'off'), captureTimers: true,
      expectedUploads: [{file, id: 'authored-upload-id'}],
      expectedMutations: [{url: '/api/process', payload, response: {job_id: 'authored-process-job'}}]});
    result.getNode('files').files = [file];
    await result.dispatch('files', 'change');
    result.getNode('new-language').value = 'en-US';
    const kind = result.document.createElement('option'); kind.value = 'unknown';
    result.getNode('new-kind').append(kind);
    result.getNode('new-ocr').value = mode;
    await result.dispatch('process', 'click');
    assert.deepEqual(result.uploadRequests, [{url: '/api/upload', name: file.name}]);
    assert.deepEqual(result.mutationRequests, [{url: '/api/process', payload}]);
    assert.deepEqual(result.remainingUploads, []);
    assert.deepEqual(result.remainingMutations, []);
    assert.equal(result.getNode('new-ocr').value, mode);
    assert.equal(result.scheduledTimers.length, 1);
    assert.match(result.getNode('notice').textContent, /Processing started/);
  });
}

for (const [profile, ocrMode] of [['table-lines', 'skip'], ['angles', 'textless'], ['turns', 'textless'], ['turns', 'skip']]) {
test('OCR ' + profile + ' layout is explicit and remains selected while OCR is off', async () => {
  const file = {name: 'Authored table scan.pdf', size: 64, authoredFileDouble: true};
  const payload = {inputs: ['authored-table-id'], options: {language: 'en-US', document_kind: 'unknown',
    ocr_mode: ocrMode, ocr_profile: profile, allow_tag_regrouping: false, repair_source_mappings: false, remove_cidset: false}};
  const result = await boot({stored: VALID, capabilities: ocrCapability(true), captureTimers: true,
    expectedUploads: [{file, id: 'authored-table-id'}],
    expectedMutations: [{url: '/api/process', payload, response: {job_id: 'authored-table-job'}}]});
  assert.equal(result.getNode('new-ocr-profile').disabled, true);
  result.getNode('new-ocr').value = ocrMode;
  await result.dispatch('new-ocr', 'change');
  assert.equal(result.getNode('new-ocr-profile').disabled, false);
  result.getNode('new-ocr-profile').value = profile;
  result.getNode('new-ocr').value = 'off';
  await result.dispatch('new-ocr', 'change');
  assert.equal(result.getNode('new-ocr-profile').disabled, true);
  assert.equal(result.getNode('new-ocr-profile').value, profile);
  result.getNode('new-ocr').value = ocrMode;
  await result.dispatch('new-ocr', 'change');
  result.getNode('files').files = [file];
  await result.dispatch('files', 'change');
  result.getNode('new-language').value = 'en-US';
  const kind = result.document.createElement('option'); kind.value = 'unknown'; result.getNode('new-kind').append(kind);
  await result.dispatch('process', 'click');
  assert.deepEqual(result.mutationRequests, [{url: '/api/process', payload}]);
  assert.equal(result.getNode('new-ocr-profile').value, profile);
});
}

test('OCR unknown page-selection mode is refused before any PDF upload', async () => {
  const result = await boot({stored: VALID, capabilities: ocrCapability(true)});
  await selectAuthoredPDF(result);
  const forged = result.document.createElement('option'); forged.value = 'force';
  result.getNode('new-ocr').append(forged); result.getNode('new-ocr').value = 'force';
  await result.dispatch('process', 'click');
  assert.deepEqual(result.uploadRequests, []);
  assert.deepEqual(result.mutationRequests, []);
  assert.match(result.getNode('notice').textContent, /supported scanned-text option/);
});

test('tilted text with redo is refused before upload and keeps the selected options for correction', async () => {
  const result = await boot({stored: VALID, capabilities: ocrCapability(true)});
  await selectAuthoredPDF(result);
  result.getNode('new-ocr').value = 'redo';
  await result.dispatch('new-ocr', 'change');
  result.getNode('new-ocr-profile').value = 'angles';
  await result.dispatch('process', 'click');
  assert.deepEqual(result.uploadRequests, []);
  assert.deepEqual(result.mutationRequests, []);
  assert.equal(result.getNode('new-ocr').value, 'redo');
  assert.equal(result.getNode('new-ocr-profile').value, 'angles');
  assert.match(result.getNode('notice').textContent, /wholly scanned pages or scan-only OCR option/);
});

test('OCR unknown layout is refused before any PDF upload', async () => {
  const result = await boot({stored: VALID, capabilities: ocrCapability(true)});
  await selectAuthoredPDF(result);
  result.getNode('new-ocr').value = 'skip';
  const forged = result.document.createElement('option'); forged.value = 'unmeasured';
  result.getNode('new-ocr-profile').append(forged); result.getNode('new-ocr-profile').value = 'unmeasured';
  await result.dispatch('process', 'click');
  assert.deepEqual(result.uploadRequests, []);
  assert.deepEqual(result.mutationRequests, []);
  assert.match(result.getNode('notice').textContent, /supported scan layout/);
});

test('OCR present: metadata enables both routes without claiming verified readiness or changing off', async () => {
  const result = await boot({stored: VALID, capabilities: ocrCapability(true)});
  const options = ocrOptions(result);
  assert.equal(options.off.disabled, false);
  assert.equal(options.skip.disabled, false);
  assert.equal(options.textless.disabled, false);
  assert.equal(options.redo.disabled, false);
  assert.equal(result.getNode('new-ocr').value, 'off');
  assert.equal(result.getNode('ocr-availability').textContent, OCR_PRESENT_MESSAGE);
  assert.match(result.getNode('ocr-availability').textContent, /checks still run/);
});

for (const mode of ['skip', 'textless', 'redo']) {
  test('OCR unavailable: forged ' + mode + ' selection is refused before any upload and never downgraded', async () => {
    const result = await boot({stored: VALID, capabilities: ocrCapability(false)});
    await selectAuthoredPDF(result);
    result.getNode('new-ocr').value = mode;
    result.getNode('new-ocr-profile').value = mode === 'textless' ? 'angles' : 'standard';
    assert.equal(result.getNode('new-ocr-profile').disabled, true);
    const requests = [...result.requests];
    await result.dispatch('process', 'click');
    assert.deepEqual(result.requests, requests, 'A rejected OCR request must not begin uploading or processing.');
    assert.deepEqual(result.uploadRequests, []);
    assert.deepEqual(result.mutationRequests, []);
    assert.equal(result.getNode('notice').textContent, OCR_UNAVAILABLE_MESSAGE);
    assert.equal(result.getNode('notice').classList.contains('error'), true);
    assert.equal(result.getNode('new-ocr').value, mode, 'Do not silently change the requested OCR mode.');
    assert.equal(result.getNode('process').disabled, false);
  });
}

for (const [name, capabilities] of [['missing', undefined], ['null', null], ['missing availability', {ocr: {}}],
    ['string availability', {ocr: {available: 'true'}}], ['numeric availability', {ocr: {available: 1}}]]) {
  test('OCR capability fails closed for ' + name + ' dashboard data', async () => {
    const result = await boot({stored: VALID, capabilities});
    assert.equal(ocrOptions(result).skip.disabled, true);
    assert.equal(ocrOptions(result).textless.disabled, true);
    assert.equal(ocrOptions(result).redo.disabled, true);
    await selectAuthoredPDF(result);
    result.getNode('new-ocr').value = 'skip';
    const requests = [...result.requests];
    await result.dispatch('process', 'click');
    assert.deepEqual(result.requests, requests);
    assert.equal(result.getNode('notice').classList.contains('error'), true);
    assert.equal(result.getNode('new-ocr').value, 'skip');
  });
}

test('OCR polling: loss of capability preserves an explicit request and refuses it before upload', async () => {
  const result = await boot({stored: VALID, capabilities: ocrCapability(true)});
  await selectAuthoredPDF(result);
  result.getNode('new-ocr').value = 'redo';
  result.remainingReads.push({url: '/api/dashboard', response: {documents: [], jobs: [], capabilities: ocrCapability(false)}});
  await result.dispatch('refresh', 'click');
  assert.equal(ocrOptions(result).redo.disabled, true);
  assert.equal(result.getNode('new-ocr').value, 'redo');
  const requests = [...result.requests];
  await result.dispatch('process', 'click');
  assert.deepEqual(result.requests, requests);
  assert.equal(result.getNode('notice').textContent, OCR_UNAVAILABLE_MESSAGE);
});

test('OCR healthy refresh changes availability only and preserves all selected processing settings', async () => {
  const result = await boot({stored: VALID, capabilities: ocrCapability(true)});
  result.getNode('new-ocr').value = 'skip';
  result.getNode('new-title').value = 'Authored unsaved title';
  result.getNode('new-language').value = 'fr-CA';
  result.getNode('new-regroup').checked = true;
  result.getNode('new-mapping').checked = true;
  await result.dispatch('refresh', 'click');
  assert.equal(result.getNode('new-ocr').value, 'skip');
  assert.equal(result.getNode('new-title').value, 'Authored unsaved title');
  assert.equal(result.getNode('new-language').value, 'fr-CA');
  assert.equal(result.getNode('new-regroup').checked, true);
  assert.equal(result.getNode('new-mapping').checked, true);
});

test('OCR shutdown race: a late availability response cannot enable routes or replace the stopped notice', async () => {
  const delayed = deferredResponse();
  const result = await boot({stored: VALID, capabilities: ocrCapability(false), expectedMutations: [stopExpectation()]});
  const guidance = result.getNode('ocr-availability').textContent;
  result.remainingReads.push({url: '/api/dashboard', response: delayed.promise});
  const refresh = result.dispatch('refresh', 'click');
  await settle();
  await result.dispatch('stop', 'click');
  delayed.resolve({documents: [], jobs: [], capabilities: ocrCapability(true)});
  await refresh;
  assertStoppedNotice(result);
  assert.equal(result.getNode('ocr-availability').textContent, guidance);
  assert.equal(ocrOptions(result).skip.disabled, true);
  assert.equal(ocrOptions(result).textless.disabled, true);
  assert.equal(ocrOptions(result).redo.disabled, true);
  assert.equal(result.getNode('new-ocr').value, 'off');
  expectOnlyMutations(result, [{url: '/api/stop', payload: {}}]);
});

test('OCR startup race: a delayed initial dashboard leaves non-off choices unavailable until confirmed', async () => {
  const delayed = deferredResponse();
  const result = await boot({stored: VALID, expectedReads: [{url: '/api/dashboard', response: delayed.promise}]});
  assert.equal(ocrOptions(result).skip.disabled, true);
  assert.equal(ocrOptions(result).textless.disabled, true);
  assert.equal(ocrOptions(result).redo.disabled, true);
  assert.equal(result.getNode('new-ocr').value, 'off');
  delayed.resolve({documents: [], jobs: [], capabilities: ocrCapability(true)});
  await settle();
  assert.equal(ocrOptions(result).skip.disabled, false);
  assert.equal(ocrOptions(result).textless.disabled, false);
  assert.equal(ocrOptions(result).redo.disabled, false);
  assert.equal(result.getNode('new-ocr').value, 'off');
});

test('saved Retry sends only its revision and never adopts unsaved OCR choices from the dashboard', async () => {
  const saved = savedReviewFixture();
  Object.assign(saved, {status: 'failed', historical_status: 'failed', output: null, page_count: 0,
    decisions: [], manual_items: [], groups: []});
  const before = JSON.stringify(saved), url = '/api/workspaces/' + saved.workspace_id + '/retry';
  const payload = {revision: saved.revision};
  const result = await bootSavedReview(saved, {capabilities: ocrCapability(true), captureTimers: true,
    expectedMutations: [{url, payload, response: {job_id: 'authored-saved-settings-retry'}}]});
  result.getNode('new-ocr').value = 'textless';
  await result.dispatch('new-ocr', 'change');
  result.getNode('new-ocr-profile').value = 'angles';
  await openSavedReview(result);
  await result.dispatch('retry', 'click');
  assert.deepEqual(result.mutationRequests, [{url, payload}]);
  assert.equal(result.getNode('new-ocr').value, 'textless');
  assert.equal(result.getNode('new-ocr-profile').value, 'angles');
  assert.equal(JSON.stringify(saved), before);
  assert.deepEqual(result.remainingMutations, []);
  assert.match(result.getNode('notice').textContent, /previous review is preserved/);
});


// OCR correction contracts: named inventories and mutations, no browser/PDF/provider.
const OCR_INVENTORY = 'b'.repeat(64);
const OCR_CONTEXT = 'c'.repeat(64);
const OCR_LITERAL = '<img src=x onerror="no-execution"> authored OCR & text';
function ocrEditorFixture() {
  const saved = repairControlsFixture();
  saved.ocr_editor = {available: true, changed_count: 0, accepted_count: 0, requires_reprocessing: false, limits: []};
  return saved;
}
function ocrItem(id = 'word-one', page = 1, original = 'recoginzed') {
  return {id, page, original_text: original, value: original, status: 'pending',
    eligible: true, limitations: [], context_sha256: OCR_CONTEXT, approved_by: null};
}
function ocrInventory(saved, items = [ocrItem()], revision = saved.revision, page = 1) {
  return {revision, page, source: saved.source, document: saved.output, inventory_sha256: OCR_INVENTORY,
    items, limitations: [], available: true};
}
function ocrRead(saved, response, page = 1, extra = {}) {
  return {url: '/api/workspaces/' + saved.workspace_id + '/ocr?page=' + page, response, ...extra};
}
function ocrCards(result) { return result.getNode('ocr-items').children.filter(node => node.dataset.ocrId); }
function ocrCard(result, id = 'word-one') {
  const cards = ocrCards(result).filter(node => node.dataset.ocrId === id);
  assert.equal(cards.length, 1, 'One current OCR correction card belongs to the authored inventory id.');
  return cards[0];
}
function ocrInput(result, id = 'word-one') { return descendants(ocrCard(result, id)).find(node => node.tagName === 'TEXTAREA'); }
async function showOCR(result, checked = true) {
  result.getNode('show-ocr').checked = checked;
  await result.dispatch('show-ocr', 'change');
}
function ocrEditedView(saved, revision = 8, accepted = 0) {
  const response = structuredClone(saved); response.revision = revision;
  response.ocr_editor.changed_count = 1; response.ocr_editor.accepted_count = accepted;
  response.ocr_editor.requires_reprocessing = true;
  return response;
}
function ocrPayload(saved, value) {
  return {revision: saved.revision, id: 'word-one', value, inventory_sha256: OCR_INVENTORY, context_sha256: OCR_CONTEXT};
}
function assertOnlyOCRRequests(result, mutations = []) {
  assert.deepEqual(result.mutationRequests, mutations);
  assert.deepEqual(result.remainingMutations, []);
  assert.deepEqual(result.remainingReads, []);
  assert.deepEqual(result.unexpectedRequests, []);
  assert(!result.requests.some(row => /\/(models|assist|auto-fix|accept-draft|group)(?:\?|$)|\/apply$/.test(row.url)),
    'OCR correction controls do not invoke AI, legacy Apply, group approval or automatic choices.');
}

test('OCR editor HTML provides native labelled correction controls and an explicit new-source recheck action', () => {
  const html = fs.readFileSync(path.resolve(path.dirname(appPath), 'index.html'), 'utf8');
  assert.match(html, /<input id="show-ocr" type="checkbox" aria-describedby="ocr-editor-note ocr-editor-summary">/);
  assert.match(html, /<h3 id="ocr-editor-title">OCR text corrections<\/h3>/);
  assert.match(html, /Create corrected copy and recheck/);
  assert.match(html, /Earlier PDFs, saved edits and approvals stay in their existing review/);
  assert.match(html, /Corrections are not accessibility approval/);
  assert.match(html, /id="extended-ocr" type="checkbox" aria-describedby="ocr-extended-help"/);
  assert.match(html, /Extended editing checks additional characters against the bundled font/);
  assert.match(html, /An omitted word needs its own result-page rectangle and an explicit position before or after a nearby recognized word/);
  assert.match(html, /<pre id="page-context"><\/pre>/, 'The existing context transcript stays read-only.');
});

test('OCR editor legacy view remains read-only with no invented inventory or mutations and preserves saved notes', async () => {
  const saved = savedReviewFixture(), before = JSON.stringify(saved);
  const result = await bootSavedReview(saved); await openSavedReview(result);
  assert.equal(result.getNode('show-ocr').disabled, true);
  assert.equal(result.getNode('ocr-apply').disabled, true);
  assert.match(result.getNode('ocr-editor-summary').textContent, /no proven editable OCR text/);
  assert.deepEqual(ocrCards(result), []);
  assert(!result.requests.some(row => row.url.includes('/ocr')));
  assertSavedNotes(result, saved.manual_items.slice(0, 2));
  assertSavedSnapshotUnchanged(result, saved, before);
});

test('OCR editor loads only expanded current pages and collapse causes no save or acceptance', async () => {
  const saved = ocrEditorFixture(), before = JSON.stringify(saved);
  const result = await bootSavedReview(saved, {expectedReads: [
    ocrRead(saved, ocrInventory(saved)),
    ocrRead(saved, ocrInventory(saved, [ocrItem('word-two', 2, 'second page')], 7, 2), 2),
  ]});
  await openSavedReview(result);
  assert.deepEqual(ocrCards(result), []);
  assert(!result.requests.some(row => row.url.includes('/ocr')));
  await showOCR(result);
  assert.equal(ocrInput(result).value, 'recoginzed');
  assert.match(result.getNode('ocr-editor-summary').textContent, /Unchanged recognized text does not need acceptance/);
  await result.dispatch('next-page', 'click');
  assert.deepEqual(ocrCards(result).map(card => card.dataset.ocrId), ['word-two']);
  await showOCR(result, false);
  assert.deepEqual(ocrCards(result), []);
  assertSavedSnapshotUnchanged(result, saved, before);
  assertOnlyOCRRequests(result);
});

test('OCR editor renders unsafe context literally and disables unsupported word controls', async () => {
  const saved = ocrEditorFixture(), item = ocrItem('unsafe-word', 1, OCR_LITERAL);
  item.eligible = false; item.limitations = ['Shared or visible text: ' + OCR_LITERAL];
  const result = await bootSavedReview(saved, {expectedReads: [ocrRead(saved, ocrInventory(saved, [item]))]});
  await openSavedReview(result); await showOCR(result);
  const card = ocrCard(result, 'unsafe-word'), field = ocrInput(result, 'unsafe-word');
  assert.equal(field.value, OCR_LITERAL); assert.equal(field.disabled, true);
  const original = descendants(card).find(node => node.tagName === 'PRE');
  assert.equal(original.textContent, OCR_LITERAL); assert.deepEqual(original.children, []);
  for (const b of descendants(card).filter(node => node.tagName === 'BUTTON')) assert.equal(b.disabled, true);
  assertOnlyOCRRequests(result);
});

test('OCR editor Save binds exact value, inventory, occurrence and revision; refreshed button retains focus', async () => {
  const saved = ocrEditorFixture(), before = JSON.stringify(saved), value = 'recognized';
  const response = ocrEditedView(saved), item = {...ocrItem(), value};
  const url = '/api/workspaces/' + saved.workspace_id + '/ocr-edit', payload = ocrPayload(saved, value);
  const result = await bootSavedReview(saved, {expectedReads: [ocrRead(saved, ocrInventory(saved)), ocrRead(saved, ocrInventory(response, [item]))],
    expectedMutations: [{url, payload, response}]});
  await openSavedReview(result); await showOCR(result);
  ocrInput(result).value = value;
  const save = buttonNamed(ocrCard(result), 'Save correction draft'); save.focus();
  await result.dispatch(save, 'click'); await settle();
  assert.equal(ocrInput(result).value, value);
  assertFreshFocus(result, buttonNamed(ocrCard(result), 'Save correction draft'), save);
  assert.equal(result.getNode('ocr-apply').disabled, true, 'A draft alone cannot create a corrected source.');
  assertSavedNotes(result, saved.manual_items.slice(0, 2));
  assertSavedSnapshotUnchanged(result, saved, before);
  assertOnlyOCRRequests(result, [{url, payload}]);
});

test('OCR editor explicit acceptance saves the exact unsaved correction before approving its returned revision', async () => {
  const saved = ocrEditorFixture(), value = 'recognized', edited = ocrEditedView(saved), approved = ocrEditedView(saved, 9, 1);
  const editUrl = '/api/workspaces/' + saved.workspace_id + '/ocr-edit', approveUrl = '/api/workspaces/' + saved.workspace_id + '/ocr-approve';
  const editPayload = ocrPayload(saved, value);
  const approvePayload = {revision: 8, id: 'word-one', reviewer: 'Authored OCR reviewer', inventory_sha256: OCR_INVENTORY, context_sha256: OCR_CONTEXT};
  const finalItem = {...ocrItem(), value, status: 'approved', approved_by: approvePayload.reviewer};
  const result = await bootSavedReview(saved, {expectedReads: [ocrRead(saved, ocrInventory(saved)), ocrRead(saved, ocrInventory(approved, [finalItem]))],
    expectedMutations: [{url: editUrl, payload: editPayload, response: edited}, {url: approveUrl, payload: approvePayload, response: approved}]});
  await openSavedReview(result); await showOCR(result); result.getNode('reviewer').value = approvePayload.reviewer;
  ocrInput(result).value = value;
  const accept = buttonNamed(ocrCard(result), 'Accept correction'); accept.focus();
  await result.dispatch(accept, 'click'); await settle();
  assertFreshFocus(result, buttonNamed(ocrCard(result), 'Accept correction'), accept);
  assert.equal(result.getNode('ocr-apply').disabled, false);
  assert.match(descendants(ocrCard(result)).map(node => node.textContent).join(' '), /not applied to the PDF yet/);
  assertOnlyOCRRequests(result, [{url: editUrl, payload: editPayload}, {url: approveUrl, payload: approvePayload}]);
});

test('OCR editor missing reviewer refuses before saving or approving an unsaved correction', async () => {
  const saved = ocrEditorFixture();
  const result = await bootSavedReview(saved, {expectedReads: [ocrRead(saved, ocrInventory(saved))]});
  await openSavedReview(result); await showOCR(result); ocrInput(result).value = 'recognized';
  await result.dispatch(buttonNamed(ocrCard(result), 'Accept correction'), 'click');
  assert.match(result.getNode('notice').textContent, /Enter your name/);
  assert.equal(ocrInput(result).value, 'recognized');
  assertOnlyOCRRequests(result);
});

for (const message of ['The replacement contains a glyph outside the proven native font.', 'The saved OCR inventory or review revision is stale.']) {
  test('OCR editor backend refusal preserves the local correction and cannot imply acceptance: ' + message, async () => {
    const saved = ocrEditorFixture(), value = 'authored unsupported value';
    const url = '/api/workspaces/' + saved.workspace_id + '/ocr-edit', payload = ocrPayload(saved, value);
    const result = await bootSavedReview(saved, {expectedReads: [ocrRead(saved, ocrInventory(saved))],
      expectedMutations: [{url, payload, ok: false, response: {error: message}}]});
    await openSavedReview(result); await showOCR(result); ocrInput(result).value = value;
    await result.dispatch(buttonNamed(ocrCard(result), 'Save correction draft'), 'click');
    assert.equal(ocrInput(result).value, value);
    assert.equal(result.getNode('notice').textContent, message);
    assert.equal(result.getNode('ocr-apply').disabled, true);
    assertOnlyOCRRequests(result, [{url, payload}]);
  });
}

test('OCR editor stale workspace disables expansion and corrected-copy action without an OCR read', async () => {
  const saved = ocrEditorFixture(); saved.stale = true; saved.ocr_editor.accepted_count = 1;
  const result = await bootSavedReview(saved); await openSavedReview(result);
  assert.equal(result.getNode('show-ocr').disabled, true); assert.equal(result.getNode('ocr-apply').disabled, true);
  await result.dispatch('ocr-apply', 'click'); assert(!result.requests.some(row => row.url.includes('/ocr')));
  assertOnlyOCRRequests(result);
});

test('OCR editor active jobs disable fields and page navigation cannot restore old-page mutable controls', async () => {
  const saved = ocrEditorFixture(), url = '/api/workspaces/' + saved.workspace_id + '/retry', payload = {revision: 7};
  saved.historical_status = 'failed';
  const result = await bootSavedReview(saved, {captureTimers: true, expectedReads: [ocrRead(saved, ocrInventory(saved))],
    expectedMutations: [{url, payload, response: {job_id: 'authored-ocr-busy'}}]});
  await openSavedReview(result); await showOCR(result); await result.dispatch('retry', 'click');
  assert.equal(ocrInput(result).disabled, true); assert.equal(result.getNode('show-ocr').disabled, true);
  assert.equal(result.getNode('ocr-apply').disabled, true);
  await result.dispatch('next-page', 'click');
  assert.deepEqual(ocrCards(result), []);
  assert.equal(result.requests.filter(row => row.url.includes('/ocr?')).length, 1);
  assert.deepEqual(result.mutationRequests, [{url, payload}]);
  assert.deepEqual(result.unexpectedRequests, []);
});

test('OCR editor an older inventory response cannot replace a newer page inventory', async () => {
  const saved = ocrEditorFixture(), delayed = deferredResponse();
  const result = await bootSavedReview(saved, {expectedReads: [
    ocrRead(saved, delayed.promise), ocrRead(saved, ocrInventory(saved, [ocrItem('word-two', 2, 'second page')], 7, 2), 2),
  ]});
  await openSavedReview(result);
  const pending = showOCR(result); await settle();
  await result.dispatch('next-page', 'click');
  assert.deepEqual(ocrCards(result).map(card => card.dataset.ocrId), ['word-two']);
  delayed.resolve(ocrInventory(saved)); await pending;
  assert.deepEqual(ocrCards(result).map(card => card.dataset.ocrId), ['word-two']);
  assertOnlyOCRRequests(result);
});

test('OCR editor an inventory response cannot paint after switching to another workspace', async () => {
  const {first, second} = navigationFixtures(); first.ocr_editor = ocrEditorFixture().ocr_editor;
  const delayed = deferredResponse();
  const result = await bootNavigation(first, second, {expectedReads: [ocrRead(first, delayed.promise)]});
  await openNamedWorkspace(result, 'workspace-A.pdf'); const pending = showOCR(result); await settle();
  await openNamedWorkspace(result, 'workspace-B.pdf');
  delayed.resolve(ocrInventory(first)); await pending;
  assertVisibleWorkspace(result, 'workspace-B.pdf', 'de');
  assert.deepEqual(ocrCards(result), []); assert.equal(result.getNode('show-ocr').checked, false);
  assertOnlyOCRRequests(result);
});

test('OCR editor delayed Save remains in its originating review and does not overwrite another workspace', async () => {
  const {first, second} = navigationFixtures(); first.ocr_editor = ocrEditorFixture().ocr_editor;
  const delayed = deferredResponse(), value = 'recognized';
  const url = '/api/workspaces/' + first.workspace_id + '/ocr-edit', payload = ocrPayload(first, value);
  const result = await bootNavigation(first, second, {expectedReads: [ocrRead(first, ocrInventory(first))],
    expectedMutations: [{url, payload, response: delayed.promise}]});
  await openNamedWorkspace(result, 'workspace-A.pdf'); await showOCR(result); ocrInput(result).value = value;
  const pending = result.dispatch(buttonNamed(ocrCard(result), 'Save correction draft'), 'click'); await settle();
  await openNamedWorkspace(result, 'workspace-B.pdf');
  delayed.resolve(ocrEditedView(first)); await pending;
  assertVisibleWorkspace(result, 'workspace-B.pdf', 'de'); assert.deepEqual(ocrCards(result), []);
  assertOnlyOCRRequests(result, [{url, payload}]);
});

test('OCR editor pending acceptance aborts after A to B to A instead of approving a coinciding revision', async () => {
  const {first, second} = navigationFixtures(); first.ocr_editor = ocrEditorFixture().ocr_editor;
  const delayed = deferredResponse(), value = 'recognized';
  const url = '/api/workspaces/' + first.workspace_id + '/ocr-edit', payload = ocrPayload(first, value);
  const result = await bootNavigation(first, second, {expectedReads: [ocrRead(first, ocrInventory(first))],
    expectedMutations: [{url, payload, response: delayed.promise}]});
  await openNamedWorkspace(result, 'workspace-A.pdf'); await showOCR(result);
  result.getNode('reviewer').value = 'Authored OCR reviewer'; ocrInput(result).value = value;
  const pending = result.dispatch(buttonNamed(ocrCard(result), 'Accept correction'), 'click'); await settle();
  await openNamedWorkspace(result, 'workspace-B.pdf'); await openNamedWorkspace(result, 'workspace-A.pdf');
  delayed.resolve(ocrEditedView(first)); await pending;
  assert.equal(result.getNode('show-ocr').checked, false); assert.deepEqual(ocrCards(result), []);
  assertOnlyOCRRequests(result, [{url, payload}]);
});

test('OCR editor delayed Save preserves a newer other-word draft, caret and focus after refreshing inventory', async () => {
  const saved = ocrEditorFixture(), delayed = deferredResponse(), value = 'recognized', response = ocrEditedView(saved);
  const second = ocrItem('word-two', 1, 'second');
  const url = '/api/workspaces/' + saved.workspace_id + '/ocr-edit', payload = ocrPayload(saved, value);
  const result = await bootSavedReview(saved, {expectedReads: [
    ocrRead(saved, ocrInventory(saved, [ocrItem(), second])),
    ocrRead(saved, ocrInventory(response, [{...ocrItem(), value}, second])),
  ], expectedMutations: [{url, payload, response: delayed.promise}]});
  await openSavedReview(result); await showOCR(result); ocrInput(result).value = value;
  const pending = result.dispatch(buttonNamed(ocrCard(result), 'Save correction draft'), 'click'); await settle();
  const newer = ocrInput(result, 'word-two'); newer.value = 'newer local correction'; newer.focus(); newer.setSelectionRange(2, 9, 'backward');
  delayed.resolve(response); await pending; await settle();
  const current = ocrInput(result, 'word-two');
  assertFreshFocus(result, current, newer); assert.equal(current.value, 'newer local correction');
  assert.equal(current.selectionStart, 2); assert.equal(current.selectionEnd, 9); assert.equal(current.selectionDirection, 'backward');
  assertOnlyOCRRequests(result, [{url, payload}]);
});

test('OCR editor a delayed ordinary Save preserves newer OCR draft text and caret across its inventory refresh', async () => {
  const saved = ocrEditorFixture(), delayed = deferredResponse(), value = 'Authored updated title', response = editedView(saved, 'title-control', value);
  const url = '/api/workspaces/' + saved.workspace_id + '/edit', payload = {revision: 7, id: 'title-control', value};
  const result = await bootSavedReview(saved, {expectedReads: [ocrRead(saved, ocrInventory(saved)), ocrRead(saved, ocrInventory(response))],
    expectedMutations: [{url, payload, response: delayed.promise}]});
  await openSavedReview(result); await showOCR(result);
  descendants(cardFor(result, 'title-control')).find(node => node.tagName === 'TEXTAREA').value = value;
  const pending = result.dispatch(buttonNamed(cardFor(result, 'title-control'), 'Save edit'), 'click'); await settle();
  const newer = ocrInput(result); newer.value = 'newer OCR draft'; newer.focus(); newer.setSelectionRange(1, 7);
  delayed.resolve(response); await pending; await settle();
  const current = ocrInput(result); assertFreshFocus(result, current, newer);
  assert.equal(current.value, 'newer OCR draft'); assert.equal(current.selectionStart, 1); assert.equal(current.selectionEnd, 7);
  assertOnlyOCRRequests(result, [{url, payload}]);
});

test('OCR editor creating a corrected source is explicit, revision bound, and separate from legacy Apply', async () => {
  const saved = ocrEditorFixture(); saved.ocr_editor.changed_count = saved.ocr_editor.accepted_count = 1;
  const url = '/api/workspaces/' + saved.workspace_id + '/ocr-apply', payload = {revision: 7};
  const result = await bootSavedReview(saved, {captureTimers: true, expectedMutations: [{url, payload, response: {job_id: 'authored-corrected-source'}}]});
  await openSavedReview(result); assert.equal(result.getNode('ocr-apply').disabled, false);
  await result.dispatch('ocr-apply', 'click');
  assert.match(result.getNode('notice').textContent, /separate corrected source copy/);
  assert.equal(result.getNode('ocr-apply').disabled, true);
  assert.equal(result.getNode('apply').disabled, true);
  assert.equal(result.scheduledTimers.length, 1);
  assertOnlyOCRRequests(result, [{url, payload}]);
});

test('OCR editor a saved draft without acceptance cannot create a corrected source', async () => {
  const saved = ocrEditorFixture(); saved.ocr_editor.changed_count = 1;
  const result = await bootSavedReview(saved); await openSavedReview(result);
  assert.equal(result.getNode('ocr-apply').disabled, true); await result.dispatch('ocr-apply', 'click');
  assertOnlyOCRRequests(result);
});

test('OCR editor source lineage clearly labels the new source while retaining fresh-review language', async () => {
  const saved = ocrEditorFixture(); saved.source_lineage = {kind: 'human-ocr-corrected-copy'};
  const result = await bootSavedReview(saved); await openSavedReview(result);
  assert.equal(result.getNode('original-caption').textContent, 'Corrected source copy');
  assert.equal(result.getNode('source-lineage').hidden, false);
  assert.match(result.getNode('source-lineage-text').textContent, /earlier original, result and saved review remain unchanged/);
  assert.match(result.getNode('source-lineage-text').textContent, /earlier approvals do not carry over/);
  assertOnlyOCRRequests(result);
});

test('OCR editor a late inventory response cannot paint after acknowledged Stop', async () => {
  const saved = ocrEditorFixture(), delayed = deferredResponse();
  const result = await bootSavedReview(saved, {expectedReads: [ocrRead(saved, delayed.promise)], expectedMutations: [stopExpectation()]});
  await openSavedReview(result); const pending = showOCR(result); await settle();
  await result.dispatch('stop', 'click'); assertStoppedNotice(result);
  delayed.resolve(ocrInventory(saved)); await pending;
  assertStoppedNotice(result); assert.deepEqual(ocrCards(result), []);
  assertOnlyOCRRequests(result, [{url: '/api/stop', payload: {}}]);
});


test('OCR editor mixed OCR and document drafts disable both application routes until separated', async () => {
  const saved = ocrEditorFixture();
  saved.ocr_editor.changed_count = saved.ocr_editor.accepted_count = 1;
  saved.decisions.find(item => item.id === 'title-control').status = 'approved';
  saved.unapplied_decisions = ['title-control', 'word-one'];
  const result = await bootSavedReview(saved); await openSavedReview(result);
  assert.equal(result.getNode('apply').disabled, true);
  assert.equal(result.getNode('ocr-apply').disabled, true);
  await result.dispatch('apply', 'click'); await result.dispatch('ocr-apply', 'click');
  assertOnlyOCRRequests(result);
});

test('OCR editor previous-review navigation reopens retained notes and problem statuses without copying approval', async () => {
  const {first, second} = navigationFixtures();
  second.ocr_editor = ocrEditorFixture().ocr_editor;
  second.source_lineage = {kind: 'human-ocr-corrected-copy'};
  second.previous_review = {workspace_id: first.workspace_id, revision: 7, notes_count: 3, blocked_count: 2,
    notice: 'Previous notes and reported problems remain in the earlier review; this corrected copy requires fresh review.', human_approvals_copied: 0};
  const beforeFirst = JSON.stringify(first), beforeSecond = JSON.stringify(second);
  const result = await bootNavigation(first, second);
  await openNamedWorkspace(result, 'workspace-B.pdf');
  assert.equal(result.getNode('previous-review').hidden, false);
  assert.match(result.getNode('source-lineage-text').textContent, /Previous notes and reported problems remain/);
  await result.dispatch('previous-review', 'click');
  assertVisibleWorkspace(result, 'workspace-A.pdf', 'en-US');
  assertSavedNotes(result, first.manual_items.slice(0, 2));
  assert.equal(result.getNode('original-caption').textContent, 'Original');
  assert.equal(JSON.stringify(first), beforeFirst); assert.equal(JSON.stringify(second), beforeSecond);
  assertOnlyOCRRequests(result);
});


for (const mismatch of ['review revision', 'requested page']) {
  test('OCR editor an unexpected inventory ' + mismatch + ' fails closed until the document is reopened', async () => {
    const saved = ocrEditorFixture(), inventory = ocrInventory(saved);
    saved.ocr_editor.accepted_count = 1;
    if (mismatch === 'review revision') inventory.revision = 8;
    else inventory.page = 2;
    const result = await bootSavedReview(saved, {expectedReads: [ocrRead(saved, inventory)]});
    await openSavedReview(result); await showOCR(result);
    assert.deepEqual(ocrCards(result), []);
    assert.equal(result.getNode('show-ocr').disabled, true); assert.equal(result.getNode('ocr-apply').disabled, true);
    assert.match(result.getNode('ocr-editor-summary').textContent, /Reopen this document/);
    assertOnlyOCRRequests(result);
  });
}

test('OCR editor a late inventory during an active job cannot restore mutable fields or focus', async () => {
  const saved = ocrEditorFixture(), delayed = deferredResponse();
  saved.historical_status = 'failed';
  const url = '/api/workspaces/' + saved.workspace_id + '/retry', payload = {revision: 7};
  const result = await bootSavedReview(saved, {captureTimers: true, expectedReads: [ocrRead(saved, delayed.promise)],
    expectedMutations: [{url, payload, response: {job_id: 'authored-late-inventory'}}]});
  await openSavedReview(result); const pending = showOCR(result); await settle();
  await result.dispatch('retry', 'click'); delayed.resolve(ocrInventory(saved)); await pending;
  assert.equal(ocrInput(result).disabled, true);
  for (const b of descendants(ocrCard(result)).filter(node => node.tagName === 'BUTTON')) assert.equal(b.disabled, true);
  assert.equal(result.getNode('ocr-apply').disabled, true);
  assert.deepEqual(result.mutationRequests, [{url, payload}]); assert.deepEqual(result.unexpectedRequests, []);
});

test('OCR editor delayed correction Save preserves a newer problem note and caret without submitting the note', async () => {
  const saved = ocrEditorFixture(), delayed = deferredResponse(), value = 'recognized', response = ocrEditedView(saved);
  const url = '/api/workspaces/' + saved.workspace_id + '/ocr-edit', payload = ocrPayload(saved, value);
  const result = await bootSavedReview(saved, {expectedReads: [ocrRead(saved, ocrInventory(saved)), ocrRead(saved, ocrInventory(response, [{...ocrItem(), value}]))],
    expectedMutations: [{url, payload, response: delayed.promise}]});
  await openSavedReview(result); await showOCR(result); ocrInput(result).value = value;
  const pending = result.dispatch(buttonNamed(ocrCard(result), 'Save correction draft'), 'click'); await settle();
  await result.dispatch('tab-checks', 'click');
  const newer = notesInput(manualCards(result)[0]); newer.value = 'Newer unsaved problem note'; newer.focus(); newer.setSelectionRange(3, 12);
  delayed.resolve(response); await pending; await settle();
  const current = notesInput(manualCards(result)[0]); assertFreshFocus(result, current, newer);
  assert.equal(current.value, 'Newer unsaved problem note'); assert.equal(current.selectionStart, 3); assert.equal(current.selectionEnd, 12);
  assert.equal(result.getNode('panel-checks').hidden, false);
  assertOnlyOCRRequests(result, [{url, payload}]);
});

test('OCR editor closing an inventory load does not leave a later available workspace stuck loading', async () => {
  const {first, second} = navigationFixtures();
  first.ocr_editor = ocrEditorFixture().ocr_editor; second.ocr_editor = ocrEditorFixture().ocr_editor;
  const delayed = deferredResponse();
  const result = await bootNavigation(first, second, {expectedReads: [ocrRead(first, delayed.promise)]});
  await openNamedWorkspace(result, 'workspace-A.pdf'); const pending = showOCR(result); await settle();
  await openNamedWorkspace(result, 'workspace-B.pdf');
  assert.match(result.getNode('ocr-editor-summary').textContent, /No saved OCR corrections/);
  assert.equal(result.getNode('show-ocr').disabled, false);
  delayed.resolve(ocrInventory(first)); await pending;
  assert.match(result.getNode('ocr-editor-summary').textContent, /No saved OCR corrections/);
  assertOnlyOCRRequests(result);
});


test('OCR editor repeated recognized text keeps distinct occurrence labels and submits only the selected bound id', async () => {
  const saved = ocrEditorFixture(), response = ocrEditedView(saved);
  const first = ocrItem('repeat-one', 1, 'same'), second = {...ocrItem('repeat-two', 1, 'same'), context_sha256: 'd'.repeat(64)};
  const url = '/api/workspaces/' + saved.workspace_id + '/ocr-edit';
  const payload = {revision: 7, id: second.id, value: 'some', inventory_sha256: OCR_INVENTORY, context_sha256: second.context_sha256};
  const result = await bootSavedReview(saved, {expectedReads: [
    ocrRead(saved, ocrInventory(saved, [first, second])),
    ocrRead(saved, ocrInventory(response, [first, {...second, value: payload.value}])),
  ], expectedMutations: [{url, payload, response}]});
  await openSavedReview(result); await showOCR(result);
  assert.notEqual(ocrInput(result, first.id).attributes['aria-label'], ocrInput(result, second.id).attributes['aria-label']);
  ocrInput(result, second.id).value = payload.value;
  await result.dispatch(buttonNamed(ocrCard(result, second.id), 'Save correction draft'), 'click'); await settle();
  assert.equal(ocrInput(result, first.id).value, 'same');
  assert.equal(ocrInput(result, second.id).value, 'some');
  assertOnlyOCRRequests(result, [{url, payload}]);
});


test('OCR editor stable occurrence numbers and nearby OCR context remain literal and unchanged words are not pending corrections', async () => {
  const saved = ocrEditorFixture(), item = ocrItem();
  item.occurrence = 14; item.context_text = OCR_LITERAL;
  item.context_text_source = 'Neighboring OCR-layer words; meaningful reading order remains unapproved.';
  const result = await bootSavedReview(saved, {expectedReads: [ocrRead(saved, ocrInventory(saved, [item]))]});
  await openSavedReview(result); await showOCR(result);
  const card = ocrCard(result), content = descendants(card);
  assert(content.some(node => node.tagName === 'H3' && node.textContent === 'Recognized text 14 on page 1'));
  assert.match(ocrInput(result).attributes['aria-label'], /^OCR correction 14 on page 1/);
  const context = content.find(node => node.tagName === 'PRE' && node.textContent === OCR_LITERAL);
  assert(context); assert.deepEqual(context.children, []);
  assert(content.some(node => node.textContent === 'No saved correction'));
  assert(content.some(node => node.textContent === item.context_text_source));
  assertOnlyOCRRequests(result);
});


test('OCR editor an accepted correction cannot create a copy while another changed correction remains pending', async () => {
  const saved = ocrEditorFixture();
  saved.ocr_editor.changed_count = 2; saved.ocr_editor.accepted_count = 1;
  const result = await bootSavedReview(saved); await openSavedReview(result);
  assert.equal(result.getNode('ocr-apply').disabled, true);
  assert.match(result.getNode('ocr-editor-summary').textContent, /2 saved corrections; 1 accepted/);
  await result.dispatch('ocr-apply', 'click');
  const html = fs.readFileSync(path.resolve(path.dirname(appPath), 'index.html'), 'utf8');
  assert.match(html, /Accept every saved correction, or restore its original recognized text, before creating a corrected copy/);
  assertOnlyOCRRequests(result);
});

// Extended OCR controls use explicit authored inventories. These tests do not
// qualify a font, PDF placement or semantic reading order; native proofs do that.
const EXPANDED_INVENTORY = 'd'.repeat(64), EXPANDED_CAPABILITY = 'a'.repeat(64);
const INSERT_ID = 'ocr-insert-' + '1'.repeat(32);
function expandedItem(id = 'word-one', page = 1, original = 'recognized') {
  return {...ocrItem(id, page, original), occurrence: id === 'word-one' ? 14 : 29,
    bbox: [0.1, 0.2, 0.2, 0.04], insertion_eligible: true, insertion_reason: '',
    supported_characters: 'recognizedMissingÉαЯ'};
}
function savedInsertion(extra = {}) {
  return {id: INSERT_ID, page: 1, anchor_id: 'word-one', value: 'Missing',
    placement: {rect: [0.35, 0.2, 0.12, 0.04], order: 'after'}, status: 'pending',
    context_sha256: OCR_CONTEXT, approved_by: null, ...extra};
}
function expandedInventory(saved, items = [expandedItem()], insertions = [], page = 1) {
  return {...ocrInventory(saved, items, saved.revision, page), profile: 'expanded-v2',
    requested_profile: 'expanded-v2', expansion_available: true, expansion_reason: '',
    inventory_sha256: EXPANDED_INVENTORY, expansion_sha256: EXPANDED_CAPABILITY,
    insertion_enabled: items.some(item => item.insertion_eligible), insertion_reason: '', insertions,
    page_geometry: {width: 612, height: 792, rotation: 0},
    font_policy: {id: 'authored-font-policy', sha256: 'e'.repeat(64), characters: 'ÉαЯ'}};
}
function expandedRead(saved, response, page = 1, explicit = true) {
  return {url: '/api/workspaces/' + saved.workspace_id + '/ocr?page=' + page + (explicit ? '&profile=expanded-v2' : ''), response};
}
function insertionCard(result, id = 'new-ocr-insertion') { return ocrCard(result, id); }
function insertionControls(result, id = 'new-ocr-insertion') {
  return descendants(insertionCard(result, id)).filter(node => ['TEXTAREA', 'SELECT', 'INPUT'].includes(node.tagName));
}
async function fillInsertion(result, {value = 'Missing', anchor = 'word-one', order = 'after', rect = ['35', '20', '12', '4']} = {}, id = 'new-ocr-insertion') {
  const fields = insertionControls(result, id), values = [value, anchor, order, ...rect];
  assert.equal(fields.length, 7);
  for (const [index, field] of fields.entries()) { field.value = values[index]; await result.dispatch(field, field.tagName === 'SELECT' ? 'change' : 'input'); }
  return fields;
}
function insertionPayload(saved, extra = {}) {
  return {revision: saved.revision, inventory_sha256: EXPANDED_INVENTORY, context_sha256: OCR_CONTEXT,
    expansion_sha256: EXPANDED_CAPABILITY, anchor_id: 'word-one', value: 'Missing',
    placement: {rect: [0.35, 0.2, 0.12, 0.04], order: 'after'}, ...extra};
}
async function openExpanded(result) { await openSavedReview(result); await showOCR(result); }

test('Extended OCR is an explicit choice and its request carries the expanded profile without changing legacy reads', async () => {
  const saved = ocrEditorFixture();
  const result = await bootSavedReview(saved, {expectedReads: [ocrRead(saved, ocrInventory(saved)), expandedRead(saved, expandedInventory(saved))]});
  await openSavedReview(result); assert.equal(result.getNode('extended-ocr').disabled, true);
  await showOCR(result); assert.equal(result.getNode('extended-ocr').checked, false);
  assert.equal(result.getNode('extended-ocr').disabled, false);
  assert(!result.requests.some(row => row.url.includes('profile=')));
  result.getNode('extended-ocr').checked = true; await result.dispatch('extended-ocr', 'change');
  assert.equal(result.getNode('extended-ocr').checked, true);
  assert.match(result.getNode('ocr-extended-help').textContent, /bundled font/);
  assert(insertionCard(result)); assertOnlyOCRRequests(result);
});

test('Extended OCR keeps earlier saved corrections in their original mode and displays the backend explanation', async () => {
  const saved = ocrEditedView(ocrEditorFixture());
  const inventory = {...ocrInventory(saved), profile: 'legacy', expansion_available: false,
    expansion_reason: 'Apply or restore the earlier saved corrections before choosing extended editing.'};
  const result = await bootSavedReview(saved, {expectedReads: [ocrRead(saved, inventory)]});
  await openExpanded(result);
  assert.equal(result.getNode('extended-ocr').checked, false); assert.equal(result.getNode('extended-ocr').disabled, true);
  assert.equal(result.getNode('ocr-extended-help').textContent, inventory.expansion_reason);
  assert(!ocrCards(result).some(card => card.dataset.ocrInsertion)); assertOnlyOCRRequests(result);
});

test('Extended OCR reopens saved expanded work in its actual mode even when the default request is legacy', async () => {
  const saved = ocrEditedView(ocrEditorFixture());
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved, [expandedItem()], [savedInsertion()]), 1, false)]});
  await openExpanded(result);
  assert.equal(result.getNode('extended-ocr').checked, true); assert(insertionCard(result, INSERT_ID));
  assertOnlyOCRRequests(result);
});

test('Extended OCR insertion uses native named text, anchor, ordering and percentage controls with a decorative result outline', async () => {
  const saved = ocrEditorFixture();
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved), 1, false)]});
  await openExpanded(result); const fields = insertionControls(result);
  assert.deepEqual(fields.map(field => field.tagName), ['TEXTAREA', 'SELECT', 'SELECT', 'INPUT', 'INPUT', 'INPUT', 'INPUT']);
  assert.equal(new Set(fields.map(field => field.getAttribute('aria-label'))).size, 7);
  assert(fields.every(field => field.getAttribute('aria-label').includes('page 1')));
  assert.deepEqual(fields[2].children.map(option => option.value), ['before', 'after']);
  for (const input of fields.slice(3)) { assert.equal(input.type, 'number'); assert.equal(input.min, '0'); assert.equal(input.max, '100'); }
  const html = fs.readFileSync(path.resolve(path.dirname(appPath), 'index.html'), 'utf8');
  assert.match(html, /class="ocr-image-stage"><img id="candidate-page"[^>]*><div id="ocr-placement" class="ocr-placement" aria-hidden="true" hidden/);
  assertOnlyOCRRequests(result);
});

test('Extended OCR saves exact additional characters with both inventory and font-capability bindings', async () => {
  const saved = ocrEditorFixture(), response = ocrEditedView(saved), value = 'ÉαЯ';
  const payload = {revision: 7, id: 'word-one', value, inventory_sha256: EXPANDED_INVENTORY,
    context_sha256: OCR_CONTEXT, expansion_sha256: EXPANDED_CAPABILITY};
  const url = '/api/workspaces/' + saved.workspace_id + '/ocr-edit';
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved), 1, false),
    expandedRead(saved, expandedInventory(response, [{...expandedItem(), value}]))], expectedMutations: [{url, payload, response}]});
  await openExpanded(result); ocrInput(result).value = value;
  await result.dispatch(buttonNamed(ocrCard(result), 'Save correction draft'), 'click');
  assert.equal(ocrInput(result).value, value); assertOnlyOCRRequests(result, [{url, payload}]);
});

test('Extended OCR font refusal preserves entered characters without pretending a corrected PDF exists', async () => {
  const saved = ocrEditorFixture(), value = 'Unsupported😀';
  const payload = {revision: 7, id: 'word-one', value, inventory_sha256: EXPANDED_INVENTORY,
    context_sha256: OCR_CONTEXT, expansion_sha256: EXPANDED_CAPABILITY};
  const url = '/api/workspaces/' + saved.workspace_id + '/ocr-edit';
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved), 1, false)],
    expectedMutations: [{url, payload, ok: false, response: {error: 'The qualified font does not cover this character.'}}]});
  await openExpanded(result); ocrInput(result).value = value;
  await result.dispatch(buttonNamed(ocrCard(result), 'Save correction draft'), 'click');
  assert.equal(ocrInput(result).value, value); assert.equal(ocrInput(result).disabled, false);
  assert.match(result.getNode('notice').textContent, /does not cover/); assert.equal(result.getNode('ocr-apply').disabled, true);
  assertOnlyOCRRequests(result, [{url, payload}]);
});

test('Extended OCR saves a new omitted word and rectangle exactly, then requires a separate acceptance of its server id', async () => {
  const saved = ocrEditorFixture(), response = ocrEditedView(saved); response.ocr_saved_insertion_id = INSERT_ID;
  const payload = insertionPayload(saved), url = '/api/workspaces/' + saved.workspace_id + '/ocr-insert';
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved), 1, false),
    expandedRead(saved, expandedInventory(response, [expandedItem()], [savedInsertion()]))], expectedMutations: [{url, payload, response}]});
  await openExpanded(result); await fillInsertion(result);
  assert.equal(result.mutationRequests.length, 0); const origin = buttonNamed(insertionCard(result), 'Save insertion draft'); origin.focus();
  await result.dispatch(origin, 'click'); await settle();
  assert.equal(insertionControls(result, INSERT_ID)[0].value, 'Missing');
  assertFreshFocus(result, buttonNamed(insertionCard(result, INSERT_ID), 'Save insertion draft'), origin);
  assert.equal(insertionControls(result)[0].value, ''); assert.equal(result.getNode('ocr-apply').disabled, true);
  assert.equal(result.getNode('show-ocr').checked, true); assertOnlyOCRRequests(result, [{url, payload}]);
});

test('Extended OCR acceptance binds a saved insertion and current revision to a named reviewer', async () => {
  const saved = ocrEditedView(ocrEditorFixture()), response = ocrEditedView(saved, 9, 1);
  const item = savedInsertion(), approved = {...item, status: 'approved', approved_by: 'Authored insertion reviewer'};
  const payload = {revision: 8, id: INSERT_ID, reviewer: approved.approved_by, inventory_sha256: EXPANDED_INVENTORY,
    context_sha256: OCR_CONTEXT, expansion_sha256: EXPANDED_CAPABILITY};
  const url = '/api/workspaces/' + saved.workspace_id + '/ocr-approve';
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved, [expandedItem()], [item]), 1, false),
    expandedRead(saved, expandedInventory(response, [expandedItem()], [approved]))], expectedMutations: [{url, payload, response}]});
  await openExpanded(result); result.getNode('reviewer').value = approved.approved_by;
  await result.dispatch(buttonNamed(insertionCard(result, INSERT_ID), 'Accept insertion'), 'click');
  assert.equal(result.getNode('ocr-apply').disabled, false);
  assert(descendants(insertionCard(result, INSERT_ID)).some(node => node.textContent === 'Accepted insertion'));
  assertOnlyOCRRequests(result, [{url, payload}]);
});

test('Extended OCR changed insertion fields must be explicitly saved before acceptance', async () => {
  const saved = ocrEditedView(ocrEditorFixture());
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved, [expandedItem()], [savedInsertion()]), 1, false)]});
  await openExpanded(result); result.getNode('reviewer').value = 'Authored reviewer';
  const fields = await fillInsertion(result, {order: 'before'}, INSERT_ID);
  await result.dispatch(buttonNamed(insertionCard(result, INSERT_ID), 'Accept insertion'), 'click');
  assert.match(result.getNode('notice').textContent, /Save the changed insertion fields/); assert.equal(fields[2].value, 'before');
  assertOnlyOCRRequests(result);
});

test('Extended OCR insertion acceptance requires a reviewer before any mutation', async () => {
  const saved = ocrEditedView(ocrEditorFixture());
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved, [expandedItem()], [savedInsertion()]), 1, false)]});
  await openExpanded(result); await result.dispatch(buttonNamed(insertionCard(result, INSERT_ID), 'Accept insertion'), 'click');
  assert.match(result.getNode('notice').textContent, /Enter your name/); assertOnlyOCRRequests(result);
});

test('Extended OCR editing an accepted insertion saves an identified pending draft with its new placement', async () => {
  const saved = ocrEditedView(ocrEditorFixture(), 8, 1), response = ocrEditedView(saved, 9, 0);
  const prior = savedInsertion({status: 'approved', approved_by: 'Earlier reviewer'}), next = savedInsertion({placement: {rect: [0.4, 0.25, 0.1, 0.05], order: 'before'}});
  const payload = insertionPayload(saved, {id: INSERT_ID, placement: next.placement}), url = '/api/workspaces/' + saved.workspace_id + '/ocr-insert';
  response.ocr_saved_insertion_id = INSERT_ID;
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved, [expandedItem()], [prior]), 1, false),
    expandedRead(saved, expandedInventory(response, [expandedItem()], [next]))], expectedMutations: [{url, payload, response}]});
  await openExpanded(result); await fillInsertion(result, {order: 'before', rect: ['40', '25', '10', '5']}, INSERT_ID);
  await result.dispatch(buttonNamed(insertionCard(result, INSERT_ID), 'Save insertion draft'), 'click');
  assert(descendants(insertionCard(result, INSERT_ID)).some(node => node.textContent === 'Insertion draft'));
  assert.equal(result.getNode('ocr-apply').disabled, true); assertOnlyOCRRequests(result, [{url, payload}]);
});

test('Extended OCR removal is revision and capability bound, restores the anchor, and preserves saved problem notes', async () => {
  const saved = ocrEditedView(ocrEditorFixture()), response = structuredClone(saved); response.revision = 9;
  response.ocr_editor = ocrEditorFixture().ocr_editor;
  const before = JSON.stringify(saved), payload = {revision: 8, id: INSERT_ID, inventory_sha256: EXPANDED_INVENTORY,
    context_sha256: OCR_CONTEXT, expansion_sha256: EXPANDED_CAPABILITY}, url = '/api/workspaces/' + saved.workspace_id + '/ocr-remove';
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved, [expandedItem()], [savedInsertion()]), 1, false),
    expandedRead(saved, expandedInventory(response))], expectedMutations: [{url, payload, response}]});
  await openExpanded(result); const origin = buttonNamed(insertionCard(result, INSERT_ID), 'Remove saved insertion'); origin.focus();
  await result.dispatch(origin, 'click'); await settle();
  assert(!ocrCards(result).some(card => card.dataset.ocrId === INSERT_ID)); assert.equal(ocrInput(result).disabled, false);
  assertFreshFocus(result, insertionControls(result)[0], origin); assert.equal(JSON.stringify(saved), before);
  await result.dispatch('tab-checks', 'click'); assertSavedNotes(result, saved.manual_items.slice(0, 2));
  assertOnlyOCRRequests(result, [{url, payload}]);
});

for (const rect of [['', '20', '12', '4'], ['-1', '20', '12', '4'], ['35', 'Infinity', '12', '4'], ['95', '20', '12', '4'], ['35', '20', '0', '4']]) {
  test('Extended OCR refuses an incomplete or out-of-page insertion rectangle ' + JSON.stringify(rect), async () => {
    const saved = ocrEditorFixture();
    const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved), 1, false)]});
    await openExpanded(result); await fillInsertion(result, {rect});
    await result.dispatch(buttonNamed(insertionCard(result), 'Save insertion draft'), 'click');
    assert.match(result.getNode('notice').textContent, /Enter a rectangle inside the result page/); assertOnlyOCRRequests(result);
  });
}

for (const value of ['two words', 'line\nbreak']) {
  test('Extended OCR keeps omitted-word insertion to one word rather than an unplaced transcript ' + JSON.stringify(value), async () => {
    const saved = ocrEditorFixture();
    const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved), 1, false)]});
    await openExpanded(result); await fillInsertion(result, {value});
    await result.dispatch(buttonNamed(insertionCard(result), 'Save insertion draft'), 'click');
    assert.match(result.getNode('notice').textContent, /one omitted word without spaces or line breaks/); assertOnlyOCRRequests(result);
  });
}

test('Extended OCR excludes occupied and changed anchors and protects the word that already anchors an insertion', async () => {
  const saved = ocrEditedView(ocrEditorFixture()), words = [expandedItem(), {...expandedItem('word-two'), value: 'changed'}, expandedItem('word-three')];
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved, words, [savedInsertion()]), 1, false)]});
  await openExpanded(result); assert.equal(ocrInput(result).disabled, true);
  assert.deepEqual(insertionControls(result)[1].children.map(option => option.value), ['', 'word-three']);
  assert.deepEqual(insertionControls(result, INSERT_ID)[1].children.map(option => option.value), ['', 'word-one', 'word-three']);
  assertOnlyOCRRequests(result);
});

test('Extended OCR shows the authoritative placement refusal and leaves unsupported-page insertion read-only', async () => {
  const saved = ocrEditorFixture(), inventory = expandedInventory(saved, [{...expandedItem(), insertion_eligible: false}]);
  inventory.insertion_reason = 'This page geometry cannot be mapped safely to the preview.'; inventory.insertion_enabled = false;
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, inventory, 1, false)]});
  await openExpanded(result); assert(insertionControls(result).every(field => field.disabled));
  assert(descendants(insertionCard(result)).some(node => node.textContent === inventory.insertion_reason));
  assert.equal(ocrInput(result).disabled, false); assertOnlyOCRRequests(result);
});

test('Extended OCR percentage placement drives only a decorative outline on the current result preview and hides when closed', async () => {
  const saved = ocrEditorFixture();
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved), 1, false)]});
  await openExpanded(result); await fillInsertion(result);
  const outline = result.getNode('ocr-placement'); assert.equal(outline.hidden, false);
  assert.deepEqual(outline.style, {left: '35%', top: '20%', width: '12%', height: '4%'});
  await showOCR(result, false); assert.equal(outline.hidden, true); assertOnlyOCRRequests(result);
});

test('Extended OCR unsaved insertion fields survive a page round trip without a server mutation', async () => {
  const saved = ocrEditorFixture();
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved), 1, false),
    expandedRead(saved, expandedInventory(saved, [expandedItem('page-two', 2)], [], 2), 2), expandedRead(saved, expandedInventory(saved))]});
  await openExpanded(result); await fillInsertion(result, {value: 'ÉαЯ', order: 'before'});
  await result.dispatch('next-page', 'click'); assert.equal(insertionControls(result)[0].value, '');
  await result.dispatch('previous-page', 'click');
  assert.deepEqual(insertionControls(result).map(field => field.value), ['ÉαЯ', 'word-one', 'before', '35', '20', '12', '4']);
  assertOnlyOCRRequests(result);
});

test('Extended OCR unsaved insertion blocks copy creation and mode changes until its fields are cleared', async () => {
  const saved = ocrEditedView(ocrEditorFixture(), 8, 1);
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved), 1, false)]});
  await openExpanded(result); assert.equal(result.getNode('ocr-apply').disabled, false);
  await fillInsertion(result); assert.equal(result.getNode('ocr-apply').disabled, true); assert.equal(result.getNode('extended-ocr').disabled, true);
  await result.dispatch(buttonNamed(insertionCard(result), 'Clear unsaved insertion fields'), 'click');
  assert.equal(insertionControls(result)[0].value, ''); assert.equal(result.getNode('ocr-apply').disabled, false);
  assert.equal(result.getNode('extended-ocr').disabled, false); assertOnlyOCRRequests(result);
});

test('Extended OCR pending insertion Save disables duplicate commands while other-word drafting remains available', async () => {
  const saved = ocrEditorFixture(), response = ocrEditedView(saved), delayed = deferredResponse(); response.ocr_saved_insertion_id = INSERT_ID;
  const words = [expandedItem(), expandedItem('word-two')], payload = insertionPayload(saved), url = '/api/workspaces/' + saved.workspace_id + '/ocr-insert';
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved, words), 1, false),
    expandedRead(saved, expandedInventory(response, words, [savedInsertion()]))], expectedMutations: [{url, payload, response: delayed.promise}]});
  await openExpanded(result); await fillInsertion(result); const origin = buttonNamed(insertionCard(result), 'Save insertion draft');
  const pending = result.dispatch(origin, 'click'); await settle(); assert.equal(origin.disabled, true);
  await result.dispatch(origin, 'click'); assert.equal(result.mutationRequests.length, 1); assert.equal(ocrInput(result, 'word-two').disabled, false);
  delayed.resolve(response); await pending; assertOnlyOCRRequests(result, [{url, payload}]);
});

test('Extended OCR delayed replacement Save preserves a newer insertion draft, position, caret and focus', async () => {
  const saved = ocrEditorFixture(), response = ocrEditedView(saved), delayed = deferredResponse(), words = [expandedItem(), expandedItem('word-two')];
  const value = 'ÉαЯ', payload = {revision: 7, id: 'word-one', value, inventory_sha256: EXPANDED_INVENTORY, context_sha256: OCR_CONTEXT, expansion_sha256: EXPANDED_CAPABILITY};
  const url = '/api/workspaces/' + saved.workspace_id + '/ocr-edit';
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved, words), 1, false),
    expandedRead(saved, expandedInventory(response, [{...words[0], value}, words[1]]))], expectedMutations: [{url, payload, response: delayed.promise}]});
  await openExpanded(result); ocrInput(result).value = value;
  const pending = result.dispatch(buttonNamed(ocrCard(result), 'Save correction draft'), 'click'); await settle();
  const fields = await fillInsertion(result, {value: 'Newer', anchor: 'word-two', order: 'before'}); fields[0].focus(); fields[0].setSelectionRange(1, 4, 'backward');
  delayed.resolve(response); await pending; await settle(); const current = insertionControls(result);
  assertFreshFocus(result, current[0], fields[0]); assert.deepEqual(current.map(field => field.value), ['Newer', 'word-two', 'before', '35', '20', '12', '4']);
  assert.equal(current[0].selectionStart, 1); assert.equal(current[0].selectionEnd, 4); assert.equal(current[0].selectionDirection, 'backward');
  assertOnlyOCRRequests(result, [{url, payload}]);
});

test('Extended OCR delayed insertion Save preserves a newer other-word draft and its caret', async () => {
  const saved = ocrEditorFixture(), response = ocrEditedView(saved), delayed = deferredResponse(), words = [expandedItem(), expandedItem('word-two')];
  response.ocr_saved_insertion_id = INSERT_ID;
  const payload = insertionPayload(saved), url = '/api/workspaces/' + saved.workspace_id + '/ocr-insert';
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved, words), 1, false),
    expandedRead(saved, expandedInventory(response, words, [savedInsertion()]))], expectedMutations: [{url, payload, response: delayed.promise}]});
  await openExpanded(result); await fillInsertion(result); const pending = result.dispatch(buttonNamed(insertionCard(result), 'Save insertion draft'), 'click'); await settle();
  const newer = ocrInput(result, 'word-two'); newer.value = 'newer local word'; newer.focus(); newer.setSelectionRange(2, 7);
  delayed.resolve(response); await pending; await settle(); const current = ocrInput(result, 'word-two');
  assertFreshFocus(result, current, newer); assert.equal(current.value, 'newer local word'); assert.equal(current.selectionStart, 2); assert.equal(current.selectionEnd, 7);
  assertOnlyOCRRequests(result, [{url, payload}]);
});

test('Extended OCR delayed removal preserves a newer unsaved insertion in a different anchor with caret and focus', async () => {
  const saved = ocrEditedView(ocrEditorFixture()), response = ocrEditedView(saved, 9, 0), delayed = deferredResponse();
  response.ocr_editor.changed_count = 0; const words = [expandedItem(), expandedItem('word-two')];
  const payload = {revision: 8, id: INSERT_ID, inventory_sha256: EXPANDED_INVENTORY, context_sha256: OCR_CONTEXT, expansion_sha256: EXPANDED_CAPABILITY};
  const url = '/api/workspaces/' + saved.workspace_id + '/ocr-remove';
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved, words, [savedInsertion()]), 1, false),
    expandedRead(saved, expandedInventory(response, words))], expectedMutations: [{url, payload, response: delayed.promise}]});
  await openExpanded(result); const origin = buttonNamed(insertionCard(result, INSERT_ID), 'Remove saved insertion');
  const pending = result.dispatch(origin, 'click'); await settle(); assert.equal(origin.disabled, true); await result.dispatch(origin, 'click');
  const newer = await fillInsertion(result, {value: 'Another', anchor: 'word-two'}); newer[0].focus(); newer[0].setSelectionRange(1, 5);
  delayed.resolve(response); await pending; await settle(); const current = insertionControls(result);
  assertFreshFocus(result, current[0], newer[0]); assert.equal(current[0].value, 'Another'); assert.equal(current[1].value, 'word-two');
  assert.equal(current[0].selectionStart, 1); assert.equal(current[0].selectionEnd, 5); assertOnlyOCRRequests(result, [{url, payload}]);
});

test('Extended OCR late insertion Save cannot paint a different workspace or copy its old draft there', async () => {
  const {first, second} = navigationFixtures(); first.ocr_editor = ocrEditorFixture().ocr_editor;
  const response = ocrEditedView(first), delayed = deferredResponse(), payload = insertionPayload(first), url = '/api/workspaces/' + first.workspace_id + '/ocr-insert';
  response.ocr_saved_insertion_id = INSERT_ID;
  const result = await bootNavigation(first, second, {expectedReads: [expandedRead(first, expandedInventory(first), 1, false)], expectedMutations: [{url, payload, response: delayed.promise}]});
  await openNamedWorkspace(result, 'workspace-A.pdf'); await showOCR(result); await fillInsertion(result);
  const pending = result.dispatch(buttonNamed(insertionCard(result), 'Save insertion draft'), 'click'); await settle();
  await openNamedWorkspace(result, 'workspace-B.pdf'); delayed.resolve(response); await pending;
  assertVisibleWorkspace(result, 'workspace-B.pdf', 'de'); assert.deepEqual(ocrCards(result), []);
  assert.equal(result.getNode('extended-ocr').checked, false); assertOnlyOCRRequests(result, [{url, payload}]);
});

test('Extended OCR a late expanded inventory cannot replace the next page or restore the old placement outline', async () => {
  const saved = ocrEditorFixture(), delayed = deferredResponse();
  const result = await bootSavedReview(saved, {expectedReads: [ocrRead(saved, delayed.promise),
    expandedRead(saved, expandedInventory(saved, [expandedItem('page-two', 2)], [], 2), 2, false)]});
  await openSavedReview(result); const pending = showOCR(result); await settle(); await result.dispatch('next-page', 'click');
  delayed.resolve(expandedInventory(saved)); await pending;
  assert(ocrCards(result).some(card => card.dataset.ocrId === 'page-two')); assert(!ocrCards(result).some(card => card.dataset.ocrId === 'word-one'));
  assert.equal(result.getNode('ocr-placement').hidden, true); assertOnlyOCRRequests(result);
});

for (const mismatch of ['capability', 'insertion page']) {
  test('Extended OCR malformed ' + mismatch + ' closes the edit surface without sending a mutation', async () => {
    const saved = ocrEditorFixture(), inventory = expandedInventory(saved, [expandedItem()], [savedInsertion()]);
    if (mismatch === 'capability') inventory.expansion_sha256 = 'untrusted'; else inventory.insertions[0].page = 2;
    const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, inventory, 1, false)]});
    await openExpanded(result); assert.deepEqual(ocrCards(result), []); assert.equal(result.getNode('show-ocr').disabled, true);
    assert.equal(result.getNode('extended-ocr').disabled, true); assert.equal(result.getNode('ocr-placement').hidden, true); assertOnlyOCRRequests(result);
  });
}

test('Extended OCR authoritative overlap refusal keeps the unsaved word, rectangle and reviewer notes intact', async () => {
  const saved = ocrEditorFixture(), before = JSON.stringify(saved), payload = insertionPayload(saved), url = '/api/workspaces/' + saved.workspace_id + '/ocr-insert';
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved), 1, false)],
    expectedMutations: [{url, payload, ok: false, response: {error: 'The insertion rectangle overlaps existing text.'}}]});
  await openExpanded(result); await fillInsertion(result); await result.dispatch(buttonNamed(insertionCard(result), 'Save insertion draft'), 'click');
  assert.deepEqual(insertionControls(result).map(field => field.value), ['Missing', 'word-one', 'after', '35', '20', '12', '4']);
  assert.match(result.getNode('notice').textContent, /overlaps/); assert.equal(JSON.stringify(saved), before);
  await result.dispatch('tab-checks', 'click'); assertSavedNotes(result, saved.manual_items.slice(0, 2)); assertOnlyOCRRequests(result, [{url, payload}]);
});

test('Extended OCR keeps a newer word and rectangle when a delayed replacement makes its selected anchor unavailable', async () => {
  const saved = ocrEditorFixture(), response = ocrEditedView(saved), delayed = deferredResponse(), words = [expandedItem(), expandedItem('word-two')];
  const value = 'ÉαЯ', payload = {revision: 7, id: 'word-one', value, inventory_sha256: EXPANDED_INVENTORY, context_sha256: OCR_CONTEXT, expansion_sha256: EXPANDED_CAPABILITY};
  const url = '/api/workspaces/' + saved.workspace_id + '/ocr-edit';
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved, words), 1, false),
    expandedRead(saved, expandedInventory(response, [{...words[0], value}, words[1]]))], expectedMutations: [{url, payload, response: delayed.promise}]});
  await openExpanded(result); ocrInput(result).value = value;
  const pending = result.dispatch(buttonNamed(ocrCard(result), 'Save correction draft'), 'click'); await settle();
  const newer = await fillInsertion(result, {value: 'Retained'}); newer[0].focus(); newer[0].setSelectionRange(2, 6);
  delayed.resolve(response); await pending; await settle(); const fields = insertionControls(result);
  assertFreshFocus(result, fields[0], newer[0]); assert.deepEqual(fields.map(field => field.value), ['Retained', '', 'after', '35', '20', '12', '4']);
  assert.equal(fields[0].selectionStart, 2); assert.equal(fields[0].selectionEnd, 6);
  assert(descendants(insertionCard(result)).some(node => /earlier anchor is no longer available/.test(node.textContent)));
  await result.dispatch(buttonNamed(insertionCard(result), 'Save insertion draft'), 'click'); assert.match(result.getNode('notice').textContent, /Choose an available nearby recognized word/);
  assertOnlyOCRRequests(result, [{url, payload}]);
});

test('Extended OCR reopens an unsaved expanded draft with its exact profile and without writing it to a saved review', async () => {
  const {first, second} = navigationFixtures(); first.ocr_editor = ocrEditorFixture().ocr_editor;
  const before = JSON.stringify(first);
  const result = await bootNavigation(first, second, {expectedReads: [expandedRead(first, expandedInventory(first), 1, false),
    expandedRead(first, expandedInventory(first))]});
  await openNamedWorkspace(result, 'workspace-A.pdf'); await showOCR(result); await fillInsertion(result, {value: 'Retained'});
  await openNamedWorkspace(result, 'workspace-B.pdf'); await openNamedWorkspace(result, 'workspace-A.pdf'); await showOCR(result);
  assert.equal(result.getNode('extended-ocr').checked, true); assert.equal(insertionControls(result)[0].value, 'Retained');
  assert.equal(JSON.stringify(first), before); assertOnlyOCRRequests(result);
});

test('Extended OCR does not rebind retained local fields when the immutable inventory changes and offers an explicit local clear', async () => {
  const saved = ocrEditorFixture(), different = expandedInventory(saved); different.inventory_sha256 = 'f'.repeat(64);
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved), 1, false),
    expandedRead(saved, expandedInventory(saved, [expandedItem('page-two', 2)], [], 2), 2), expandedRead(saved, different)]});
  await openExpanded(result); await fillInsertion(result, {value: 'Earlier'});
  await result.dispatch('next-page', 'click'); await result.dispatch('previous-page', 'click');
  assert.equal(insertionControls(result)[0].value, ''); assert.equal(result.getNode('ocr-clear-drafts').hidden, false);
  assert(descendants(insertionCard(result)).some(node => /earlier edit context and cannot be rebound/.test(node.textContent)));
  await result.dispatch('ocr-clear-drafts', 'click'); assert.equal(result.getNode('ocr-clear-drafts').hidden, true);
  assert.match(result.getNode('notice').textContent, /Saved corrections, PDFs and review notes remain unchanged/); assertOnlyOCRRequests(result);
});

test('Extended OCR preserves an unsaved draft through a legacy fallback and permits clearing local fields without touching saved corrections', async () => {
  const saved = ocrEditorFixture(), legacy = {...ocrInventory(saved), profile: 'legacy', expansion_available: false,
    expansion_reason: 'Earlier saved corrections still use standard editing.'};
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved), 1, false), expandedRead(saved, legacy)]});
  await openExpanded(result); await fillInsertion(result, {value: 'Earlier'}); await showOCR(result, false); await showOCR(result);
  assert.equal(result.getNode('extended-ocr').checked, false); assert.equal(result.getNode('ocr-clear-drafts').hidden, false);
  assert.equal(result.getNode('ocr-extended-help').textContent, legacy.expansion_reason);
  await result.dispatch('ocr-clear-drafts', 'click'); assert.equal(result.getNode('ocr-clear-drafts').hidden, true); assertOnlyOCRRequests(result);
});

test('Extended OCR unmodified fractional placement accepts semantically equal field order without inventing a geometry edit', async () => {
  const saved = ocrEditedView(ocrEditorFixture()), response = ocrEditedView(saved, 9, 1);
  const item = savedInsertion({placement: {order: 'after', rect: [0.123456789, 0.234567891, 0.123456789, 0.0456789123]}});
  const approved = {...item, status: 'approved', approved_by: 'Authored reviewer'};
  const payload = {revision: 8, id: INSERT_ID, reviewer: approved.approved_by, inventory_sha256: EXPANDED_INVENTORY,
    context_sha256: OCR_CONTEXT, expansion_sha256: EXPANDED_CAPABILITY}, url = '/api/workspaces/' + saved.workspace_id + '/ocr-approve';
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved, [expandedItem()], [item]), 1, false),
    expandedRead(saved, expandedInventory(response, [expandedItem()], [approved]))], expectedMutations: [{url, payload, response}]});
  await openExpanded(result); result.getNode('reviewer').value = approved.approved_by;
  await result.dispatch(buttonNamed(insertionCard(result, INSERT_ID), 'Accept insertion'), 'click');
  assert.equal(result.getNode('ocr-apply').disabled, false); assertOnlyOCRRequests(result, [{url, payload}]);
});

for (const action of ['Accept insertion', 'Remove saved insertion']) {
  test('Extended OCR ' + action + ' refuses a saved insertion whose occurrence context does not match its anchor', async () => {
    const saved = ocrEditedView(ocrEditorFixture()), item = savedInsertion({context_sha256: 'f'.repeat(64)});
    const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved, [expandedItem()], [item]), 1, false)]});
    await openExpanded(result); result.getNode('reviewer').value = 'Authored reviewer';
    await result.dispatch(buttonNamed(insertionCard(result, INSERT_ID), action), 'click');
    assert.match(result.getNode('notice').textContent, /saved insertion context changed/); assertOnlyOCRRequests(result);
  });
}

test('Extended OCR trusts per-page eligibility for quarter-turn previews without changing user placement coordinates', async () => {
  const saved = ocrEditorFixture(), inventory = expandedInventory(saved); inventory.page_geometry.rotation = 270;
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, inventory, 1, false)]});
  await openExpanded(result); const fields = await fillInsertion(result);
  assert(fields.every(field => !field.disabled)); assert.equal(result.getNode('ocr-placement').hidden, false);
  assert.deepEqual(result.getNode('ocr-placement').style, {left: '35%', top: '20%', width: '12%', height: '4%'});
  assert(!/unrotated/.test(result.getNode('ocr-extended-help').textContent)); assertOnlyOCRRequests(result);
});

test('Extended OCR late insertion response after Stop cannot restore controls, preview placement or an old notice', async () => {
  const saved = ocrEditorFixture(), response = ocrEditedView(saved), delayed = deferredResponse(); response.ocr_saved_insertion_id = INSERT_ID;
  const payload = insertionPayload(saved), url = '/api/workspaces/' + saved.workspace_id + '/ocr-insert';
  const result = await bootSavedReview(saved, {expectedReads: [expandedRead(saved, expandedInventory(saved), 1, false)],
    expectedMutations: [{url, payload, response: delayed.promise}, stopExpectation()]});
  await openExpanded(result); await fillInsertion(result);
  const pending = result.dispatch(buttonNamed(insertionCard(result), 'Save insertion draft'), 'click'); await settle();
  await result.dispatch('stop', 'click'); delayed.resolve(response); await pending;
  assertStoppedNotice(result); assert.equal(result.getNode('ocr-placement').hidden, true);
  assertOnlyOCRRequests(result, [{url, payload}, {url: '/api/stop', payload: {}}]);
});

test('Extended OCR corrected-copy request locks against a repeated click until the worker job is received', async () => {
  const saved = ocrEditedView(ocrEditorFixture(), 8, 1), delayed = deferredResponse();
  const payload = {revision: 8}, url = '/api/workspaces/' + saved.workspace_id + '/ocr-apply';
  const result = await bootSavedReview(saved, {captureTimers: true, expectedMutations: [{url, payload, response: delayed.promise}]});
  await openSavedReview(result); const pending = result.dispatch('ocr-apply', 'click'); await settle();
  assert.equal(result.getNode('ocr-apply').disabled, true); await result.dispatch('ocr-apply', 'click');
  delayed.resolve({job_id: 'authored-expanded-copy'}); await pending;
  assert.equal(result.scheduledTimers.length, 1); assertOnlyOCRRequests(result, [{url, payload}]);
});

// Authored v2 views qualify the actual native-select listeners only. These
// doubles do not classify an image, edit a PDF or grant semantic acceptance.
function contentRoleFixture() {
  const saved = repairControlsFixture();
  const common = {status: 'pending', human_touched: false, structural_eligible: true,
    structural_limitations: [], context_text_source: 'Authored v2 scope only',
    context_sha256: 'b'.repeat(64), structure_path: 'root/K/0', references: []};
  saved.decisions.push(
    {...common, id: 'document-container', kind: 'structure-role', element: '80:0', page: null,
      current: 'Div', value: 'Div', allowed_values: ['Div', 'Document'],
      context_text: 'Existing top-level grouping with all document content'},
    {...common, id: 'figure-purpose-one', kind: 'figure-purpose', element: '81:0', page: 1,
      current: 'Figure', value: 'Figure', allowed_values: ['Figure', 'Artifact'],
      context_text: LITERAL_CONTEXT, references: [{page: 1, stream: 'page', mcid: 8}],
      figure_bbox: {status: 'valid', bbox: [10, 20, 80, 90], units: 'PDF default user space',
        coordinate_system: 'bottom-left PDF coordinates (not preview percentages)',
        reason: 'Authored declared-bounds diagnostic: ' + LITERAL_CONTEXT, page_box: [0, 0, 100, 100]}},
    {...common, id: 'section-container', kind: 'structure-role', element: '82:0', page: 2,
      current: 'Div', value: 'Div', allowed_values: ['Div', 'Sect'],
      context_text: 'Existing nested grouping on the second page'},
    {...common, id: 'unsafe-figure-purpose', kind: 'figure-purpose', element: '83:0', page: 1,
      current: 'Figure', value: 'Figure', allowed_values: ['Figure'], structural_eligible: false,
      structural_limitations: ['The occurrence has shared content: ' + LITERAL_CONTEXT],
      context_text: 'Unsafe source-authored figure',
      figure_bbox: {status: 'unresolved', bbox: null, units: 'PDF default user space',
        coordinate_system: 'bottom-left PDF coordinates (not preview percentages)',
        reason: 'Cannot resolve a unique occurrence', page_box: null}},
  );
  return saved;
}

test('DOM content roles: collapsed controls stay hidden and document-wide roles remain available across pages', async () => {
  const saved = contentRoleFixture(), before = JSON.stringify(saved);
  const result = await bootSavedReview(saved);
  await openSavedReview(result);
  assert.deepEqual(decisionCards(result).map(card => card.dataset.decisionId), ['title-control', 'language-control']);
  await showStructure(result);
  assert.deepEqual(decisionCards(result).map(card => card.dataset.decisionId),
    ['title-control', 'language-control', 'heading-one', 'table-one', 'unsafe-heading',
      'document-container', 'figure-purpose-one', 'unsafe-figure-purpose']);
  assert.match(result.getNode('structure-summary').textContent, /1 document-wide container control included/);
  const root = selectsFor(cardFor(result, 'document-container'))[0];
  assert.deepEqual(root.children.map(option => option.value), ['Div', 'Document']);
  assert.match(root.getAttribute('aria-label'), /for the document/);
  await result.dispatch('next-page', 'click');
  assert.equal(cardFor(result, 'document-container').dataset.decisionId, 'document-container');
  assert.deepEqual(selectsFor(cardFor(result, 'section-container'))[0].children.map(option => option.value), ['Div', 'Sect']);
  assert.equal(decisionCards(result).some(card => card.dataset.decisionId === 'figure-purpose-one'), false);
  await showStructure(result, false);
  assert.deepEqual(decisionCards(result).map(card => card.dataset.decisionId), ['title-control', 'language-control']);
  assertSavedSnapshotUnchanged(result, saved, before);
  expectOnlyMutations(result, []);
});

for (const [id, value, page] of [
  ['figure-purpose-one', 'Artifact', 1], ['document-container', 'Document', 1], ['section-container', 'Sect', 2],
]) {
  test('DOM content roles: Save records only the exact pending purpose or role for ' + id, async () => {
    const saved = contentRoleFixture(), before = JSON.stringify(saved);
    const url = '/api/workspaces/' + saved.workspace_id + '/edit';
    const payload = {revision: 7, id, value}, response = editedView(saved, id, value);
    const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response}]});
    await openSavedReview(result); await showStructure(result);
    if (page === 2) await result.dispatch('next-page', 'click');
    const card = cardFor(result, id), select = selectsFor(card)[0];
    assert.equal(select.value, saved.decisions.find(item => item.id === id).value);
    assert(!descendants(card).some(node => node.dataset.aiId), 'New structural choices cannot be selected for AI.');
    select.value = value; await result.dispatch(select, 'change');
    assert.deepEqual(result.mutationRequests, [], 'A native select change is neither a save nor approval.');
    const save = buttonNamed(card, 'Save edit'); save.focus();
    await result.dispatch(save, 'click');
    assertFreshFocus(result, buttonNamed(cardFor(result, id), 'Save edit'), save);
    assert.equal(selectsFor(cardFor(result, id))[0].value, value);
    assert.equal(response.decisions.find(item => item.id === id).status, 'pending');
    assert.equal(result.getNode('apply').disabled, true);
    assertSavedSnapshotUnchanged(result, saved, before);
    expectOnlyMutations(result, [{url, payload}]);
  });

  test('DOM content roles: named acceptance uses the saved revision and leaves Apply separate for ' + id, async () => {
    const saved = contentRoleFixture(), before = JSON.stringify(saved), prefix = '/api/workspaces/' + saved.workspace_id;
    const edited = editedView(saved, id, value), accepted = structuredClone(edited);
    accepted.revision = 9;
    Object.assign(accepted.decisions.find(item => item.id === id), {status: 'approved', approved_by: 'Authored content reviewer'});
    const expected = [
      {url: prefix + '/edit', payload: {revision: 7, id, value}, response: edited},
      {url: prefix + '/approve', payload: {revision: 8, id, reviewer: 'Authored content reviewer'}, response: accepted},
    ];
    const result = await bootSavedReview(saved, {expectedMutations: expected});
    await openSavedReview(result); await showStructure(result);
    if (page === 2) await result.dispatch('next-page', 'click');
    const card = cardFor(result, id); selectsFor(card)[0].value = value;
    result.getNode('reviewer').value = ' Authored content reviewer ';
    const accept = buttonNamed(card, 'Accept this value'); accept.focus();
    await result.dispatch(accept, 'click');
    assertFreshFocus(result, buttonNamed(cardFor(result, id), 'Accept this value'), accept);
    assert.equal(result.getNode('apply').disabled, false);
    assertSavedSnapshotUnchanged(result, saved, before);
    expectOnlyMutations(result, expected.map(({url, payload}) => ({url, payload})));
  });

  test('DOM content roles: unnamed acceptance refuses before saving ' + id, async () => {
    const saved = contentRoleFixture(), before = JSON.stringify(saved), result = await bootSavedReview(saved);
    await openSavedReview(result); await showStructure(result);
    if (page === 2) await result.dispatch('next-page', 'click');
    const card = cardFor(result, id); selectsFor(card)[0].value = value;
    await result.dispatch(buttonNamed(card, 'Accept this value'), 'click');
    assert.match(result.getNode('notice').textContent, /Enter your name/);
    assertSavedSnapshotUnchanged(result, saved, before);
    expectOnlyMutations(result, []);
  });
}

test('DOM content roles: classification warnings and bounds diagnostics are literal read-only evidence', async () => {
  const saved = contentRoleFixture(), before = JSON.stringify(saved), result = await bootSavedReview(saved);
  await openSavedReview(result); await showStructure(result);
  const card = cardFor(result, 'figure-purpose-one'), select = selectsFor(card)[0];
  assert.deepEqual(select.children.map(option => option.textContent), ['Keep meaningful figure', 'Mark decorative artifact']);
  assert(descendants(card).some(node => node.textContent.includes('only when this occurrence conveys no information')));
  assert(descendants(card).some(node => node.textContent.includes('same figure cannot be applied together')));
  assert(descendants(card).some(node => node.textContent.includes('Declared figure bounds passed the recorded mechanical checks.')));
  const diagnostic = descendants(card).find(node => node.tagName === 'PRE' && node.textContent.includes('bottom-left PDF coordinates'));
  assert(diagnostic && diagnostic.textContent.includes('not preview percentages'));
  const recorded = JSON.parse(diagnostic.textContent);
  assert.deepEqual(recorded, saved.decisions.find(item => item.id === 'figure-purpose-one').figure_bbox,
    'The diagnostic preserves every exact original value, including JSON-escaped hostile-looking text.');
  assert.equal(recorded.reason, 'Authored declared-bounds diagnostic: ' + LITERAL_CONTEXT);
  assert.equal(diagnostic.children.length, 0, 'Recorded text creates no child markup.');
  assert.equal(descendants(card).filter(node => ['IMG', 'SCRIPT'].includes(node.tagName)).length, 0);
  assert.equal(descendants(card).filter(node => ['INPUT', 'TEXTAREA', 'SELECT'].includes(node.tagName)).length, 1,
    'Bounds have no coordinate editor or automatic correction control.');
  assertSavedSnapshotUnchanged(result, saved, before);
  expectOnlyMutations(result, []);
});

for (const status of ['missing', 'invalid', 'unresolved', 'unrecognized']) {
  test('DOM content roles: ' + status + ' bounds remain an explicit diagnostic without guessed geometry', async () => {
    const saved = contentRoleFixture(), item = saved.decisions.find(item => item.id === 'figure-purpose-one');
    item.figure_bbox = {status, bbox: null, reason: 'Authored unknown bounds; inspect the original.', page_box: null};
    const before = JSON.stringify(saved), result = await bootSavedReview(saved);
    await openSavedReview(result); await showStructure(result);
    const card = cardFor(result, item.id);
    const expected = {missing: /bounds are missing/, invalid: /bounds are invalid/,
      unresolved: /bounds could not be verified/, unrecognized: /bounds are unknown/}[status];
    assert(descendants(card).some(node => expected.test(node.textContent)));
    assert.equal(descendants(card).filter(node => ['INPUT', 'TEXTAREA', 'SELECT'].includes(node.tagName)).length, 1);
    assertSavedSnapshotUnchanged(result, saved, before);
    expectOnlyMutations(result, []);
  });
}

for (const problem of ['unsafe', 'stale', 'missing-choices', 'foreign-choice']) {
  test('DOM content roles: ' + problem + ' capability disables all purpose actions while keeping the saved value', async () => {
    const saved = contentRoleFixture(), item = saved.decisions.find(item => item.id === 'figure-purpose-one');
    item.value = 'Artifact';
    if (problem === 'unsafe') { item.structural_eligible = false; item.structural_limitations = ['Authored shared occurrence refusal']; }
    else if (problem === 'stale') saved.stale = true;
    else if (problem === 'missing-choices') delete item.allowed_values;
    else item.allowed_values.push('Table');
    const before = JSON.stringify(saved), result = await bootSavedReview(saved);
    await openSavedReview(result); await showStructure(result);
    const card = cardFor(result, item.id), select = selectsFor(card)[0];
    assert.equal(select.value, 'Artifact', 'A disabled control must retain the saved draft for inspection.');
    assert.equal(select.disabled, true);
    assert(!select.children.some(option => option.value === 'Table'));
    for (const label of ['Save edit', 'Accept this value']) {
      const button = buttonNamed(card, label); assert.equal(button.disabled, true);
      await result.dispatch(button, 'click');
    }
    assertSavedSnapshotUnchanged(result, saved, before);
    expectOnlyMutations(result, []);
  });
}

for (const returnToA of [false, true]) {
  test('DOM content roles: a delayed Accept cannot approve after ' + (returnToA ? 'A to B to A' : 'A to B'), async () => {
    const first = contentRoleFixture(), second = contentRoleFixture();
    first.source.path = '/authored/workspace-A.pdf'; second.source.path = '/authored/workspace-B.pdf';
    second.workspace_id = 'f'.repeat(24); second.decisions.find(item => item.kind === 'language').value = 'de';
    const before = [JSON.stringify(first), JSON.stringify(second)], delayed = deferredResponse();
    const url = '/api/workspaces/' + first.workspace_id + '/edit';
    const payload = {revision: 7, id: 'figure-purpose-one', value: 'Artifact'};
    const result = await bootNavigation(first, second, {expectedMutations: [{url, payload, response: delayed.promise}]});
    await openNamedWorkspace(result, 'workspace-A.pdf'); await showStructure(result);
    result.getNode('reviewer').value = 'Authored race reviewer';
    const card = cardFor(result, payload.id); selectsFor(card)[0].value = payload.value;
    const accepting = result.dispatch(buttonNamed(card, 'Accept this value'), 'click'); await settle();
    await result.dispatch('back', 'click'); await openNamedWorkspace(result, 'workspace-B.pdf');
    if (returnToA) { await result.dispatch('back', 'click'); await openNamedWorkspace(result, 'workspace-A.pdf'); }
    delayed.resolve(editedView(first, payload.id, payload.value)); await accepting;
    assertVisibleWorkspace(result, returnToA ? 'workspace-A.pdf' : 'workspace-B.pdf', returnToA ? 'en-US' : 'de');
    assert.equal(selectsFor(cardFor(result, payload.id))[0].value, 'Figure');
    assert.equal(JSON.stringify(first), before[0]); assert.equal(JSON.stringify(second), before[1]);
    expectOnlyMutations(result, [{url, payload}]);
  });
}

test('DOM content roles: a delayed other response retains a newly focused unsaved container draft', async () => {
  const saved = contentRoleFixture(), delayed = deferredResponse();
  const url = '/api/workspaces/' + saved.workspace_id + '/edit';
  const payload = {revision: 7, id: 'heading-one', value: 'H3'};
  const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: delayed.promise}]});
  await openSavedReview(result); await showStructure(result);
  const heading = cardFor(result, 'heading-one'); selectsFor(heading)[0].value = 'H3';
  const saving = result.dispatch(buttonNamed(heading, 'Save edit'), 'click'); await settle();
  const draft = selectsFor(cardFor(result, 'document-container'))[0]; draft.value = 'Document'; draft.focus();
  delayed.resolve(editedView(saved, 'heading-one', 'H3')); await saving;
  const current = selectsFor(cardFor(result, 'document-container'))[0];
  assertFreshFocus(result, current, draft); assert.equal(current.value, 'Document');
  assert.equal(saved.decisions.find(item => item.id === 'document-container').value, 'Div');
  expectOnlyMutations(result, [{url, payload}]);
});

test('DOM content roles: an active job keeps new page and document controls disabled after navigation', async () => {
  const saved = contentRoleFixture(), before = JSON.stringify(saved);
  const url = '/api/workspaces/' + saved.workspace_id + '/auto-fix';
  const payload = {revision: 7, consent: true, use_ai: false, ai_consent: false,
    endpoint: '', model: '', include_images: false, reasoning_effort: null};
  const result = await bootSavedReview(saved, {captureTimers: true,
    expectedMutations: [{url, payload, response: {job_id: 'authored-content-role-guard'}}]});
  await openSavedReview(result); await showStructure(result); await result.dispatch('auto-fix', 'click');
  await showStructure(result, false); await showStructure(result, true);
  for (const id of ['figure-purpose-one', 'document-container']) {
    assert(selectsFor(cardFor(result, id)).every(field => field.disabled));
    for (const label of ['Save edit', 'Accept this value']) assert.equal(buttonNamed(cardFor(result, id), label).disabled, true);
  }
  await result.dispatch('next-page', 'click');
  for (const id of ['document-container', 'section-container']) {
    assert(selectsFor(cardFor(result, id)).every(field => field.disabled));
    await result.dispatch(buttonNamed(cardFor(result, id), 'Save edit'), 'click');
  }
  assert.equal(JSON.stringify(saved), before);
  assert.deepEqual(result.mutationRequests, [{url, payload}]); assert.deepEqual(result.remainingMutations, []);
  assert.deepEqual(result.unexpectedRequests, []);
});

// Source-authored local-language decisions. These views do not infer language,
// edit PDFs, run a browser or turn an accepted field into semantic verification.
function scopedLanguageFixture() {
  const saved = contentRoleFixture();
  const inheritedSource = {kind: 'document', element: null, structure_path: null};
  const local = (id, kind, page, direct, inherited, element) => ({
    id, kind, page, element, current: JSON.stringify({language: direct}), value: JSON.stringify({language: direct}),
    status: 'pending', human_touched: false, structural_eligible: true, structural_limitations: [],
    context_text: kind === 'page-language' ? 'Existing page-exclusive group' : LITERAL_CONTEXT,
    context_text_source: 'Authored exact tagged text scope', context_sha256: 'c'.repeat(64),
    structure_path: 'root/K/language/' + id, references: [{page, stream: 'page', mcid: page + 10}],
    language_context: {policy: 'explicit-local-language-1', direct, direct_valid: true, inherited, inherited_valid: true,
      inherited_source: {...inheritedSource}, effective: direct ?? inherited, effective_valid: true,
      effective_source: direct === null ? {...inheritedSource} : {kind: 'structure', element, structure_path: 'root/K/language/' + id}},
    language_scope: {kind: kind === 'page-language' ? 'page' : 'passage', page, target_element: element,
      coverage: {known_references: kind === 'page-language' ? 3 : 1, page_real_references: 3, complete_page: kind === 'page-language'},
      descendant_overrides: kind === 'page-language' ? [{element: '91:0', structure_path: 'root/K/one/passage', language: 'es', valid: true}] : [], limits: []},
  });
  saved.decisions.push(local('page-language-one', 'page-language', 1, 'de', 'en-US', '90:0'),
    local('passage-language-one', 'passage-language', 1, 'es', 'de', '91:0'),
    local('page-language-two', 'page-language', 2, null, 'en-US', '92:0'),
    local('passage-language-two', 'passage-language', 2, null, 'fr', '93:0'));
  return saved;
}

function localLanguageFields(card) {
  const mode = selectsFor(card)[0];
  const tags = descendants(card).filter(node => node.tagName === 'INPUT' && node.type !== 'checkbox');
  assert(mode && tags.length === 1, 'A language setting has one native mode and one tag field.');
  return {mode, tag: tags[0]};
}

test('DOM scoped language: controls are collapsed and page-bound while document language remains separate', async () => {
  const saved = scopedLanguageFixture(), before = JSON.stringify(saved), result = await bootSavedReview(saved);
  await openSavedReview(result);
  assert.deepEqual(decisionCards(result).map(card => card.dataset.decisionId), ['title-control', 'language-control']);
  await showStructure(result);
  assert(decisionCards(result).some(card => card.dataset.decisionId === 'page-language-one'));
  assert(decisionCards(result).some(card => card.dataset.decisionId === 'passage-language-one'));
  assert(!decisionCards(result).some(card => card.dataset.decisionId.endsWith('language-two')));
  assert.equal(descendants(cardFor(result, 'language-control')).find(node => node.tagName === 'INPUT').value, 'en-US');
  await result.dispatch('next-page', 'click');
  assert(!decisionCards(result).some(card => card.dataset.decisionId.endsWith('language-one')));
  assert.equal(localLanguageFields(cardFor(result, 'passage-language-two')).mode.value, 'inherit');
  assert.equal(localLanguageFields(cardFor(result, 'passage-language-two')).tag.readOnly, true);
  await showStructure(result, false);
  assert.deepEqual(decisionCards(result).map(card => card.dataset.decisionId), ['title-control', 'language-control']);
  assertSavedSnapshotUnchanged(result, saved, before); expectOnlyMutations(result, []);
});

test('DOM scoped language: direct, effective, inherited and preserved descendant scope are literal source evidence', async () => {
  const saved = scopedLanguageFixture(), before = JSON.stringify(saved), result = await bootSavedReview(saved);
  await openSavedReview(result); await showStructure(result);
  const passage = cardFor(result, 'passage-language-one'), page = cardFor(result, 'page-language-one');
  assert(descendants(passage).some(node => node.textContent.includes('Direct override: es')));
  assert(descendants(passage).some(node => node.textContent.includes('Current effective language: es; source: this tagged element.')));
  assert(descendants(passage).some(node => node.textContent.includes('Inherited language without this override: de')));
  assert(descendants(passage).some(node => node.textContent.includes('not an arbitrary text selection, translation')));
  assert(descendants(page).some(node => node.textContent.includes('Explicit overrides inside it stay in place')));
  assert(descendants(page).some(node => node.textContent.includes('Recorded explicit descendant overrides: 1')));
  const scope = descendants(page).find(node => node.tagName === 'PRE' && node.textContent.includes('language_context'));
  const item = saved.decisions.find(item => item.id === 'page-language-one');
  assert.deepEqual(JSON.parse(scope.textContent), {language_context: item.language_context, language_scope: item.language_scope});
  assert.equal(scope.children.length, 0);
  for (const card of [passage, page]) {
    assert.equal(descendants(card).filter(node => ['IMG', 'SCRIPT', 'TEXTAREA'].includes(node.tagName)).length, 0);
    assert(!descendants(card).some(node => node.dataset.aiId));
  }
  assertSavedSnapshotUnchanged(result, saved, before); expectOnlyMutations(result, []);
});

test('DOM scoped language: invalid source language remains correctable without trusting or rendering it as markup', async () => {
  const saved = scopedLanguageFixture(), item = saved.decisions.find(item => item.id === 'passage-language-one');
  item.current = item.value = JSON.stringify({language: LITERAL_CONTEXT});
  Object.assign(item.language_context, {direct: LITERAL_CONTEXT, direct_valid: false, effective: LITERAL_CONTEXT, effective_valid: false});
  item.language_scope.descendant_overrides = [{element: '95:0', structure_path: 'root/K/child', language: LITERAL_CONTEXT, valid: false}];
  const before = JSON.stringify(saved), result = await bootSavedReview(saved);
  await openSavedReview(result); await showStructure(result);
  const card = cardFor(result, item.id), fields = localLanguageFields(card);
  assert.equal(fields.tag.value, LITERAL_CONTEXT.replace(/[\r\n]/g, ''));
  assert.equal(fields.tag.disabled, false); assert.equal(buttonNamed(card, 'Save edit').disabled, false);
  assert(descendants(card).some(node => node.textContent.includes('source override is not a valid language tag')));
  const scope = descendants(card).find(node => node.tagName === 'PRE' && node.textContent.includes('language_context'));
  assert.equal(JSON.parse(scope.textContent).language_context.direct, LITERAL_CONTEXT);
  assert.equal(scope.children.length, 0); assert.equal(descendants(card).filter(node => ['IMG', 'SCRIPT'].includes(node.tagName)).length, 0);
  assertSavedSnapshotUnchanged(result, saved, before); expectOnlyMutations(result, []);
});

for (const id of ['page-language-one', 'passage-language-one']) {
  test('DOM scoped language: Save records only a pending explicit tag for ' + id, async () => {
    const saved = scopedLanguageFixture(), before = JSON.stringify(saved), value = JSON.stringify({language: 'fr-CA'});
    const url = '/api/workspaces/' + saved.workspace_id + '/edit', payload = {revision: 7, id, value};
    const response = editedView(saved, id, value), result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response}]});
    await openSavedReview(result); await showStructure(result);
    const card = cardFor(result, id), fields = localLanguageFields(card);
    fields.mode.value = 'set'; await result.dispatch(fields.mode, 'change'); fields.tag.value = 'fr-CA';
    assert.deepEqual(result.mutationRequests, []);
    const save = buttonNamed(card, 'Save edit'); save.focus(); await result.dispatch(save, 'click');
    assertFreshFocus(result, buttonNamed(cardFor(result, id), 'Save edit'), save);
    assert.equal(localLanguageFields(cardFor(result, id)).tag.value, 'fr-CA');
    assert.equal(response.decisions.find(item => item.id === id).status, 'pending');
    assert.equal(result.getNode('apply').disabled, true);
    assertSavedSnapshotUnchanged(result, saved, before); expectOnlyMutations(result, [{url, payload}]);
  });

  test('DOM scoped language: inheritance is an explicit null override for ' + id, async () => {
    const saved = scopedLanguageFixture(), before = JSON.stringify(saved), value = JSON.stringify({language: null});
    const url = '/api/workspaces/' + saved.workspace_id + '/edit', payload = {revision: 7, id, value};
    const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: editedView(saved, id, value)}]});
    await openSavedReview(result); await showStructure(result);
    const card = cardFor(result, id), fields = localLanguageFields(card);
    fields.mode.value = 'inherit'; await result.dispatch(fields.mode, 'change');
    assert.equal(fields.tag.readOnly, true); assert.equal(fields.tag.getAttribute('aria-readonly'), 'true');
    fields.tag.value = 'ignored-authored-tag';
    await result.dispatch(buttonNamed(card, 'Save edit'), 'click');
    assert.equal(localLanguageFields(cardFor(result, id)).mode.value, 'inherit');
    assert.equal(localLanguageFields(cardFor(result, id)).tag.readOnly, true);
    assertSavedSnapshotUnchanged(result, saved, before); expectOnlyMutations(result, [{url, payload}]);
  });

  test('DOM scoped language: named acceptance saves exact tag then approves its new revision for ' + id, async () => {
    const saved = scopedLanguageFixture(), before = JSON.stringify(saved), value = JSON.stringify({language: 'fr'});
    const prefix = '/api/workspaces/' + saved.workspace_id, edited = editedView(saved, id, value), accepted = structuredClone(edited);
    accepted.revision = 9; Object.assign(accepted.decisions.find(item => item.id === id), {status: 'approved', approved_by: 'Authored language reviewer'});
    const expected = [{url: prefix + '/edit', payload: {revision: 7, id, value}, response: edited},
      {url: prefix + '/approve', payload: {revision: 8, id, reviewer: 'Authored language reviewer'}, response: accepted}];
    const result = await bootSavedReview(saved, {expectedMutations: expected});
    await openSavedReview(result); await showStructure(result); result.getNode('reviewer').value = ' Authored language reviewer ';
    localLanguageFields(cardFor(result, id)).tag.value = 'fr';
    const accept = buttonNamed(cardFor(result, id), 'Accept this value'); accept.focus(); await result.dispatch(accept, 'click');
    assertFreshFocus(result, buttonNamed(cardFor(result, id), 'Accept this value'), accept);
    assert.equal(result.getNode('apply').disabled, false);
    assertSavedSnapshotUnchanged(result, saved, before); expectOnlyMutations(result, expected.map(({url, payload}) => ({url, payload})));
  });

  test('DOM scoped language: unnamed acceptance refuses before a save for ' + id, async () => {
    const saved = scopedLanguageFixture(), before = JSON.stringify(saved), result = await bootSavedReview(saved);
    await openSavedReview(result); await showStructure(result); localLanguageFields(cardFor(result, id)).tag.value = 'fr';
    await result.dispatch(buttonNamed(cardFor(result, id), 'Accept this value'), 'click');
    assert.match(result.getNode('notice').textContent, /Enter your name/);
    assertSavedSnapshotUnchanged(result, saved, before); expectOnlyMutations(result, []);
  });
}

for (const defect of ['unsafe', 'stale', 'missing-context', 'wrong-policy', 'wrong-page-scope', 'incomplete-page']) {
  test('DOM scoped language: ' + defect + ' scope disables mutations and retains the saved draft', async () => {
    const saved = scopedLanguageFixture(), item = saved.decisions.find(item => item.id === 'page-language-one');
    if (defect === 'unsafe') { item.structural_eligible = false; item.structural_limitations = ['Shared source language: ' + LITERAL_CONTEXT]; }
    else if (defect === 'stale') saved.stale = true;
    else if (defect === 'missing-context') delete item.language_context;
    else if (defect === 'wrong-policy') item.language_context.policy = 'unrecognized-authority';
    else if (defect === 'wrong-page-scope') item.language_scope.page = 2;
    else item.language_scope.coverage.complete_page = false;
    const before = JSON.stringify(saved), result = await bootSavedReview(saved);
    await openSavedReview(result); await showStructure(result);
    const card = cardFor(result, item.id), fields = localLanguageFields(card);
    assert.equal(fields.tag.value, 'de'); assert(fields.mode.disabled && fields.tag.disabled);
    for (const text of ['Save edit', 'Accept this value']) { assert(buttonNamed(card, text).disabled); await result.dispatch(buttonNamed(card, text), 'click'); }
    assertSavedSnapshotUnchanged(result, saved, before); expectOnlyMutations(result, []);
  });
}

test('DOM scoped language: empty Set input refuses rather than silently switching to inheritance', async () => {
  const saved = scopedLanguageFixture(), result = await bootSavedReview(saved);
  await openSavedReview(result); await showStructure(result); localLanguageFields(cardFor(result, 'passage-language-one')).tag.value = '  ';
  await result.dispatch(buttonNamed(cardFor(result, 'passage-language-one'), 'Save edit'), 'click');
  assert.match(result.getNode('notice').textContent, /Enter a language tag or choose Use inherited language/);
  expectOnlyMutations(result, []);
});

test('DOM scoped language: authoritative syntax refusal retains entered text without approval or Apply', async () => {
  const saved = scopedLanguageFixture(), value = JSON.stringify({language: 'en_US'}), url = '/api/workspaces/' + saved.workspace_id + '/edit';
  const payload = {revision: 7, id: 'passage-language-one', value};
  const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, ok: false, response: {error: 'Use a well-formed language tag.'}}]});
  await openSavedReview(result); await showStructure(result); const field = localLanguageFields(cardFor(result, payload.id)).tag;
  field.value = 'en_US'; await result.dispatch(buttonNamed(cardFor(result, payload.id), 'Save edit'), 'click');
  assert.equal(field.value, 'en_US'); assert.match(result.getNode('notice').textContent, /well-formed language tag/);
  assert.equal(result.getNode('apply').disabled, true); expectOnlyMutations(result, [{url, payload}]);
});

for (const navigation of ['next-page', 'page-away-and-back', 'collapse-and-reopen', 'tab-away-and-back']) {
  test('DOM scoped language: delayed Save leaves only a draft after ' + navigation, async () => {
    const saved = scopedLanguageFixture(), before = JSON.stringify(saved), delayed = deferredResponse();
    const id = 'passage-language-one', value = JSON.stringify({language: 'fr'}), url = '/api/workspaces/' + saved.workspace_id + '/edit';
    const payload = {revision: 7, id, value}, result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: delayed.promise}]});
    await openSavedReview(result); await showStructure(result); result.getNode('reviewer').value = 'Authored delayed language reviewer';
    localLanguageFields(cardFor(result, id)).tag.value = 'fr';
    const accepting = result.dispatch(buttonNamed(cardFor(result, id), 'Accept this value'), 'click'); await settle();
    if (navigation === 'next-page' || navigation === 'page-away-and-back') { await result.dispatch('next-page', 'click'); if (navigation === 'page-away-and-back') await result.dispatch('previous-page', 'click'); }
    else if (navigation === 'collapse-and-reopen') { await showStructure(result, false); await showStructure(result, true); }
    else { await result.dispatch('tab-checks', 'click'); await result.dispatch('tab-decisions', 'click'); }
    delayed.resolve(editedView(saved, id, value)); await accepting;
    assert.equal(result.getNode('apply').disabled, true);
    assert.match(result.getNode('notice').textContent, /Language draft saved/);
    if (navigation !== 'next-page') assert.equal(localLanguageFields(cardFor(result, id)).tag.value, 'fr');
    assertSavedSnapshotUnchanged(result, saved, before); expectOnlyMutations(result, [{url, payload}]);
  });
}

for (const returnToA of [false, true]) {
  test('DOM scoped language: delayed acceptance cannot cross workspace ' + (returnToA ? 'A to B to A' : 'A to B'), async () => {
    const first = scopedLanguageFixture(), second = scopedLanguageFixture(), delayed = deferredResponse();
    first.source.path = '/authored/workspace-A.pdf'; second.source.path = '/authored/workspace-B.pdf'; second.workspace_id = 'f'.repeat(24);
    const id = 'passage-language-one', value = JSON.stringify({language: 'fr'}), url = '/api/workspaces/' + first.workspace_id + '/edit';
    const payload = {revision: 7, id, value}, result = await bootNavigation(first, second, {expectedMutations: [{url, payload, response: delayed.promise}]});
    await openNamedWorkspace(result, 'workspace-A.pdf'); await showStructure(result); result.getNode('reviewer').value = 'Authored workspace language reviewer';
    localLanguageFields(cardFor(result, id)).tag.value = 'fr';
    const accepting = result.dispatch(buttonNamed(cardFor(result, id), 'Accept this value'), 'click'); await settle();
    await result.dispatch('back', 'click'); await openNamedWorkspace(result, 'workspace-B.pdf');
    if (returnToA) { await result.dispatch('back', 'click'); await openNamedWorkspace(result, 'workspace-A.pdf'); }
    delayed.resolve(editedView(first, id, value)); await accepting;
    assertVisibleWorkspace(result, returnToA ? 'workspace-A.pdf' : 'workspace-B.pdf', 'en-US');
    assert.equal(localLanguageFields(cardFor(result, id)).tag.value, 'es'); expectOnlyMutations(result, [{url, payload}]);
  });
}

test('DOM scoped language: newer inherited-mode draft and text caret survive another delayed response', async () => {
  const saved = scopedLanguageFixture(), delayed = deferredResponse(), url = '/api/workspaces/' + saved.workspace_id + '/edit';
  const payload = {revision: 7, id: 'heading-one', value: 'H3'}, result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: delayed.promise}]});
  await openSavedReview(result); await showStructure(result); selectsFor(cardFor(result, 'heading-one'))[0].value = 'H3';
  const saving = result.dispatch(buttonNamed(cardFor(result, 'heading-one'), 'Save edit'), 'click'); await settle();
  const fields = localLanguageFields(cardFor(result, 'passage-language-one')); fields.tag.value = 'fr-CA'; fields.tag.focus(); fields.tag.setSelectionRange(1, 4, 'forward');
  fields.mode.value = 'inherit'; await result.dispatch(fields.mode, 'change');
  delayed.resolve(editedView(saved, 'heading-one', 'H3')); await saving;
  const current = localLanguageFields(cardFor(result, 'passage-language-one'));
  assertFreshFocus(result, current.tag, fields.tag); assert.equal(current.tag.value, 'fr-CA'); assert.equal(current.mode.value, 'inherit'); assert.equal(current.tag.readOnly, true);
  assert.equal(current.tag.selectionStart, 1); assert.equal(current.tag.selectionEnd, 4);
  expectOnlyMutations(result, [{url, payload}]);
});

test('DOM scoped language: active work cannot re-enable local language fields after page navigation', async () => {
  const saved = scopedLanguageFixture(), before = JSON.stringify(saved), url = '/api/workspaces/' + saved.workspace_id + '/auto-fix';
  const payload = {revision: 7, consent: true, use_ai: false, ai_consent: false, endpoint: '', model: '', include_images: false, reasoning_effort: null};
  const result = await bootSavedReview(saved, {captureTimers: true, expectedMutations: [{url, payload, response: {job_id: 'authored-language-job'}}]});
  await openSavedReview(result); await showStructure(result); await result.dispatch('auto-fix', 'click'); await showStructure(result, false); await showStructure(result, true);
  for (const id of ['page-language-one', 'passage-language-one']) {
    const card = cardFor(result, id), fields = localLanguageFields(card); assert(fields.mode.disabled && fields.tag.disabled);
    for (const label of ['Save edit', 'Accept this value']) { assert(buttonNamed(card, label).disabled); await result.dispatch(buttonNamed(card, label), 'click'); }
  }
  await result.dispatch('next-page', 'click');
  assert(localLanguageFields(cardFor(result, 'passage-language-two')).tag.disabled);
  assertSavedSnapshotUnchanged(result, saved, before); assert.deepEqual(result.mutationRequests, [{url, payload}]); assert.deepEqual(result.remainingMutations, []);
});

for (const nextValue of ['de', '']) {
  test('DOM scoped language: a newer ' + (nextValue ? 'tag' : 'empty draft') + ' prevents delayed acceptance and keeps the current fields', async () => {
    const saved = scopedLanguageFixture(), delayed = deferredResponse(), id = 'passage-language-one';
    const value = JSON.stringify({language: 'fr'}), url = '/api/workspaces/' + saved.workspace_id + '/edit', payload = {revision: 7, id, value};
    const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: delayed.promise}]});
    await openSavedReview(result); await showStructure(result); result.getNode('reviewer').value = 'Authored newer draft reviewer';
    const fields = localLanguageFields(cardFor(result, id)); fields.tag.value = 'fr';
    const accepting = result.dispatch(buttonNamed(cardFor(result, id), 'Accept this value'), 'click'); await settle();
    fields.tag.value = nextValue; fields.tag.focus();
    delayed.resolve(editedView(saved, id, value)); await accepting;
    const current = localLanguageFields(cardFor(result, id));
    assertFreshFocus(result, current.tag, fields.tag); assert.equal(current.tag.value, nextValue);
    assert.equal(result.getNode('apply').disabled, true); assert.match(result.getNode('notice').textContent, /Current fields still need saving and acceptance/);
    expectOnlyMutations(result, [{url, payload}]);
  });
}

test('DOM scoped language: starting work during a delayed save prevents its follow-up approval', async () => {
  const saved = scopedLanguageFixture(), delayed = deferredResponse(), id = 'passage-language-one';
  const prefix = '/api/workspaces/' + saved.workspace_id, value = JSON.stringify({language: 'fr'});
  const edit = {revision: 7, id, value}, automatic = {revision: 7, consent: true, use_ai: false, ai_consent: false,
    endpoint: '', model: '', include_images: false, reasoning_effort: null};
  const result = await bootSavedReview(saved, {captureTimers: true, expectedMutations: [
    {url: prefix + '/edit', payload: edit, response: delayed.promise},
    {url: prefix + '/auto-fix', payload: automatic, response: {job_id: 'authored-overlapping-language-work'}},
  ]});
  await openSavedReview(result); await showStructure(result); result.getNode('reviewer').value = 'Authored busy reviewer';
  localLanguageFields(cardFor(result, id)).tag.value = 'fr';
  const accepting = result.dispatch(buttonNamed(cardFor(result, id), 'Accept this value'), 'click'); await settle();
  await result.dispatch('auto-fix', 'click'); delayed.resolve(editedView(saved, id, value)); await accepting;
  assert(localLanguageFields(cardFor(result, id)).tag.disabled); assert.equal(result.getNode('apply').disabled, true);
  assert.deepEqual(result.mutationRequests, [{url: prefix + '/edit', payload: edit}, {url: prefix + '/auto-fix', payload: automatic}]);
  assert.deepEqual(result.remainingMutations, []); assert.deepEqual(result.unexpectedRequests, []);
});

// Navigation authoring is qualified with named DOM/HTTP doubles only. No URL
// is opened or fetched, no PDF is processed and no semantic approval is granted.
function navigationFixture() {
  const saved = repairControlsFixture();
  const context = (scope, overrides = {}) => ({policy: 'reviewed-navigation-1', scope,
    annotation_index: null, bookmark_index: null, source_name: null, source_target: null,
    page_count: 2, allowed_target_kinds: ['page', 'uri'], linked_structure: null,
    limits: {name_chars: 4000, title_chars: 500, uri_chars: 4096, new_bookmarks: 200, new_depth: 10}, ...overrides});
  const row = (id, kind, page, current, navigation_context) => ({id, kind, page, current, value: current,
    status: 'pending', human_touched: false, structural_eligible: true, structural_limitations: [],
    context_text: LITERAL_CONTEXT, context_text_source: 'Independent authored navigation occurrence',
    context_sha256: 'd'.repeat(64), structure_path: kind === 'link-name' ? 'root/K/link' : null,
    element: kind === 'link-name' ? '91:0' : null, references: [], navigation_context});
  const destination = {kind: 'uri', uri: 'https://example.invalid/source'};
  saved.decisions.push(
    row('annotation:1:0:name', 'annotation-name', 1, 'Existing annotation description',
      context('annotation', {annotation_index: 0, source_name: 'Existing annotation description', source_target: destination})),
    row('link:91:0:name', 'link-name', 1, 'Existing alternative name', context('link-structure', {
      annotation_index: 0, source_name: 'Existing alternative name', source_target: destination,
      linked_structure: {element: '91:0', path: 'root/K/link', alt: 'Existing alternative name'}})),
    row('annotation:1:0:target', 'link-target', 1, JSON.stringify(destination), context('annotation', {
      annotation_index: 0, source_target: destination})),
    row('annotation:2:0:name', 'annotation-name', 2, 'Second-page description', context('annotation', {
      annotation_index: 0, source_name: 'Second-page description', source_target: {kind: 'page', page: 1}})),
    row('bookmark:0:entry', 'bookmark-entry', null, '{"target":{"kind":"page","page":1},"title":"Original chapter"}',
      context('bookmark', {bookmark_index: 0, source_name: 'Original chapter', source_target: {kind: 'page', page: 1}})),
    row('bookmarks:additions', 'bookmark-additions', null, '{"entries":[]}', context('bookmark-additions')),
  );
  return saved;
}
async function showNavigation(result, checked = true) {
  result.getNode('show-navigation').checked = checked;
  await result.dispatch('show-navigation', 'change');
}
function navigationName(card) { return descendants(card).find(node => node.tagName === 'TEXTAREA'); }
function navigationTargets(card) {
  const fields = descendants(card).filter(node => ['INPUT', 'SELECT'].includes(node.tagName));
  return {mode: fields.find(node => node.tagName === 'SELECT'),
    page: fields.find(node => /destination page/.test(node.getAttribute('aria-label') || '')),
    uri: fields.find(node => /web address/.test(node.getAttribute('aria-label') || ''))};
}
function newBookmarkRows(card) { return descendants(card).filter(node => node.tagName === 'FIELDSET'); }
function newBookmarkFields(row) { return descendants(row).filter(node => ['INPUT', 'TEXTAREA'].includes(node.tagName)); }
async function fillNavigationDraft(result, id) {
  const card = cardFor(result, id);
  if (id === 'annotation:1:0:name') { navigationName(card).value = 'Department contact'; return 'Department contact'; }
  if (id === 'link:91:0:name') { navigationName(card).value = 'Study details'; return 'Study details'; }
  if (id === 'annotation:1:0:target') {
    const fields = navigationTargets(card); fields.mode.value = 'page'; await result.dispatch(fields.mode, 'change'); fields.page.value = '2';
    return '{"kind":"page","page":2}';
  }
  if (id === 'bookmark:0:entry') {
    descendants(card).find(node => ['INPUT', 'TEXTAREA'].includes(node.tagName) && / title /.test(node.getAttribute('aria-label') || '')).value = 'Updated chapter';
    navigationTargets(card).page.value = '2'; return '{"target":{"kind":"page","page":2},"title":"Updated chapter"}';
  }
  await result.dispatch(buttonNamed(card, 'Add new bookmark'), 'click');
  let fields = newBookmarkFields(newBookmarkRows(card)[0]); fields[0].value = 'Overview'; fields[1].value = '1'; fields[2].value = '1';
  await result.dispatch(buttonNamed(card, 'Add new bookmark'), 'click');
  fields = newBookmarkFields(newBookmarkRows(card)[1]); fields[0].value = 'Details'; fields[1].value = '2'; fields[2].value = '2';
  return '{"entries":[{"level":1,"page":1,"title":"Overview"},{"level":2,"page":2,"title":"Details"}]}';
}

test('DOM navigation: controls are opt-in, page-local names stay separate and bookmarks remain document-wide', async () => {
  const saved = navigationFixture(), before = JSON.stringify(saved), result = await bootSavedReview(saved);
  await openSavedReview(result); assert.deepEqual(decisionCards(result).map(card => card.dataset.decisionId), ['title-control', 'language-control']);
  await showNavigation(result);
  assert.deepEqual(decisionCards(result).map(card => card.dataset.decisionId), ['title-control', 'language-control',
    'annotation:1:0:name', 'link:91:0:name', 'annotation:1:0:target', 'bookmark:0:entry', 'bookmarks:additions']);
  assert.equal(navigationName(cardFor(result, 'annotation:1:0:name')).value, 'Existing annotation description');
  assert.equal(navigationName(cardFor(result, 'link:91:0:name')).value, 'Existing alternative name');
  assert.match(descendants(cardFor(result, 'annotation:1:0:name')).map(node => node.textContent).join(' '), /description.*alternative name is a separate decision/);
  assert.match(descendants(cardFor(result, 'link:91:0:name')).map(node => node.textContent).join(' '), /alternative name.*annotation description is a separate decision/);
  assert.equal(result.getNode('show-structure').checked, false);
  await result.dispatch('next-page', 'click');
  assert.deepEqual(decisionCards(result).map(card => card.dataset.decisionId), ['title-control', 'language-control', 'annotation:2:0:name', 'bookmark:0:entry', 'bookmarks:additions']);
  await showNavigation(result, false); assert.deepEqual(decisionCards(result).map(card => card.dataset.decisionId), ['title-control', 'language-control']);
  assertSavedSnapshotUnchanged(result, saved, before); expectOnlyMutations(result, []);
});

test('DOM navigation: source names and target text render literally with no external anchors or network reads', async () => {
  const saved = navigationFixture(), name = saved.decisions.find(item => item.kind === 'annotation-name');
  name.current = name.value = LITERAL_CONTEXT; name.navigation_context.source_name = LITERAL_CONTEXT;
  name.navigation_context.source_target = {kind: 'uri', uri: 'https://example.invalid/' + LITERAL_CONTEXT};
  const result = await bootSavedReview(saved); await openSavedReview(result); await showNavigation(result);
  const card = cardFor(result, name.id); assert.equal(navigationName(card).value, LITERAL_CONTEXT);
  assert.equal(descendants(card).filter(node => ['A', 'IMG', 'SCRIPT'].includes(node.tagName)).length, 0);
  assert(descendants(card).some(node => node.textContent.includes('https://example.invalid/' + LITERAL_CONTEXT)));
  assert(result.requests.every(request => !request.url.startsWith('https:'))); expectOnlyMutations(result, []);
});

for (const id of ['annotation:1:0:name', 'link:91:0:name', 'annotation:1:0:target', 'bookmark:0:entry', 'bookmarks:additions']) {
  test('DOM navigation: Save records only the exact pending draft for ' + id, async () => {
    const saved = navigationFixture(), before = JSON.stringify(saved), url = '/api/workspaces/' + saved.workspace_id + '/edit';
    const values = {'annotation:1:0:name': 'Department contact', 'link:91:0:name': 'Study details', 'annotation:1:0:target': '{"kind":"page","page":2}',
      'bookmark:0:entry': '{"target":{"kind":"page","page":2},"title":"Updated chapter"}',
      'bookmarks:additions': '{"entries":[{"level":1,"page":1,"title":"Overview"},{"level":2,"page":2,"title":"Details"}]}'};
    const value = values[id], payload = {revision: 7, id, value}, response = editedView(saved, id, value);
    const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response}]});
    await openSavedReview(result); await showNavigation(result); assert.equal(await fillNavigationDraft(result, id), value);
    const save = buttonNamed(cardFor(result, id), 'Save edit'); save.focus(); await result.dispatch(save, 'click');
    assertFreshFocus(result, buttonNamed(cardFor(result, id), 'Save edit'), save);
    assert.equal(result.getNode('apply').disabled, true); assert.equal(response.decisions.find(item => item.id === id).status, 'pending');
    assertSavedSnapshotUnchanged(result, saved, before); expectOnlyMutations(result, [{url, payload}]);
  });
  test('DOM navigation: named acceptance saves then approves the new revision for ' + id, async () => {
    const saved = navigationFixture(), url = '/api/workspaces/' + saved.workspace_id;
    const values = {'annotation:1:0:name': 'Department contact', 'link:91:0:name': 'Study details', 'annotation:1:0:target': '{"kind":"page","page":2}',
      'bookmark:0:entry': '{"target":{"kind":"page","page":2},"title":"Updated chapter"}',
      'bookmarks:additions': '{"entries":[{"level":1,"page":1,"title":"Overview"},{"level":2,"page":2,"title":"Details"}]}'};
    const value = values[id], edited = editedView(saved, id, value), accepted = structuredClone(edited); accepted.revision = 9;
    Object.assign(accepted.decisions.find(item => item.id === id), {status: 'approved', approved_by: 'Authored navigation reviewer'});
    const expected = [{url: url + '/edit', payload: {revision: 7, id, value}, response: edited},
      {url: url + '/approve', payload: {revision: 8, id, reviewer: 'Authored navigation reviewer'}, response: accepted}];
    const result = await bootSavedReview(saved, {expectedMutations: expected});
    await openSavedReview(result); await showNavigation(result); result.getNode('reviewer').value = ' Authored navigation reviewer '; await fillNavigationDraft(result, id);
    const accept = buttonNamed(cardFor(result, id), 'Accept this value'); accept.focus(); await result.dispatch(accept, 'click');
    assertFreshFocus(result, buttonNamed(cardFor(result, id), 'Accept this value'), accept); assert.equal(result.getNode('apply').disabled, false);
    expectOnlyMutations(result, expected.map(({url, payload}) => ({url, payload})));
  });
  test('DOM navigation: unnamed acceptance refuses before saving ' + id, async () => {
    const saved = navigationFixture(), result = await bootSavedReview(saved); await openSavedReview(result); await showNavigation(result); await fillNavigationDraft(result, id);
    await result.dispatch(buttonNamed(cardFor(result, id), 'Accept this value'), 'click');
    assert.match(result.getNode('notice').textContent, /Enter your name/); expectOnlyMutations(result, []);
  });
}

for (const defect of ['unsafe', 'stale', 'missing-context', 'wrong-policy', 'wrong-page-count', 'wrong-scope', 'missing-limits']) {
  test('DOM navigation: ' + defect + ' capability refuses mutation without losing source evidence', async () => {
    const saved = navigationFixture(), item = saved.decisions.find(item => item.id === 'annotation:1:0:name');
    if (defect === 'unsafe') { item.structural_eligible = false; item.structural_limitations = ['This annotation is shared.']; }
    else if (defect === 'stale') saved.stale = true;
    else if (defect === 'missing-context') delete item.navigation_context;
    else if (defect === 'wrong-policy') item.navigation_context.policy = 'unrecognized-authority';
    else if (defect === 'wrong-page-count') item.navigation_context.page_count = 3;
    else if (defect === 'wrong-scope') item.navigation_context.scope = 'bookmark';
    else delete item.navigation_context.limits;
    const result = await bootSavedReview(saved); await openSavedReview(result); await showNavigation(result); const card = cardFor(result, item.id);
    assert.equal(navigationName(card).value, item.value); assert(navigationName(card).disabled);
    for (const label of ['Save edit', 'Accept this value']) { const control = buttonNamed(card, label); assert(control.disabled); await result.dispatch(control, 'click'); }
    expectOnlyMutations(result, []);
  });
}

for (const id of ['annotation:1:0:name', 'link:91:0:name']) {
  test('DOM navigation: clearing an existing name is refused for ' + id, async () => {
    const saved = navigationFixture(), result = await bootSavedReview(saved); await openSavedReview(result); await showNavigation(result);
    navigationName(cardFor(result, id)).value = ' '; await result.dispatch(buttonNamed(cardFor(result, id), 'Save edit'), 'click');
    assert.match(result.getNode('notice').textContent, /meaningful nonblank name/); expectOnlyMutations(result, []);
  });
}

test('DOM navigation: target type is explicit and an address save never fetches the address', async () => {
  const saved = navigationFixture(), id = 'annotation:1:0:target', value = '{"kind":"uri","uri":"https://example.invalid/reviewed"}';
  const url = '/api/workspaces/' + saved.workspace_id + '/edit', payload = {revision: 7, id, value};
  const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: editedView(saved, id, value)}]});
  await openSavedReview(result); await showNavigation(result); const fields = navigationTargets(cardFor(result, id));
  assert.equal(fields.mode.value, 'uri'); assert(fields.page.readOnly); assert.equal(fields.uri.readOnly, false);
  fields.uri.value = 'https://example.invalid/reviewed'; await result.dispatch(buttonNamed(cardFor(result, id), 'Save edit'), 'click');
  assert(result.requests.every(request => request.url.startsWith('/api/'))); expectOnlyMutations(result, [{url, payload}]);
});

for (const page of ['', '0', '3', '1.5', 'Infinity']) {
  test('DOM navigation: invalid internal destination refuses before saving ' + JSON.stringify(page), async () => {
    const saved = navigationFixture(), result = await bootSavedReview(saved); await openSavedReview(result); await showNavigation(result);
    const card = cardFor(result, 'annotation:1:0:target'), fields = navigationTargets(card); fields.mode.value = 'page'; await result.dispatch(fields.mode, 'change'); fields.page.value = page;
    await result.dispatch(buttonNamed(card, 'Save edit'), 'click'); assert.match(result.getNode('notice').textContent, /destination page within this document/); expectOnlyMutations(result, []);
  });
}

test('DOM navigation: new bookmark rows move and remove only the unsaved appended forest', async () => {
  const saved = navigationFixture(), result = await bootSavedReview(saved); await openSavedReview(result); await showNavigation(result); await fillNavigationDraft(result, 'bookmarks:additions');
  const card = cardFor(result, 'bookmarks:additions'), existing = cardFor(result, 'bookmark:0:entry');
  await result.dispatch(buttonNamed(card, 'Move new bookmark 2 up'), 'click');
  assert.deepEqual(newBookmarkRows(card).map(row => newBookmarkFields(row)[0].value), ['Details', 'Overview']);
  await result.dispatch(buttonNamed(card, 'Move new bookmark 1 down'), 'click');
  assert.deepEqual(newBookmarkRows(card).map(row => newBookmarkFields(row)[0].value), ['Overview', 'Details']);
  await result.dispatch(buttonNamed(card, 'Remove new bookmark 1'), 'click');
  assert.deepEqual(newBookmarkRows(card).map(row => newBookmarkFields(row)[0].value), ['Details']);
  assert.equal(bookmarkTitleField(existing).value, 'Original chapter');
  assert.equal(descendants(existing).some(node => node.tagName === 'BUTTON' && /Move|Remove/.test(node.textContent)), false); expectOnlyMutations(result, []);
});

for (const defect of ['blank-title', 'bad-page', 'first-level', 'skipped-level', 'too-deep']) {
  test('DOM navigation: invalid bookmark forest is refused before saving ' + defect, async () => {
    const saved = navigationFixture(), result = await bootSavedReview(saved); await openSavedReview(result); await showNavigation(result); await fillNavigationDraft(result, 'bookmarks:additions');
    const card = cardFor(result, 'bookmarks:additions'), first = newBookmarkFields(newBookmarkRows(card)[0]), second = newBookmarkFields(newBookmarkRows(card)[1]);
    if (defect === 'blank-title') first[0].value = ' ';
    else if (defect === 'bad-page') second[1].value = '3';
    else if (defect === 'first-level') first[2].value = '2';
    else second[2].value = defect === 'skipped-level' ? '3' : '11';
    await result.dispatch(buttonNamed(card, 'Save edit'), 'click');
    assert.match(result.getNode('notice').textContent, /nonblank title|destination page|Start bookmarks/); expectOnlyMutations(result, []);
  });
}

for (const navigation of ['next-page', 'page-away-and-back', 'collapse-and-reopen', 'tab-away-and-back']) {
  test('DOM navigation: delayed Save leaves only a draft after ' + navigation, async () => {
    const saved = navigationFixture(), delayed = deferredResponse(), id = 'annotation:1:0:name', value = 'Department contact';
    const url = '/api/workspaces/' + saved.workspace_id + '/edit', payload = {revision: 7, id, value};
    const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: delayed.promise}]});
    await openSavedReview(result); await showNavigation(result); result.getNode('reviewer').value = 'Authored delayed navigation reviewer'; await fillNavigationDraft(result, id);
    const accepting = result.dispatch(buttonNamed(cardFor(result, id), 'Accept this value'), 'click'); await settle();
    if (navigation === 'next-page' || navigation === 'page-away-and-back') { await result.dispatch('next-page', 'click'); if (navigation === 'page-away-and-back') await result.dispatch('previous-page', 'click'); }
    else if (navigation === 'collapse-and-reopen') { await showNavigation(result, false); await showNavigation(result, true); }
    else { await result.dispatch('tab-checks', 'click'); await result.dispatch('tab-decisions', 'click'); }
    delayed.resolve(editedView(saved, id, value)); await accepting;
    assert.equal(result.getNode('apply').disabled, true); assert.match(result.getNode('notice').textContent, /Navigation draft saved/); expectOnlyMutations(result, [{url, payload}]);
  });
}

for (const returnToA of [false, true]) {
  test('DOM navigation: delayed acceptance cannot cross workspace ' + (returnToA ? 'A to B to A' : 'A to B'), async () => {
    const first = navigationFixture(), second = navigationFixture(), delayed = deferredResponse();
    first.source.path = '/authored/workspace-A.pdf'; second.source.path = '/authored/workspace-B.pdf'; second.workspace_id = 'f'.repeat(24);
    const id = 'annotation:1:0:name', value = 'Department contact', url = '/api/workspaces/' + first.workspace_id + '/edit', payload = {revision: 7, id, value};
    const result = await bootNavigation(first, second, {expectedMutations: [{url, payload, response: delayed.promise}]});
    await openNamedWorkspace(result, 'workspace-A.pdf'); await showNavigation(result); result.getNode('reviewer').value = 'Authored workspace navigation reviewer'; await fillNavigationDraft(result, id);
    const accepting = result.dispatch(buttonNamed(cardFor(result, id), 'Accept this value'), 'click'); await settle(); await result.dispatch('back', 'click'); await openNamedWorkspace(result, 'workspace-B.pdf');
    if (returnToA) { await result.dispatch('back', 'click'); await openNamedWorkspace(result, 'workspace-A.pdf'); }
    delayed.resolve(editedView(first, id, value)); await accepting; assertVisibleWorkspace(result, returnToA ? 'workspace-A.pdf' : 'workspace-B.pdf', 'en-US');
    assert.equal(navigationName(cardFor(result, id)).value, 'Existing annotation description'); expectOnlyMutations(result, [{url, payload}]);
  });
}

test('DOM navigation: a newer dynamic bookmark forest survives an unrelated delayed response without being saved', async () => {
  const saved = navigationFixture(), delayed = deferredResponse(), id = 'title-control', value = 'Revised title', url = '/api/workspaces/' + saved.workspace_id + '/edit';
  const payload = {revision: 7, id, value}, result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: delayed.promise}]});
  await openSavedReview(result); await showNavigation(result); descendants(cardFor(result, id)).find(node => node.tagName === 'TEXTAREA').value = value;
  const saving = result.dispatch(buttonNamed(cardFor(result, id), 'Save edit'), 'click'); await settle(); await fillNavigationDraft(result, 'bookmarks:additions');
  const field = newBookmarkFields(newBookmarkRows(cardFor(result, 'bookmarks:additions'))[1])[0]; field.value = 'Newer detail'; field.focus(); field.setSelectionRange(1, 5, 'forward');
  delayed.resolve(editedView(saved, id, value)); await saving;
  const current = newBookmarkRows(cardFor(result, 'bookmarks:additions')); assert.equal(current.length, 2);
  assert.deepEqual(current.map(row => newBookmarkFields(row).map(field => field.value)), [['Overview', '1', '1'], ['Newer detail', '2', '2']]);
  const restored = newBookmarkFields(current[1])[0]; assertFreshFocus(result, restored, field); assert.equal(restored.selectionStart, 1); assert.equal(restored.selectionEnd, 5); expectOnlyMutations(result, [{url, payload}]);
});

test('DOM navigation: changing a bookmark forest during its delayed acceptance saves only the earlier draft', async () => {
  const saved = navigationFixture(), delayed = deferredResponse(), id = 'bookmarks:additions';
  const value = '{"entries":[{"level":1,"page":1,"title":"Overview"},{"level":2,"page":2,"title":"Details"}]}', url = '/api/workspaces/' + saved.workspace_id + '/edit';
  const payload = {revision: 7, id, value}, result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: delayed.promise}]});
  await openSavedReview(result); await showNavigation(result); result.getNode('reviewer').value = 'Authored bookmark reviewer'; await fillNavigationDraft(result, id);
  const accepting = result.dispatch(buttonNamed(cardFor(result, id), 'Accept this value'), 'click'); await settle();
  await result.dispatch(buttonNamed(cardFor(result, id), 'Add new bookmark'), 'click'); const field = newBookmarkFields(newBookmarkRows(cardFor(result, id))[2])[0]; field.value = 'Unsaved third entry'; field.focus();
  delayed.resolve(editedView(saved, id, value)); await accepting;
  assert.equal(newBookmarkRows(cardFor(result, id)).length, 3); assert.equal(newBookmarkFields(newBookmarkRows(cardFor(result, id))[2])[0].value, 'Unsaved third entry');
  assert.equal(result.getNode('apply').disabled, true); assert.match(result.getNode('notice').textContent, /Current fields still need saving and acceptance/); expectOnlyMutations(result, [{url, payload}]);
});

test('DOM navigation: active work keeps all navigation fields and row buttons disabled after rebuilding', async () => {
  const saved = navigationFixture(), url = '/api/workspaces/' + saved.workspace_id + '/auto-fix', payload = {revision: 7, consent: true, use_ai: false, ai_consent: false, endpoint: '', model: '', include_images: false, reasoning_effort: null};
  const result = await bootSavedReview(saved, {captureTimers: true, expectedMutations: [{url, payload, response: {job_id: 'authored-navigation-job'}}]});
  await openSavedReview(result); await showNavigation(result); await result.dispatch('auto-fix', 'click');
  await result.dispatch('next-page', 'click');
  for (const id of ['annotation:2:0:name', 'bookmark:0:entry', 'bookmarks:additions']) {
    const card = cardFor(result, id); assert(descendants(card).filter(node => ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(node.tagName)).every(node => node.disabled));
  }
  assert.equal(result.getNode('show-navigation').disabled, true); assert.deepEqual(result.mutationRequests, [{url, payload}]); assert.deepEqual(result.unexpectedRequests, []);
});

for (const sourceTarget of [{kind: 'none'}, {detail: 'The saved named destination is missing.', kind: 'unresolved'}]) {
  for (const id of ['annotation:1:0:target', 'bookmark:0:entry']) {
    test('DOM navigation: explicit page repair remains available for ' + sourceTarget.kind + ' source on ' + id, async () => {
      const saved = navigationFixture(), item = saved.decisions.find(item => item.id === id), bookmark = item.kind === 'bookmark-entry';
      item.current = item.value = bookmark ? JSON.stringify({target: sourceTarget, title: 'Original chapter'}) : JSON.stringify(sourceTarget);
      item.navigation_context.source_target = structuredClone(sourceTarget);
      const value = bookmark ? '{"target":{"kind":"page","page":2},"title":"Original chapter"}' : '{"kind":"page","page":2}';
      const url = '/api/workspaces/' + saved.workspace_id + '/edit', payload = {revision: 7, id, value};
      const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: editedView(saved, id, value)}]});
      await openSavedReview(result); await showNavigation(result); const card = cardFor(result, id), fields = navigationTargets(card);
      assert.equal(fields.mode.value, 'keep'); assert.equal(fields.mode.disabled, false); assert(fields.page.readOnly && fields.uri.readOnly);
      assert(descendants(card).some(node => node.textContent.includes('missing or unresolved')));
      fields.mode.value = 'page'; await result.dispatch(fields.mode, 'change'); fields.page.value = '2';
      await result.dispatch(buttonNamed(card, 'Save edit'), 'click');
      assert.equal(navigationTargets(cardFor(result, id)).mode.value, 'page'); assert.equal(result.getNode('apply').disabled, true); expectOnlyMutations(result, [{url, payload}]);
    });
  }
}

for (const id of ['annotation:1:0:name', 'link:91:0:name', 'bookmark:0:entry']) {
  test('DOM navigation: a missing source name is explicitly repairable on ' + id, async () => {
    const saved = navigationFixture(), item = saved.decisions.find(item => item.id === id), bookmark = item.kind === 'bookmark-entry';
    item.current = item.value = bookmark ? '{"target":{"kind":"page","page":1},"title":""}' : '';
    item.navigation_context.source_name = ''; if (item.navigation_context.linked_structure) item.navigation_context.linked_structure.alt = '';
    const value = bookmark ? '{"target":{"kind":"page","page":1},"title":"Useful chapter name"}' : 'Useful accessible name';
    const url = '/api/workspaces/' + saved.workspace_id + '/edit', payload = {revision: 7, id, value};
    const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: editedView(saved, id, value)}]});
    await openSavedReview(result); await showNavigation(result); const card = cardFor(result, id);
    const field = bookmark ? descendants(card).find(node => ['INPUT', 'TEXTAREA'].includes(node.tagName) && / title /.test(node.getAttribute('aria-label') || '')) : navigationName(card);
    assert.equal(field.value, ''); assert.equal(field.disabled, false); field.value = bookmark ? 'Useful chapter name' : value;
    await result.dispatch(buttonNamed(card, 'Save edit'), 'click'); expectOnlyMutations(result, [{url, payload}]);
  });
}

test('DOM navigation: a source destination mismatch disables target editing instead of trusting a detached capability', async () => {
  const saved = navigationFixture(), item = saved.decisions.find(item => item.kind === 'link-target');
  item.navigation_context.source_target = {kind: 'page', page: 2};
  const result = await bootSavedReview(saved); await openSavedReview(result); await showNavigation(result); const card = cardFor(result, item.id);
  assert(navigationTargets(card).mode.disabled); assert(buttonNamed(card, 'Save edit').disabled); expectOnlyMutations(result, []);
});

test('DOM navigation: active or unsupported source actions stay read-only even if the response claims eligibility', async () => {
  const saved = navigationFixture(), item = saved.decisions.find(item => item.kind === 'link-target'), target = {detail: 'An additional action is present.', kind: 'unsupported'};
  item.current = item.value = JSON.stringify(target); item.navigation_context.source_target = target;
  const result = await bootSavedReview(saved); await openSavedReview(result); await showNavigation(result); const card = cardFor(result, item.id);
  assert(navigationTargets(card).mode.disabled); assert(buttonNamed(card, 'Accept this value').disabled); expectOnlyMutations(result, []);
});

test('DOM navigation: Keep original restores a supported original target without inventing destination details', async () => {
  const saved = navigationFixture(), item = saved.decisions.find(item => item.kind === 'link-target'), id = item.id;
  item.value = '{"kind":"page","page":2}'; saved.unapplied_decisions = [id];
  const value = '{"kind":"uri","uri":"https://example.invalid/source"}', url = '/api/workspaces/' + saved.workspace_id + '/edit', payload = {revision: 7, id, value};
  const response = editedView(saved, id, value), result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response}]});
  await openSavedReview(result); await showNavigation(result); const card = cardFor(result, id), fields = navigationTargets(card);
  assert.equal(fields.mode.value, 'page'); fields.mode.value = 'keep'; await result.dispatch(fields.mode, 'change');
  await result.dispatch(buttonNamed(card, 'Save edit'), 'click'); expectOnlyMutations(result, [{url, payload}]);
});

for (const sourceTarget of [{kind: 'none'}, {detail: 'The saved named destination is missing.', kind: 'unresolved'}]) {
  for (const id of ['annotation:1:0:target', 'bookmark:0:entry']) {
    test('DOM navigation: Keep original withdraws a repaired draft without claiming a repair for ' + sourceTarget.kind + ' on ' + id, async () => {
      const saved = navigationFixture(), item = saved.decisions.find(item => item.id === id), bookmark = item.kind === 'bookmark-entry';
      item.current = bookmark ? JSON.stringify({target: sourceTarget, title: 'Original chapter'}) : JSON.stringify(sourceTarget);
      item.value = bookmark ? '{"target":{"kind":"page","page":2},"title":"Original chapter"}' : '{"kind":"page","page":2}';
      item.navigation_context.source_target = structuredClone(sourceTarget); saved.unapplied_decisions = [id];
      const value = item.current, url = '/api/workspaces/' + saved.workspace_id + '/edit', payload = {revision: 7, id, value}, response = editedView(saved, id, value);
      response.unapplied_decisions = [];
      const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response}]});
      await openSavedReview(result); await showNavigation(result); const card = cardFor(result, id), fields = navigationTargets(card);
      assert.equal(fields.mode.value, 'page'); fields.mode.value = 'keep'; await result.dispatch(fields.mode, 'change');
      await result.dispatch(buttonNamed(card, 'Save edit'), 'click'); assert.equal(navigationTargets(cardFor(result, id)).mode.value, 'keep');
      assert.equal(result.getNode('apply').disabled, true); assert(descendants(cardFor(result, id)).some(node => node.textContent.includes('preserves the problem'))); expectOnlyMutations(result, [{url, payload}]);
    });
  }
}

test('DOM navigation: a changed bookmark title requires a repaired destination while its exact blank original can be restored', async () => {
  const saved = navigationFixture(), item = saved.decisions.find(item => item.kind === 'bookmark-entry'), target = {kind: 'none'};
  item.current = item.value = '{"target":{"kind":"none"},"title":""}'; item.navigation_context.source_target = target; item.navigation_context.source_name = '';
  const result = await bootSavedReview(saved); await openSavedReview(result); await showNavigation(result); const card = cardFor(result, item.id);
  const field = descendants(card).find(node => ['INPUT', 'TEXTAREA'].includes(node.tagName) && / title /.test(node.getAttribute('aria-label') || ''));
  field.value = 'New name'; await result.dispatch(buttonNamed(card, 'Save edit'), 'click'); assert.match(result.getNode('notice').textContent, /when changing an existing bookmark/); expectOnlyMutations(result, []);
});

test('DOM navigation: withdrawing a saved bookmark repair can restore its exact blank-title original', async () => {
  const saved = navigationFixture(), item = saved.decisions.find(item => item.kind === 'bookmark-entry'), id = item.id;
  item.current = '{"target":{"kind":"none"},"title":""}'; item.value = '{"target":{"kind":"page","page":2},"title":"Reviewed name"}';
  item.navigation_context.source_target = {kind: 'none'}; item.navigation_context.source_name = ''; saved.unapplied_decisions = [id];
  const value = item.current, url = '/api/workspaces/' + saved.workspace_id + '/edit', payload = {revision: 7, id, value}, response = editedView(saved, id, value); response.unapplied_decisions = [];
  const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response}]});
  await openSavedReview(result); await showNavigation(result); const card = cardFor(result, id);
  descendants(card).find(node => ['INPUT', 'TEXTAREA'].includes(node.tagName) && / title /.test(node.getAttribute('aria-label') || '')).value = '';
  const fields = navigationTargets(card); fields.mode.value = 'keep'; await result.dispatch(fields.mode, 'change');
  await result.dispatch(buttonNamed(card, 'Save edit'), 'click'); assert.equal(result.getNode('apply').disabled, true); expectOnlyMutations(result, [{url, payload}]);
});

function bookmarkTitleField(card) { return descendants(card).find(node => ['INPUT', 'TEXTAREA'].includes(node.tagName) && / title /.test(node.getAttribute('aria-label') || '')); }
function bookmarkRawRows(result) { return newBookmarkRows(cardFor(result, 'bookmarks:additions')).map(row => newBookmarkFields(row).map(field => field.value)); }

test('DOM navigation: partial unsaved bookmark plans and entry fields survive repeated preview page changes without a save', async () => {
  const saved = navigationFixture(), before = JSON.stringify(saved), result = await bootSavedReview(saved);
  await openSavedReview(result); await showNavigation(result); await fillNavigationDraft(result, 'bookmarks:additions');
  const initial = newBookmarkRows(cardFor(result, 'bookmarks:additions'));
  newBookmarkFields(initial[0])[1].value = ''; newBookmarkFields(initial[1])[2].value = '';
  bookmarkTitleField(cardFor(result, 'bookmark:0:entry')).value = 'Unfinished renamed chapter';
  const expected = [['Overview', '', '1'], ['Details', '2', '']];
  for (const pageAction of ['next-page', 'previous-page', 'next-page', 'previous-page']) {
    await result.dispatch(pageAction, 'click'); assert.deepEqual(bookmarkRawRows(result), expected);
    assert.equal(bookmarkTitleField(cardFor(result, 'bookmark:0:entry')).value, 'Unfinished renamed chapter');
  }
  assert.equal(result.getNode('apply').disabled, true); assertSavedSnapshotUnchanged(result, saved, before); expectOnlyMutations(result, []);
});

test('DOM navigation: partial bookmark rows survive collapse and reopen while their fields remain local drafts', async () => {
  const saved = navigationFixture(), before = JSON.stringify(saved), result = await bootSavedReview(saved);
  await openSavedReview(result); await showNavigation(result); await fillNavigationDraft(result, 'bookmarks:additions');
  const card = cardFor(result, 'bookmarks:additions'); newBookmarkFields(newBookmarkRows(card)[1])[0].value = '';
  const target = navigationTargets(cardFor(result, 'bookmark:0:entry')); target.mode.value = 'uri'; await result.dispatch(target.mode, 'change'); target.uri.value = 'https://example.invalid/unfinished';
  for (let index = 0; index < 2; index++) {
    await showNavigation(result, false); assert.equal(decisionCards(result).some(card => card.dataset.decisionId === 'bookmarks:additions'), false);
    await showNavigation(result, true); assert.deepEqual(bookmarkRawRows(result), [['Overview', '1', '1'], ['', '2', '2']]);
    const restored = navigationTargets(cardFor(result, 'bookmark:0:entry')); assert.equal(restored.mode.value, 'uri'); assert.equal(restored.uri.value, 'https://example.invalid/unfinished'); assert.equal(restored.uri.readOnly, false);
  }
  assertSavedSnapshotUnchanged(result, saved, before); expectOnlyMutations(result, []);
});

test('DOM navigation: an unrelated delayed response preserves partial bookmark plans even when focus is outside the card', async () => {
  const saved = navigationFixture(), delayed = deferredResponse(), id = 'title-control', value = 'Updated document title', url = '/api/workspaces/' + saved.workspace_id + '/edit';
  const payload = {revision: 7, id, value}, result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: delayed.promise}]});
  await openSavedReview(result); await showNavigation(result); descendants(cardFor(result, id)).find(node => node.tagName === 'TEXTAREA').value = value;
  const saving = result.dispatch(buttonNamed(cardFor(result, id), 'Save edit'), 'click'); await settle(); await fillNavigationDraft(result, 'bookmarks:additions');
  newBookmarkFields(newBookmarkRows(cardFor(result, 'bookmarks:additions'))[0])[1].value = ''; result.getNode('page-number').focus();
  delayed.resolve(editedView(saved, id, value)); await saving;
  assert.deepEqual(bookmarkRawRows(result), [['Overview', '', '1'], ['Details', '2', '2']]); expectOnlyMutations(result, [{url, payload}]);
});

for (const change of ['context', 'server-value', 'stale']) {
  test('DOM navigation: a ' + change + ' change discards detached unsaved bookmark fields', async () => {
    const saved = navigationFixture(), delayed = deferredResponse(), id = 'title-control', value = 'Updated document title', url = '/api/workspaces/' + saved.workspace_id + '/edit';
    const payload = {revision: 7, id, value}, response = editedView(saved, id, value);
    const additions = response.decisions.find(item => item.id === 'bookmarks:additions'), entry = response.decisions.find(item => item.id === 'bookmark:0:entry');
    if (change === 'context') { additions.context_sha256 = 'e'.repeat(64); entry.context_sha256 = 'e'.repeat(64); }
    else if (change === 'server-value') { additions.value = '{"entries":[{"level":1,"page":2,"title":"Server-saved bookmark"}]}'; entry.value = '{"target":{"kind":"page","page":1},"title":"Server-saved title"}'; }
    else response.stale = true;
    const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: delayed.promise}]});
    await openSavedReview(result); await showNavigation(result); descendants(cardFor(result, id)).find(node => node.tagName === 'TEXTAREA').value = value;
    const saving = result.dispatch(buttonNamed(cardFor(result, id), 'Save edit'), 'click'); await settle(); await fillNavigationDraft(result, 'bookmarks:additions');
    bookmarkTitleField(cardFor(result, 'bookmark:0:entry')).value = 'Detached local title'; result.getNode('page-number').focus();
    delayed.resolve(response); await saving;
    assert.deepEqual(bookmarkRawRows(result), change === 'server-value' ? [['Server-saved bookmark', '2', '1']] : []);
    assert.equal(bookmarkTitleField(cardFor(result, 'bookmark:0:entry')).value, change === 'server-value' ? 'Server-saved title' : 'Original chapter');
    if (change === 'stale') assert(buttonNamed(cardFor(result, 'bookmarks:additions'), 'Add new bookmark').disabled);
    expectOnlyMutations(result, [{url, payload}]);
  });
}

for (const returnToA of [false, true]) {
  test('DOM navigation: unsaved bookmark fields are discarded across workspace ' + (returnToA ? 'A to B to A' : 'A to B'), async () => {
    const first = navigationFixture(), second = navigationFixture(); first.source.path = '/authored/workspace-A.pdf'; second.source.path = '/authored/workspace-B.pdf'; second.workspace_id = 'f'.repeat(24);
    const result = await bootNavigation(first, second); await openNamedWorkspace(result, 'workspace-A.pdf'); await showNavigation(result); await fillNavigationDraft(result, 'bookmarks:additions');
    bookmarkTitleField(cardFor(result, 'bookmark:0:entry')).value = 'Local A draft'; await result.dispatch('back', 'click'); await openNamedWorkspace(result, 'workspace-B.pdf');
    if (returnToA) { await result.dispatch('back', 'click'); await openNamedWorkspace(result, 'workspace-A.pdf'); }
    assert.deepEqual(bookmarkRawRows(result), []); assert.equal(bookmarkTitleField(cardFor(result, 'bookmark:0:entry')).value, 'Original chapter'); expectOnlyMutations(result, []);
  });
}

for (const change of ['context', 'server-value']) {
  for (const focusedId of ['bookmark:0:entry', 'bookmarks:additions']) {
    test('DOM navigation: focused ' + focusedId + ' draft cannot bypass a changed ' + change + ' binding', async () => {
      const saved = navigationFixture(), delayed = deferredResponse(), id = 'title-control', value = 'Updated document title';
      const url = '/api/workspaces/' + saved.workspace_id + '/edit', payload = {revision: 7, id, value}, response = editedView(saved, id, value);
      const changed = response.decisions.find(item => item.id === focusedId);
      if (change === 'context') changed.context_sha256 = 'f'.repeat(64);
      else changed.value = focusedId === 'bookmarks:additions' ? '{"entries":[{"level":1,"page":2,"title":"Server-saved bookmark"}]}' : '{"target":{"kind":"page","page":1},"title":"Server-saved title"}';
      const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: delayed.promise}]});
      await openSavedReview(result); await showNavigation(result); descendants(cardFor(result, id)).find(node => node.tagName === 'TEXTAREA').value = value;
      const saving = result.dispatch(buttonNamed(cardFor(result, id), 'Save edit'), 'click'); await settle();
      let field;
      if (focusedId === 'bookmarks:additions') { await fillNavigationDraft(result, focusedId); field = newBookmarkFields(newBookmarkRows(cardFor(result, focusedId))[0])[0]; }
      else field = bookmarkTitleField(cardFor(result, focusedId));
      field.value = 'Detached focused draft'; field.focus(); field.setSelectionRange(2, 8, 'forward');
      delayed.resolve(response); await saving;
      if (focusedId === 'bookmarks:additions') assert.deepEqual(bookmarkRawRows(result), change === 'context' ? [] : [['Server-saved bookmark', '2', '1']]);
      else assert.equal(bookmarkTitleField(cardFor(result, focusedId)).value, change === 'context' ? 'Original chapter' : 'Server-saved title');
      expectOnlyMutations(result, [{url, payload}]);
    });
  }
}

test('DOM navigation: target-only bookmark edits preserve a supported multiline source title exactly', async () => {
  const saved = navigationFixture(), item = saved.decisions.find(item => item.kind === 'bookmark-entry'), id = item.id, title = 'Chapter one\nResearch\tdetails';
  item.current = item.value = JSON.stringify({target: {kind: 'page', page: 1}, title}); item.navigation_context.source_name = title;
  const value = JSON.stringify({target: {kind: 'page', page: 2}, title}), url = '/api/workspaces/' + saved.workspace_id + '/edit', payload = {revision: 7, id, value};
  const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: editedView(saved, id, value)}]});
  await openSavedReview(result); await showNavigation(result); const card = cardFor(result, id), field = bookmarkTitleField(card);
  assert.equal(field.tagName, 'TEXTAREA'); assert.equal(field.value, title); navigationTargets(card).page.value = '2';
  await result.dispatch(buttonNamed(card, 'Save edit'), 'click'); assert.equal(bookmarkTitleField(cardFor(result, id)).value, title); expectOnlyMutations(result, [{url, payload}]);
});

test('DOM navigation: new bookmark title line breaks and tabs survive preview navigation and exact draft serialization', async () => {
  const saved = navigationFixture(), id = 'bookmarks:additions', title = 'Chapter one\nResearch\tdetails', value = JSON.stringify({entries: [{level: 1, page: 2, title}]});
  const url = '/api/workspaces/' + saved.workspace_id + '/edit', payload = {revision: 7, id, value}, result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: editedView(saved, id, value)}]});
  await openSavedReview(result); await showNavigation(result); let card = cardFor(result, id); await result.dispatch(buttonNamed(card, 'Add new bookmark'), 'click');
  const fields = newBookmarkFields(newBookmarkRows(card)[0]); assert.equal(fields[0].tagName, 'TEXTAREA'); fields[0].value = title; fields[1].value = '2'; fields[2].value = '1';
  await result.dispatch('next-page', 'click'); card = cardFor(result, id); assert.equal(newBookmarkFields(newBookmarkRows(card)[0])[0].value, title);
  await result.dispatch(buttonNamed(card, 'Save edit'), 'click'); expectOnlyMutations(result, [{url, payload}]);
});

test('DOM navigation: a known same-bookmark Save transition preserves newer local fields without accepting them', async () => {
  const saved = navigationFixture(), delayed = deferredResponse(), id = 'bookmarks:additions';
  const value = '{"entries":[{"level":1,"page":1,"title":"Overview"},{"level":2,"page":2,"title":"Details"}]}', url = '/api/workspaces/' + saved.workspace_id + '/edit', payload = {revision: 7, id, value};
  const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: delayed.promise}]});
  await openSavedReview(result); await showNavigation(result); await fillNavigationDraft(result, id);
  const saving = result.dispatch(buttonNamed(cardFor(result, id), 'Save edit'), 'click'); await settle();
  const field = newBookmarkFields(newBookmarkRows(cardFor(result, id))[1])[0]; field.value = 'Newer unsaved detail'; field.focus(); field.setSelectionRange(1, 5, 'forward');
  delayed.resolve(editedView(saved, id, value)); await saving;
  const current = newBookmarkFields(newBookmarkRows(cardFor(result, id))[1])[0]; assert.equal(current.value, 'Newer unsaved detail'); assertFreshFocus(result, current, field); assert.equal(current.selectionStart, 1); assert.equal(current.selectionEnd, 5);
  assert.equal(result.getNode('apply').disabled, true); expectOnlyMutations(result, [{url, payload}]);
});

test('DOM navigation: a known bookmark Accept response preserves newer typing as an unaccepted local draft', async () => {
  const saved = navigationFixture(), delayed = deferredResponse(), id = 'bookmark:0:entry', value = '{"target":{"kind":"page","page":2},"title":"Updated chapter"}';
  const prefix = '/api/workspaces/' + saved.workspace_id, edited = editedView(saved, id, value), accepted = structuredClone(edited); accepted.revision = 9;
  Object.assign(accepted.decisions.find(item => item.id === id), {status: 'approved', approved_by: 'Authored bookmark reviewer'});
  const expected = [{url: prefix + '/edit', payload: {revision: 7, id, value}, response: edited},
    {url: prefix + '/approve', payload: {revision: 8, id, reviewer: 'Authored bookmark reviewer'}, response: delayed.promise}];
  const result = await bootSavedReview(saved, {expectedMutations: expected}); await openSavedReview(result); await showNavigation(result); result.getNode('reviewer').value = 'Authored bookmark reviewer'; await fillNavigationDraft(result, id);
  const accepting = result.dispatch(buttonNamed(cardFor(result, id), 'Accept this value'), 'click'); await settle();
  const field = bookmarkTitleField(cardFor(result, id)); field.value = 'Newer unaccepted title'; field.focus(); delayed.resolve(accepted); await accepting;
  assert.equal(bookmarkTitleField(cardFor(result, id)).value, 'Newer unaccepted title');
  assert.equal(accepted.decisions.find(item => item.id === id).value, value); expectOnlyMutations(result, expected.map(({url, payload}) => ({url, payload})));
});

test('DOM navigation: a stale response discards focused raw bookmark rows before any dynamic field restoration', async () => {
  const saved = navigationFixture(), delayed = deferredResponse(), id = 'title-control', value = 'Updated document title', url = '/api/workspaces/' + saved.workspace_id + '/edit';
  const payload = {revision: 7, id, value}, response = editedView(saved, id, value); response.stale = true;
  const result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response: delayed.promise}]});
  await openSavedReview(result); await showNavigation(result); descendants(cardFor(result, id)).find(node => node.tagName === 'TEXTAREA').value = value;
  const saving = result.dispatch(buttonNamed(cardFor(result, id), 'Save edit'), 'click'); await settle(); await fillNavigationDraft(result, 'bookmarks:additions');
  const field = newBookmarkFields(newBookmarkRows(cardFor(result, 'bookmarks:additions'))[0])[0]; field.value = 'Stale focused local draft'; field.focus();
  delayed.resolve(response); await saving;
  assert.deepEqual(bookmarkRawRows(result), []); assert(buttonNamed(cardFor(result, 'bookmarks:additions'), 'Add new bookmark').disabled); expectOnlyMutations(result, [{url, payload}]);
});


// Source-authored semantic tree decisions. No PDF, browser, provider or inferred
// reading order is involved in these DOM/HTTP contract fixtures.
function semanticJSON(value) {
  if (Array.isArray(value)) return '[' + value.map(semanticJSON).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(key => JSON.stringify(key) + ':' + semanticJSON(value[key])).join(',') + '}';
  return JSON.stringify(value);
}
const SEMANTIC_IDS = {role: 'tree:role:10:0', order: 'tree:order:200:0', move: 'tree:move:15:0', list: 'tree:list:200:0'};
function semanticFixture() {
  const saved = repairControlsFixture();
  const node = (element, role, parent, index, children, context_text) => ({element, role, parent, index, children, page: 1, context_text});
  const children = [node('10:0', 'H2', '200:0', 0, [], LITERAL_CONTEXT),
    node('11:0', 'P', '200:0', 1, [], '1.'), node('12:0', 'P', '200:0', 2, [], 'First existing item'),
    node('13:0', 'P', '200:0', 3, [], '2.'), node('14:0', 'P', '200:0', 4, [], 'Second existing item'),
    node('15:0', 'P', '200:0', 5, [], 'An existing closing paragraph')];
  const parent = node('200:0', 'Sect', '100:0', 0, children.map(child => child.element), 'Existing section'),
    destination = node('201:0', 'Sect', '100:0', 1, ['20:0'], 'A different existing section');
  const context = (source, overrides = {}) => ({policy: 'reviewed-semantic-tree-1', page_count: 2,
    source: {element: source.element, role: source.role, parent: source.parent, index: source.index, children: [...source.children]},
    children: source.element === parent.element ? structuredClone(children) : [],
    parent_choices: [], list_candidates: [], numbering_values: ['None','Disc','Circle','Square','Decimal','UpperRoman','LowerRoman','UpperAlpha','LowerAlpha'],
    limits: {children: 100, list_items: 50, move_parents: 100, payload_chars: 100000}, ...overrides});
  const row = (id, kind, current, source, tree_context, extra = {}) => ({id, kind, current, value: current, page: 1,
    element: source.element, structure_path: 'root/K/semantic/' + id, context_sha256: 'c'.repeat(64),
    context_text: source.context_text, context_text_source: 'Authored existing tagged text',
    structural_eligible: true, structural_limitations: [], status: 'pending', human_touched: false,
    references: [{page: 1, stream: 'page', mcid: source.index}], tree_context, ...extra});
  saved.decisions.push(row(SEMANTIC_IDS.role, 'semantic-role', 'H2', children[0], context(children[0]), {allowed_values: ['H2', 'P']}),
    row(SEMANTIC_IDS.order, 'reading-order', semanticJSON({children: parent.children}), parent, context(parent)),
    row(SEMANTIC_IDS.move, 'tree-move', semanticJSON({parent: parent.element, index: 5}), children[5], context(children[5], {parent_choices: [destination]})),
    row(SEMANTIC_IDS.list, 'semantic-list', semanticJSON({items: [], numbering: 'None'}), parent,
      context(parent, {list_candidates: structuredClone(children.slice(1, 5))})));
  return saved;
}
async function showSemantic(result, checked = true) { result.getNode('show-semantic').checked = checked; await result.dispatch('show-semantic', 'change'); }
function semanticOrderRows(card) { return descendants(card).filter(node => node.dataset?.semanticNode); }
function semanticOrderIds(card) { return semanticOrderRows(card).map(node => node.dataset.semanticNode); }
function semanticListRows(card) { return descendants(card).filter(node => node.tagName === 'FIELDSET'); }
function semanticListRaw(result) { return semanticListRows(cardFor(result, SEMANTIC_IDS.list)).map(row => selectsFor(row).map(field => field.value)); }
function semanticMoveFields(card) { return {parent: selectsFor(card)[0], position: descendants(card).find(node => node.tagName === 'INPUT')}; }
const SEMANTIC_DRAFT_VALUES = {
  'semantic-role': 'P',
  'reading-order': semanticJSON({children: ['11:0','10:0','12:0','13:0','14:0','15:0']}),
  'tree-move': semanticJSON({parent: '201:0', index: 1}),
  'semantic-list': semanticJSON({items: [{label: '13:0', body: '14:0'}, {label: '11:0', body: '12:0'}], numbering: 'Decimal'}),
};
async function fillSemanticDraft(result, id) {
  const card = cardFor(result, id);
  if (id === SEMANTIC_IDS.role) selectsFor(card)[0].value = 'P';
  else if (id === SEMANTIC_IDS.order) await result.dispatch(buttonNamed(card, 'Move element 1 down'), 'click');
  else if (id === SEMANTIC_IDS.move) { const fields = semanticMoveFields(card); fields.parent.value = '201:0'; await result.dispatch(fields.parent, 'change'); fields.position.value = '2'; }
  else {
    selectsFor(card)[0].value = 'Decimal';
    await result.dispatch(buttonNamed(card, 'Add list item'), 'click');
    let fields = selectsFor(semanticListRows(card)[0]); fields[0].value = '11:0'; fields[1].value = '12:0';
    await result.dispatch(buttonNamed(card, 'Add list item'), 'click');
    fields = selectsFor(semanticListRows(card)[1]); fields[0].value = '13:0'; fields[1].value = '14:0';
    await result.dispatch(buttonNamed(card, 'Move list item 2 up'), 'click');
  }
  return SEMANTIC_DRAFT_VALUES[{[SEMANTIC_IDS.role]:'semantic-role',[SEMANTIC_IDS.order]:'reading-order',[SEMANTIC_IDS.move]:'tree-move',[SEMANTIC_IDS.list]:'semantic-list'}[id]];
}

test('DOM semantic tree: new controls are opt-in and exact-page bound without changing earlier controls', async () => {
  const saved = semanticFixture(), before = JSON.stringify(saved), result = await bootSavedReview(saved);
  await openSavedReview(result); assert.deepEqual(decisionCards(result).map(card => card.dataset.decisionId), ['title-control', 'language-control']);
  await showSemantic(result);
  assert.deepEqual(decisionCards(result).map(card => card.dataset.decisionId), ['title-control', 'language-control', ...Object.values(SEMANTIC_IDS)]);
  assert.equal(result.getNode('show-navigation').checked, false); assert.equal(result.getNode('show-structure').checked, false);
  await result.dispatch('next-page', 'click'); assert.deepEqual(decisionCards(result).map(card => card.dataset.decisionId), ['title-control', 'language-control']);
  await result.dispatch('previous-page', 'click'); await showSemantic(result, false);
  assertSavedSnapshotUnchanged(result, saved, before); expectOnlyMutations(result, []);
});
test('DOM semantic tree: source labels render literally and controls never expose arbitrary node-ID or JSON inputs', async () => {
  const saved = semanticFixture(), result = await bootSavedReview(saved); await openSavedReview(result); await showSemantic(result);
  const cards = Object.values(SEMANTIC_IDS).map(id => cardFor(result, id));
  assert(cards.some(card => descendants(card).some(node => node.textContent.includes(LITERAL_CONTEXT))));
  assert(cards.every(card => !descendants(card).some(node => ['A','SCRIPT','IMG','TEXTAREA'].includes(node.tagName))));
  assert(cards.every(card => descendants(card).filter(node => node.tagName === 'INPUT').every(node => node.type === 'number')));
  assert(result.requests.every(request => request.url.startsWith('/api/'))); expectOnlyMutations(result, []);
});
for (const [kind, id] of Object.entries({ 'semantic-role': SEMANTIC_IDS.role, 'reading-order': SEMANTIC_IDS.order, 'tree-move': SEMANTIC_IDS.move, 'semantic-list': SEMANTIC_IDS.list })) {
  test('DOM semantic tree: Save keeps only an exact pending ' + kind + ' draft', async () => {
    const saved = semanticFixture(), before = JSON.stringify(saved), value = SEMANTIC_DRAFT_VALUES[kind], url = '/api/workspaces/' + saved.workspace_id + '/edit';
    const payload = {revision: 7, id, value}, response = editedView(saved, id, value), result = await bootSavedReview(saved, {expectedMutations: [{url, payload, response}]});
    await openSavedReview(result); await showSemantic(result); assert.equal(await fillSemanticDraft(result, id), value);
    const save = buttonNamed(cardFor(result, id), 'Save edit'); save.focus(); await result.dispatch(save, 'click');
    assertFreshFocus(result, buttonNamed(cardFor(result, id), 'Save edit'), save); assert.equal(result.getNode('apply').disabled, true);
    assert.equal(response.decisions.find(item => item.id === id).status, 'pending'); assertSavedSnapshotUnchanged(result, saved, before);
    expectOnlyMutations(result, [{url, payload}]);
  });
  test('DOM semantic tree: named ' + kind + ' acceptance saves then approves the exact new revision', async () => {
    const saved = semanticFixture(), value = SEMANTIC_DRAFT_VALUES[kind], url = '/api/workspaces/' + saved.workspace_id;
    const edited = editedView(saved, id, value), accepted = structuredClone(edited); accepted.revision = 9;
    Object.assign(accepted.decisions.find(item => item.id === id), {status: 'approved', approved_by: 'Authored tree reviewer'});
    const expected = [{url: url + '/edit', payload: {revision: 7, id, value}, response: edited},
      {url: url + '/approve', payload: {revision: 8, id, reviewer: 'Authored tree reviewer'}, response: accepted}];
    const result = await bootSavedReview(saved, {expectedMutations: expected}); await openSavedReview(result); await showSemantic(result);
    result.getNode('reviewer').value = ' Authored tree reviewer '; await fillSemanticDraft(result, id);
    const accept = buttonNamed(cardFor(result, id), 'Accept this value'); accept.focus(); await result.dispatch(accept, 'click');
    assertFreshFocus(result, buttonNamed(cardFor(result, id), 'Accept this value'), accept); assert.equal(result.getNode('apply').disabled, false);
    expectOnlyMutations(result, expected.map(({url,payload})=>({url,payload})));
  });
  test('DOM semantic tree: unnamed ' + kind + ' acceptance refuses before saving', async () => {
    const result = await bootSavedReview(semanticFixture()); await openSavedReview(result); await showSemantic(result); await fillSemanticDraft(result, id);
    await result.dispatch(buttonNamed(cardFor(result, id), 'Accept this value'), 'click');
    assert.match(result.getNode('notice').textContent, /Enter your name/); expectOnlyMutations(result, []);
  });
  test('DOM semantic tree: restoring the original ' + kind + ' withdraws a saved draft without repair credit', async () => {
    const saved = semanticFixture(), item = saved.decisions.find(row => row.id === id), original = item.current; item.value = SEMANTIC_DRAFT_VALUES[kind]; saved.unapplied_decisions = [id];
    const url = '/api/workspaces/' + saved.workspace_id + '/edit', payload = {revision: 7, id, value: original}, response = editedView(saved, id, original); response.unapplied_decisions = [];
    const result = await bootSavedReview(saved, {expectedMutations: [{url,payload,response}]}); await openSavedReview(result); await showSemantic(result);
    const card = cardFor(result, id); await result.dispatch(buttonNamed(card, 'Restore original choice'), 'click'); assert.match(result.getNode('notice').textContent, /does not repair/);
    await result.dispatch(buttonNamed(card, 'Save edit'), 'click'); assert.equal(result.getNode('apply').disabled, true); expectOnlyMutations(result, [{url,payload}]);
  });
}
for (const defect of ['unsafe','stale','missing-context','wrong-policy','wrong-page-count','missing-limits','duplicate-children','invented-role','self-parent']) {
  test('DOM semantic tree: ' + defect + ' source capability remains read-only', async () => {
    const saved = semanticFixture(), id = defect === 'invented-role' ? SEMANTIC_IDS.role : defect === 'self-parent' ? SEMANTIC_IDS.move : SEMANTIC_IDS.list;
    const item = saved.decisions.find(row => row.id === id);
    if (defect === 'unsafe') { item.structural_eligible = false; item.structural_limitations = ['The existing element is shared.']; }
    else if (defect === 'stale') saved.stale = true;
    else if (defect === 'missing-context') delete item.tree_context;
    else if (defect === 'wrong-policy') item.tree_context.policy = 'unknown';
    else if (defect === 'wrong-page-count') item.tree_context.page_count = 9;
    else if (defect === 'missing-limits') delete item.tree_context.limits;
    else if (defect === 'duplicate-children') item.tree_context.source.children[1] = item.tree_context.source.children[0];
    else if (defect === 'invented-role') item.allowed_values.push('Table');
    else item.tree_context.parent_choices[0].element = item.element;
    const before = JSON.stringify(saved), result = await bootSavedReview(saved); await openSavedReview(result); await showSemantic(result);
    const card = cardFor(result, id); for (const label of ['Save edit','Accept this value']) { assert(buttonNamed(card,label).disabled); await result.dispatch(buttonNamed(card,label),'click'); }
    assertSavedSnapshotUnchanged(result,saved,before); expectOnlyMutations(result,[]);
  });
}
for (const defect of ['missing-body','duplicate-node','noncontiguous-selection','empty-numbered-plan']) {
  test('DOM semantic tree: a ' + defect + ' list plan cannot be saved or inferred', async () => {
    const result = await bootSavedReview(semanticFixture()); await openSavedReview(result); await showSemantic(result);
    const card = cardFor(result,SEMANTIC_IDS.list); await fillSemanticDraft(result,SEMANTIC_IDS.list);
    if (defect === 'missing-body') selectsFor(semanticListRows(card)[0])[1].value = '';
    else if (defect === 'duplicate-node') selectsFor(semanticListRows(card)[1])[1].value = '14:0';
    else if (defect === 'noncontiguous-selection') for (const row of semanticListRows(card)) selectsFor(row)[0].value = '';
    else { await result.dispatch(buttonNamed(card,'Remove list item 2'),'click'); await result.dispatch(buttonNamed(card,'Remove list item 1'),'click'); }
    await result.dispatch(buttonNamed(card,'Save edit'),'click'); assert.equal(result.getNode('notice').classList.contains('error'),true); expectOnlyMutations(result,[]);
  });
}
test('DOM semantic tree: reparenting needs an explicit 1-based destination position and rejects source-unknown parents', async () => {
  const result = await bootSavedReview(semanticFixture()); await openSavedReview(result); await showSemantic(result); const card=cardFor(result,SEMANTIC_IDS.move),fields=semanticMoveFields(card);
  fields.parent.value='201:0'; await result.dispatch(fields.parent,'change'); assert.equal(fields.position.value,''); assert.equal(fields.position.max,'2');
  for (const position of ['', '0', '3', '1.5']) { fields.position.value=position; await result.dispatch(buttonNamed(card,'Save edit'),'click'); }
  fields.parent.value='invented-parent'; fields.position.value='1'; await result.dispatch(buttonNamed(card,'Save edit'),'click'); expectOnlyMutations(result,[]);
});
test('DOM semantic tree: existing sibling order has no remove control or arbitrary child input', async () => {
  const result=await bootSavedReview(semanticFixture());await openSavedReview(result);await showSemantic(result);const card=cardFor(result,SEMANTIC_IDS.order);
  assert.equal(descendants(card).filter(node=>['INPUT','SELECT','TEXTAREA'].includes(node.tagName)).length,0);
  assert(!descendants(card).filter(node=>node.tagName==='BUTTON').some(node=>/Remove element/.test(node.textContent)));
  await result.dispatch(buttonNamed(card,'Move element 1 down'),'click'); assert.equal(new Set(semanticOrderIds(card)).size,6); expectOnlyMutations(result,[]);
});
test('DOM semantic tree: explicit list rows may reorder a contiguous source union without synthesizing labels', async () => {
  const result=await bootSavedReview(semanticFixture());await openSavedReview(result);await showSemantic(result);await fillSemanticDraft(result,SEMANTIC_IDS.list);
  assert.deepEqual(semanticListRaw(result),[['13:0','14:0'],['11:0','12:0']]);const card=cardFor(result,SEMANTIC_IDS.list);
  await result.dispatch(buttonNamed(card,'Remove list item 1'),'click');assert.deepEqual(semanticListRaw(result),[['11:0','12:0']]);expectOnlyMutations(result,[]);
});
test('DOM semantic tree: partial list, move and role fields survive page navigation and collapse without autosave',async()=>{
  const saved=semanticFixture(),before=JSON.stringify(saved),result=await bootSavedReview(saved);await openSavedReview(result);await showSemantic(result);await fillSemanticDraft(result,SEMANTIC_IDS.list);await fillSemanticDraft(result,SEMANTIC_IDS.move);await fillSemanticDraft(result,SEMANTIC_IDS.role);
  selectsFor(semanticListRows(cardFor(result,SEMANTIC_IDS.list))[0])[1].value='';semanticMoveFields(cardFor(result,SEMANTIC_IDS.move)).position.value='';
  for(const action of ['next-page','previous-page','next-page','previous-page'])await result.dispatch(action,'click');
  for(let i=0;i<2;i++){await showSemantic(result,false);await showSemantic(result,true);}
  assert.deepEqual(semanticListRaw(result),[['13:0',''],['11:0','12:0']]);assert.equal(semanticMoveFields(cardFor(result,SEMANTIC_IDS.move)).position.value,'');assert.equal(selectsFor(cardFor(result,SEMANTIC_IDS.role))[0].value,'P');
  assert.equal(result.getNode('apply').disabled,true);assertSavedSnapshotUnchanged(result,saved,before);expectOnlyMutations(result,[]);
});

for (const change of ['context','server-value','stale']) {
  for (const focused of [false,true]) {
    test('DOM semantic tree: '+(focused?'focused':'unfocused')+' partial list cannot survive a changed '+change+' source binding',async()=>{
      const saved=semanticFixture(),delayed=deferredResponse(),id='title-control',value='A separately saved title',url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id,value},response=editedView(saved,id,value);
      const item=response.decisions.find(row=>row.id===SEMANTIC_IDS.list);
      if(change==='context')item.context_sha256='f'.repeat(64);
      else if(change==='server-value')item.value=semanticJSON({items:[{label:null,body:'12:0'}],numbering:'None'});
      else response.stale=true;
      const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:delayed.promise}]});await openSavedReview(result);await showSemantic(result);
      descendants(cardFor(result,id)).find(node=>node.tagName==='TEXTAREA').value=value;const saving=result.dispatch(buttonNamed(cardFor(result,id),'Save edit'),'click');await settle();
      await fillSemanticDraft(result,SEMANTIC_IDS.list);const field=selectsFor(semanticListRows(cardFor(result,SEMANTIC_IDS.list))[0])[1];field.value='';
      (focused?field:result.getNode('page-number')).focus();delayed.resolve(response);await saving;
      assert.deepEqual(semanticListRaw(result),change==='server-value'?[['','12:0']]:[]);
      if(change==='stale')assert(buttonNamed(cardFor(result,SEMANTIC_IDS.list),'Add list item').disabled);expectOnlyMutations(result,[{url,payload}]);
    });
  }
}
for (const change of ['context','capability']) {
  test('DOM semantic tree: an edited '+change+' response cannot carry named acceptance to a different occurrence',async()=>{
    const saved=semanticFixture(),id=SEMANTIC_IDS.role,value='P',url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id,value},response=editedView(saved,id,value);
    const item=response.decisions.find(row=>row.id===id);if(change==='context')item.context_sha256='e'.repeat(64);else item.tree_context.source.index=1;
    const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response}]});await openSavedReview(result);await showSemantic(result);result.getNode('reviewer').value='Authored source-bound reviewer';
    await fillSemanticDraft(result,id);await result.dispatch(buttonNamed(cardFor(result,id),'Accept this value'),'click');
    assert.equal(response.decisions.find(row=>row.id===id).status,'pending');expectOnlyMutations(result,[{url,payload}]);
  });
}
for (const transition of ['next-page','page-round-trip','hide-controls','hide-and-show-controls','checks-tab']) {
  test('DOM semantic tree: delayed Save to Accept stops after '+transition,async()=>{
    const saved=semanticFixture(),id=SEMANTIC_IDS.role,value='P',url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id,value},delayed=deferredResponse();
    const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:delayed.promise}]});await openSavedReview(result);await showSemantic(result);result.getNode('reviewer').value='Authored tree reviewer';
    await fillSemanticDraft(result,id);const accepting=result.dispatch(buttonNamed(cardFor(result,id),'Accept this value'),'click');await settle();
    if(transition==='next-page')await result.dispatch('next-page','click');
    else if(transition==='page-round-trip'){await result.dispatch('next-page','click');await result.dispatch('previous-page','click');}
    else if(transition==='hide-controls')await showSemantic(result,false);
    else if(transition==='hide-and-show-controls'){await showSemantic(result,false);await showSemantic(result,true);}
    else await result.dispatch('tab-checks','click');
    delayed.resolve(editedView(saved,id,value));await accepting;expectOnlyMutations(result,[{url,payload}]);
  });
}
test('DOM semantic tree: newer local fields during Save to Accept remain unaccepted',async()=>{
  const saved=semanticFixture(),id=SEMANTIC_IDS.role,value='P',url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id,value},delayed=deferredResponse();
  const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:delayed.promise}]});await openSavedReview(result);await showSemantic(result);result.getNode('reviewer').value='Authored tree reviewer';
  await fillSemanticDraft(result,id);const card=cardFor(result,id),field=selectsFor(card)[0],accepting=result.dispatch(buttonNamed(card,'Accept this value'),'click');await settle();
  field.value='H2';field.focus();delayed.resolve(editedView(saved,id,value));await accepting;
  assert.equal(selectsFor(cardFor(result,id))[0].value,'H2');assert.equal(result.getNode('apply').disabled,true);expectOnlyMutations(result,[{url,payload}]);
});
for (const returnToA of [false,true]) {
  test('DOM semantic tree: a delayed acceptance cannot cross workspace '+(returnToA?'A to B to A':'A to B'),async()=>{
    const first=semanticFixture(),second=semanticFixture();first.source.path='/authored/workspace-A.pdf';second.source.path='/authored/workspace-B.pdf';second.workspace_id='f'.repeat(24);
    const id=SEMANTIC_IDS.role,value='P',url='/api/workspaces/'+first.workspace_id+'/edit',payload={revision:7,id,value},delayed=deferredResponse();
    const result=await bootNavigation(first,second,{expectedMutations:[{url,payload,response:delayed.promise}]});await openNamedWorkspace(result,'workspace-A.pdf');await showSemantic(result);result.getNode('reviewer').value='Authored workspace reviewer';await fillSemanticDraft(result,id);
    const accepting=result.dispatch(buttonNamed(cardFor(result,id),'Accept this value'),'click');await settle();await result.dispatch('back','click');await openNamedWorkspace(result,'workspace-B.pdf');
    if(returnToA){await result.dispatch('back','click');await openNamedWorkspace(result,'workspace-A.pdf');}
    delayed.resolve(editedView(first,id,value));await accepting;assert.equal(selectsFor(cardFor(result,id))[0].value,'H2');expectOnlyMutations(result,[{url,payload}]);
  });
}
test('DOM semantic tree: newer partial list fields survive a known same-decision Save response while focus stays inside the card',async()=>{
  const saved=semanticFixture(),id=SEMANTIC_IDS.list,value=SEMANTIC_DRAFT_VALUES['semantic-list'],url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id,value},delayed=deferredResponse();
  const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:delayed.promise}]});await openSavedReview(result);await showSemantic(result);await fillSemanticDraft(result,id);
  const card=cardFor(result,id),body=selectsFor(semanticListRows(card)[0])[1];body.focus();const saving=result.dispatch(buttonNamed(card,'Save edit'),'click');await settle();
  selectsFor(semanticListRows(card)[1])[1].value='';delayed.resolve(editedView(saved,id,value));await saving;
  assert.deepEqual(semanticListRaw(result),[['13:0','14:0'],['11:0','']]);assert.equal(result.getNode('apply').disabled,true);expectOnlyMutations(result,[{url,payload}]);
});
test('DOM semantic tree: a known Accept response preserves newer partial list fields without accepting those fields',async()=>{
  const saved=semanticFixture(),id=SEMANTIC_IDS.list,value=SEMANTIC_DRAFT_VALUES['semantic-list'],base='/api/workspaces/'+saved.workspace_id,edited=editedView(saved,id,value),accepted=structuredClone(edited),delayed=deferredResponse();accepted.revision=9;accepted.decisions.find(row=>row.id===id).status='approved';
  const expected=[{url:base+'/edit',payload:{revision:7,id,value},response:edited},{url:base+'/approve',payload:{revision:8,id,reviewer:'Authored response reviewer'},response:delayed.promise}];
  const result=await bootSavedReview(saved,{expectedMutations:expected});await openSavedReview(result);await showSemantic(result);result.getNode('reviewer').value='Authored response reviewer';await fillSemanticDraft(result,id);
  const accepting=result.dispatch(buttonNamed(cardFor(result,id),'Accept this value'),'click');await settle();const row=semanticListRows(cardFor(result,id))[0],field=selectsFor(row)[1];field.value='';field.focus();
  delayed.resolve(accepted);await accepting;assert.deepEqual(semanticListRaw(result),[['13:0',''],['11:0','12:0']]);expectOnlyMutations(result,expected.map(({url,payload})=>({url,payload})));
});
test('DOM semantic tree: an active job blocks acceptance and every new control after page navigation',async()=>{
  const saved=semanticFixture(),base='/api/workspaces/'+saved.workspace_id,expected=[{url:base+'/auto-fix',payload:{revision:7,consent:true,use_ai:false,ai_consent:false,endpoint:'',model:'',include_images:false,reasoning_effort:null},response:{job_id:'authored-tree-guard'}}];
  const result=await bootSavedReview(saved,{captureTimers:true,expectedMutations:expected});await openSavedReview(result);await showSemantic(result);await result.dispatch('auto-fix','click');
  await showSemantic(result,false);await showSemantic(result,true);await result.dispatch('next-page','click');await result.dispatch('previous-page','click');
  assert.equal(result.getNode('show-semantic').disabled,true);for(const id of Object.values(SEMANTIC_IDS))for(const control of descendants(cardFor(result,id)).filter(node=>['INPUT','SELECT','TEXTAREA','BUTTON'].includes(node.tagName)))assert.equal(control.disabled,true);
  assert.deepEqual(result.mutationRequests,expected.map(({url,payload})=>({url,payload})));assert.deepEqual(result.remainingMutations,[]);assert.deepEqual(result.unexpectedRequests,[]);
});

// Complete-table authoring is a source-bound plan, not a free-form JSON editor.
const TABLE_ID='table:structure:400:0',TABLE_CELLS=['410:0','411:0','412:0','413:0','414:0','415:0','416:0'];
function tableFixture(){
  const saved=repairControlsFixture(),texts=[LITERAL_CONTEXT,'Results','Current','Prior','Enrollment','100','90'];
  const positions=[[0,0,0,2,1],[0,1,1,1,2],[1,0,1,1,1],[1,1,2,1,1],[2,0,0,1,1],[2,1,1,1,1],[2,2,2,1,1]];
  const cells=TABLE_CELLS.map((element,index)=>{const [row,cell,column,row_span,col_span]=positions[index];return {element,role:'TD',page:1,pages:[1],row,index:cell,column,context_text:texts[index],id:null,scope:null,headers:[],row_span,col_span};});
  const table_context={policy:'reviewed-table-1',table:{element:'400:0',path:'Document/Table[1]',pages:[1],summary:null},
    rows:[{element:'401:0',index:0,group:null,group_key:'direct',cells:TABLE_CELLS.slice(0,2)},{element:'402:0',index:1,group:null,group_key:'direct',cells:TABLE_CELLS.slice(2,4)},{element:'403:0',index:2,group:null,group_key:'direct',cells:TABLE_CELLS.slice(4)}],cells,
    global_ids:[{id:'outside',element:'999:0'}],limits:{rows:100,cells:500,columns:100,span:100,headers:32,id_chars:128,summary_chars:4000,payload_chars:150000}};
  const current=semanticJSON({summary:null,cells:cells.map(({element,role,id,scope,headers,row_span,col_span})=>({element,role,id,scope,headers,row_span,col_span}))});
  saved.decisions.push({id:TABLE_ID,kind:'table-structure',current,value:current,page:1,element:'400:0',structure_path:'Document/Table[1]',context_sha256:'d'.repeat(64),context_text:LITERAL_CONTEXT,
    structural_eligible:true,structural_limitations:[],status:'pending',human_touched:false,references:[{page:1,stream:'page',mcid:20}],table_context});return saved;
}
function syncTableOriginal(saved){const item=saved.decisions.find(row=>row.id===TABLE_ID),c=item.table_context;item.current=item.value=semanticJSON({summary:c.table.summary,cells:c.cells.map(({element,role,id,scope,headers,row_span,col_span})=>({element,role,id,scope,headers,row_span,col_span}))});return saved;}
function tableDraft(){const plan=JSON.parse(tableFixture().decisions.at(-1).current);plan.summary='Results compare current and prior enrollment.\nHeader relationships are explicit — reviewed.';
  const ids=['measure','results','current','prior','enrollment'];for(let index=0;index<5;index++)Object.assign(plan.cells[index],{role:'TH',id:ids[index],scope:index===4?'Row':'Column'});
  plan.cells[2].headers=[TABLE_CELLS[1]];plan.cells[3].headers=[TABLE_CELLS[1]];plan.cells[5].headers=[TABLE_CELLS[2],TABLE_CELLS[4]];plan.cells[6].headers=[TABLE_CELLS[3],TABLE_CELLS[4]];return plan;
}
async function showTables(result,checked=true){result.getNode('show-tables').checked=checked;await result.dispatch('show-tables','change');}
function tableRows(card){return descendants(card).filter(node=>node.dataset?.tableCell);}
function tableRow(card,id){const rows=tableRows(card).filter(row=>row.dataset.tableCell===id);assert.equal(rows.length,1);return rows[0];}
function tableFields(card,id){const row=tableRow(card,id),selects=selectsFor(row),texts=descendants(row).filter(node=>node.tagName==='TEXTAREA'),numbers=descendants(row).filter(node=>node.tagName==='INPUT');return {row,role:selects[0],scope:selects[1],id:texts[0],rowSpan:numbers[0],colSpan:numbers[1],headers:selects.slice(2)};}
function tableSummary(card){return descendants(card).find(node=>node.tagName==='TEXTAREA'&&node.getAttribute('aria-label')==='Table summary '+TABLE_ID);}
function tableRaw(card){return {summary:tableSummary(card).value,cells:TABLE_CELLS.map(id=>{const fields=tableFields(card,id);return {element:id,role:fields.role.value,id:fields.id.value,scope:fields.scope.value,row_span:fields.rowSpan.value,col_span:fields.colSpan.value,headers:fields.headers.map(field=>field.value)};})};}
async function fillTableDraft(result,plan=tableDraft()){
  const card=cardFor(result,TABLE_ID);tableSummary(card).value=plan.summary??'';
  for(const cell of plan.cells){const fields=tableFields(card,cell.element);fields.role.value=cell.role;fields.id.value=cell.id??'';fields.scope.value=cell.scope??'';fields.rowSpan.value=String(cell.row_span);fields.colSpan.value=String(cell.col_span);}
  await result.dispatch(tableFields(card,TABLE_CELLS[0]).role,'change');
  for(const cell of plan.cells){let fields=tableFields(card,cell.element);while(fields.headers.length) {await result.dispatch(buttonNamed(fields.row,'Remove header 1 from cell '+cell.element),'click');fields=tableFields(card,cell.element);}
    for(const target of cell.headers){await result.dispatch(buttonNamed(fields.row,'Add header to cell '+cell.element),'click');fields=tableFields(card,cell.element);fields.headers.at(-1).value=target;}}
  return semanticJSON(plan);
}

test('DOM tables: complete-table controls are opt-in and exact-page bound',async()=>{
  const saved=tableFixture(),before=JSON.stringify(saved),result=await bootSavedReview(saved);await openSavedReview(result);
  assert.deepEqual(decisionCards(result).map(card=>card.dataset.decisionId),['title-control','language-control']);await showTables(result);
  assert.deepEqual(tableRows(cardFor(result,TABLE_ID)).map(row=>row.dataset.tableCell),TABLE_CELLS);assert.equal(result.getNode('show-semantic').checked,false);assert.equal(result.getNode('show-structure').checked,false);
  await result.dispatch('next-page','click');assert(!decisionCards(result).some(card=>card.dataset.decisionId===TABLE_ID));await result.dispatch('previous-page','click');await showTables(result,false);
  assertSavedSnapshotUnchanged(result,saved,before);expectOnlyMutations(result,[]);
});
test('DOM tables: document-wide multi-page table plans remain one atomic plan',async()=>{
  const saved=tableFixture(),item=saved.decisions.at(-1);item.page=null;item.table_context.table.pages=[1,2];item.table_context.cells.at(-1).page=2;item.table_context.cells.at(-1).pages=[2];
  const result=await bootSavedReview(saved);await openSavedReview(result);await showTables(result);await result.dispatch('next-page','click');assert.equal(tableRows(cardFor(result,TABLE_ID)).length,7);expectOnlyMutations(result,[]);
});
test('DOM tables: literal source excerpts and real summary and ID textareas never become HTML or arbitrary JSON inputs',async()=>{
  const saved=tableFixture();saved.decisions.at(-1).table_context.table.summary='Original\nRésumé — <script>literal</script>';syncTableOriginal(saved);
  const result=await bootSavedReview(saved);await openSavedReview(result);await showTables(result);const card=cardFor(result,TABLE_ID);
  assert(descendants(card).some(node=>node.textContent.includes(LITERAL_CONTEXT)));assert.equal(tableSummary(card).value,'Original\nRésumé — <script>literal</script>');assert.equal(tableSummary(card).tagName,'TEXTAREA');
  assert(!descendants(card).some(node=>['SCRIPT','IMG','A'].includes(node.tagName)));assert.equal(descendants(card).filter(node=>node.tagName==='TEXTAREA').length,8);
  assert(descendants(card).filter(node=>node.tagName==='INPUT').every(node=>node.type==='number'));expectOnlyMutations(result,[]);
});
test('DOM tables: source cell rows expose no cell insertion deletion split movement or generated summary controls',async()=>{
  const result=await bootSavedReview(tableFixture());await openSavedReview(result);await showTables(result);const card=cardFor(result,TABLE_ID),buttons=descendants(card).filter(node=>node.tagName==='BUTTON').map(node=>node.textContent);
  assert(!buttons.some(label=>/add cell|remove cell|split|move cell|generate|guess/i.test(label)));assert.equal(tableSummary(card).value,'');assert(TABLE_CELLS.every(id=>tableFields(card,id).id.value===''));expectOnlyMutations(result,[]);
});
test('DOM tables: Save sends one exact pending whole-table plan with parent and multiple header selections',async()=>{
  const saved=tableFixture(),before=JSON.stringify(saved),value=semanticJSON(tableDraft()),url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:TABLE_ID,value},response=editedView(saved,TABLE_ID,value);
  const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response}]});await openSavedReview(result);await showTables(result);assert.equal(await fillTableDraft(result),value);
  const save=buttonNamed(cardFor(result,TABLE_ID),'Save edit');save.focus();await result.dispatch(save,'click');assertFreshFocus(result,buttonNamed(cardFor(result,TABLE_ID),'Save edit'),save);
  assert.equal(result.getNode('apply').disabled,true);assert.equal(response.decisions.at(-1).status,'pending');assertSavedSnapshotUnchanged(result,saved,before);expectOnlyMutations(result,[{url,payload}]);
});
test('DOM tables: named acceptance saves then approves the exact new revision and never applies automatically',async()=>{
  const saved=tableFixture(),value=semanticJSON(tableDraft()),base='/api/workspaces/'+saved.workspace_id,edited=editedView(saved,TABLE_ID,value),accepted=structuredClone(edited);accepted.revision=9;Object.assign(accepted.decisions.at(-1),{status:'approved',approved_by:'Authored table reviewer'});
  const expected=[{url:base+'/edit',payload:{revision:7,id:TABLE_ID,value},response:edited},{url:base+'/approve',payload:{revision:8,id:TABLE_ID,reviewer:'Authored table reviewer'},response:accepted}];
  const result=await bootSavedReview(saved,{expectedMutations:expected});await openSavedReview(result);await showTables(result);result.getNode('reviewer').value=' Authored table reviewer ';await fillTableDraft(result);
  await result.dispatch(buttonNamed(cardFor(result,TABLE_ID),'Accept this value'),'click');assert.equal(result.getNode('apply').disabled,false);expectOnlyMutations(result,expected.map(({url,payload})=>({url,payload})));
});
test('DOM tables: unnamed acceptance refuses before saving',async()=>{
  const result=await bootSavedReview(tableFixture());await openSavedReview(result);await showTables(result);await fillTableDraft(result);await result.dispatch(buttonNamed(cardFor(result,TABLE_ID),'Accept this value'),'click');assert.match(result.getNode('notice').textContent,/Enter your name/);expectOnlyMutations(result,[]);
});
test('DOM tables: restoring an original table withdraws a saved draft without repair credit',async()=>{
  const saved=tableFixture(),item=saved.decisions.at(-1),value=item.current;item.value=semanticJSON(tableDraft());saved.unapplied_decisions=[TABLE_ID];const url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:TABLE_ID,value},response=editedView(saved,TABLE_ID,value);response.unapplied_decisions=[];
  const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response}]});await openSavedReview(result);await showTables(result);await result.dispatch(buttonNamed(cardFor(result,TABLE_ID),'Restore original table'),'click');assert.match(result.getNode('notice').textContent,/does not repair/);
  await result.dispatch(buttonNamed(cardFor(result,TABLE_ID),'Save edit'),'click');assert.equal(result.getNode('apply').disabled,true);expectOnlyMutations(result,[{url,payload}]);
});
test('DOM tables: exact original invalid references may be withdrawn without inferring replacement headers',async()=>{
  const saved=tableFixture(),c=saved.decisions.at(-1).table_context;c.cells[5].headers=['unresolved:bad-source'];c.table.summary='';syncTableOriginal(saved);const value=saved.decisions.at(-1).current,url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:TABLE_ID,value};
  const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:editedView(saved,TABLE_ID,value)}]});await openSavedReview(result);await showTables(result);const card=cardFor(result,TABLE_ID);
  assert.equal(tableFields(card,TABLE_CELLS[5]).headers[0].value,'unresolved:bad-source');await result.dispatch(buttonNamed(card,'Restore original table'),'click');await result.dispatch(buttonNamed(card,'Save edit'),'click');expectOnlyMutations(result,[{url,payload}]);
});
for(const defect of ['unsafe','stale','missing-context','wrong-policy','wrong-limits','duplicate-source-cell','source-order','source-plan','unknown-group','page-outside-document']){
  test('DOM tables: '+defect+' source capability stays read-only',async()=>{
    const saved=tableFixture(),item=saved.decisions.at(-1),c=item.table_context;
    if(defect==='unsafe'){item.structural_eligible=false;item.structural_limitations=['This existing table contains a nested table.'];}else if(defect==='stale')saved.stale=true;else if(defect==='missing-context')delete item.table_context;else if(defect==='wrong-policy')c.policy='unknown';else if(defect==='wrong-limits')c.limits.cells=501;else if(defect==='duplicate-source-cell')c.rows[0].cells[1]=c.rows[0].cells[0];else if(defect==='source-order')[c.cells[0],c.cells[1]]=[c.cells[1],c.cells[0]];else if(defect==='source-plan')c.cells[0].context_text=19;else if(defect==='unknown-group')c.rows[0].group='Invented';else c.table.pages=[9];
    const before=JSON.stringify(saved),result=await bootSavedReview(saved);await openSavedReview(result);await showTables(result);for(const label of ['Save edit','Accept this value']){const control=buttonNamed(cardFor(result,TABLE_ID),label);assert(control.disabled);await result.dispatch(control,'click');}assertSavedSnapshotUnchanged(result,saved,before);expectOnlyMutations(result,[]);
  });
}
for(const defect of ['duplicate-id','global-id-collision','invalid-id','oversized-id','data-scope','self-header','missing-header-id','duplicate-header','cyclic-headers','blank-header','zero-span','fractional-span','oversized-span','rowspan-outside-table','grid-hole','row-group-crossing','oversized-summary']){
  test('DOM tables: a '+defect+' whole-table plan refuses before any save',async()=>{
    const saved=tableFixture();if(defect==='row-group-crossing'){saved.decisions.at(-1).table_context.rows[0].group='THead';saved.decisions.at(-1).table_context.rows[0].group_key='thead:1';saved.decisions.at(-1).table_context.rows[1].group='TBody';saved.decisions.at(-1).table_context.rows[1].group_key='tbody:1';}
    const result=await bootSavedReview(saved);await openSavedReview(result);await showTables(result);await fillTableDraft(result);const card=cardFor(result,TABLE_ID),first=tableFields(card,TABLE_CELLS[0]),data=tableFields(card,TABLE_CELLS[5]);
    if(defect==='duplicate-id')tableFields(card,TABLE_CELLS[1]).id.value=first.id.value;else if(defect==='global-id-collision')first.id.value='outside';else if(defect==='invalid-id')first.id.value='Not a valid ID';else if(defect==='oversized-id')first.id.value='a'.repeat(129);else if(defect==='data-scope')data.scope.value='Row';else if(defect==='missing-header-id')tableFields(card,TABLE_CELLS[2]).id.value='';else if(defect==='duplicate-header')data.headers[1].value=data.headers[0].value;else if(defect==='blank-header')data.headers[0].value='';else if(defect==='self-header'){await result.dispatch(buttonNamed(first.row,'Add header to cell '+TABLE_CELLS[0]),'click');tableFields(card,TABLE_CELLS[0]).headers[0].value=TABLE_CELLS[0];}
    else if(defect==='cyclic-headers'){const second=tableFields(card,TABLE_CELLS[1]);await result.dispatch(buttonNamed(second.row,'Add header to cell '+TABLE_CELLS[1]),'click');tableFields(card,TABLE_CELLS[1]).headers[0].value=TABLE_CELLS[2];}
    else if(defect==='zero-span')first.rowSpan.value='0';else if(defect==='fractional-span')first.colSpan.value='1.5';else if(defect==='oversized-span')first.colSpan.value='101';else if(defect==='rowspan-outside-table')data.rowSpan.value='2';else if(defect==='grid-hole')tableFields(card,TABLE_CELLS[1]).colSpan.value='1';else if(defect==='oversized-summary')tableSummary(card).value='x'.repeat(4001);
    await result.dispatch(buttonNamed(card,'Save edit'),'click');assert.equal(result.getNode('notice').classList.contains('error'),true);expectOnlyMutations(result,[]);
  });
}
test('DOM tables: unresolved original relationships must be explicitly cleared or replaced in a changed plan',async()=>{
  const saved=tableFixture();saved.decisions.at(-1).table_context.cells[5].headers=['unresolved:original'];syncTableOriginal(saved);const result=await bootSavedReview(saved);await openSavedReview(result);await showTables(result);const card=cardFor(result,TABLE_ID);tableSummary(card).value='A changed summary';await result.dispatch(buttonNamed(card,'Save edit'),'click');assert.match(result.getNode('notice').textContent,/header relationship/);expectOnlyMutations(result,[]);
});
test('DOM tables: changing spans recomputes a complete grid without changing source cell order',async()=>{
  const saved=tableFixture(),plan=tableDraft();plan.cells[0].row_span=1;plan.cells[2].col_span=2;const value=semanticJSON(plan),url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:TABLE_ID,value};
  const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:editedView(saved,TABLE_ID,value)}]});await openSavedReview(result);await showTables(result);await fillTableDraft(result,plan);await result.dispatch(buttonNamed(cardFor(result,TABLE_ID),'Save edit'),'click');assert.deepEqual(tableRows(cardFor(result,TABLE_ID)).map(row=>row.dataset.tableCell),TABLE_CELLS);expectOnlyMutations(result,[{url,payload}]);
});
test('DOM tables: header identity selections survive explicit target ID renaming',async()=>{
  const result=await bootSavedReview(tableFixture());await openSavedReview(result);await showTables(result);await fillTableDraft(result);const card=cardFor(result,TABLE_ID),target=tableFields(card,TABLE_CELLS[2]);target.id.value='renamed_current';await result.dispatch(target.id,'input');assert.deepEqual(tableFields(card,TABLE_CELLS[5]).headers.map(field=>field.value),[TABLE_CELLS[2],TABLE_CELLS[4]]);assert(tableFields(card,TABLE_CELLS[5]).headers[0].children.some(option=>option.value===TABLE_CELLS[2]&&option.textContent.includes('renamed_current')));expectOnlyMutations(result,[]);
});
test('DOM tables: a role change retains an existing selection visibly but refuses its now-data target',async()=>{
  const result=await bootSavedReview(tableFixture());await openSavedReview(result);await showTables(result);await fillTableDraft(result);const card=cardFor(result,TABLE_ID),target=tableFields(card,TABLE_CELLS[2]);target.role.value='TD';target.scope.value='';await result.dispatch(target.role,'change');assert.equal(tableFields(card,TABLE_CELLS[5]).headers[0].value,TABLE_CELLS[2]);assert(tableFields(card,TABLE_CELLS[5]).headers[0].children.some(option=>option.value===TABLE_CELLS[2]&&option.textContent.includes('not a header')));await result.dispatch(buttonNamed(card,'Save edit'),'click');expectOnlyMutations(result,[]);
});
test('DOM tables: scope-only headers need no forced IDs or guessed associations',async()=>{
  const saved=tableFixture(),plan=JSON.parse(saved.decisions.at(-1).current);Object.assign(plan.cells[0],{role:'TH',scope:'Column'});const value=semanticJSON(plan),url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:TABLE_ID,value};const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:editedView(saved,TABLE_ID,value)}]});await openSavedReview(result);await showTables(result);await fillTableDraft(result,plan);await result.dispatch(buttonNamed(cardFor(result,TABLE_ID),'Save edit'),'click');expectOnlyMutations(result,[{url,payload}]);
});
test('DOM tables: unchanged original Unicode IDs and summary line breaks survive a separately changed plan',async()=>{
  const saved=tableFixture(),c=saved.decisions.at(-1).table_context;c.cells[0].id='Ünicode\noriginal';c.global_ids.push({id:c.cells[0].id,element:TABLE_CELLS[0]});c.table.summary='Original\nRésumé';syncTableOriginal(saved);const plan=JSON.parse(saved.decisions.at(-1).current);plan.summary+='\nReviewed description';const value=semanticJSON(plan),url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:TABLE_ID,value};
  const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:editedView(saved,TABLE_ID,value)}]});await openSavedReview(result);await showTables(result);assert.equal(tableFields(cardFor(result,TABLE_ID),TABLE_CELLS[0]).id.value,'Ünicode\noriginal');tableSummary(cardFor(result,TABLE_ID)).value=plan.summary;await result.dispatch(buttonNamed(cardFor(result,TABLE_ID),'Save edit'),'click');expectOnlyMutations(result,[{url,payload}]);
});
test('DOM tables: partially filled raw headers spans and summaries survive pages and collapse without autosave',async()=>{
  const saved=tableFixture(),before=JSON.stringify(saved),result=await bootSavedReview(saved);await openSavedReview(result);await showTables(result);await fillTableDraft(result);let card=cardFor(result,TABLE_ID);tableFields(card,TABLE_CELLS[5]).headers[1].value='';tableFields(card,TABLE_CELLS[0]).rowSpan.value='';tableSummary(card).value='Incomplete\nRésumé';const raw=tableRaw(card);
  for(const action of ['next-page','previous-page','next-page','previous-page'])await result.dispatch(action,'click');for(let i=0;i<2;i++){await showTables(result,false);await showTables(result,true);}assert.deepEqual(tableRaw(cardFor(result,TABLE_ID)),raw);assert.equal(result.getNode('apply').disabled,true);assertSavedSnapshotUnchanged(result,saved,before);expectOnlyMutations(result,[]);
});
for(const change of ['context','server-value','stale'])for(const focused of [false,true]){
  test('DOM tables: '+(focused?'focused':'unfocused')+' raw drafts cannot cross a changed '+change+' binding',async()=>{
    const saved=tableFixture(),delayed=deferredResponse(),id='title-control',value='A separate authored title',url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id,value},response=editedView(saved,id,value),item=response.decisions.at(-1);
    if(change==='context')item.context_sha256='f'.repeat(64);else if(change==='server-value'){const plan=JSON.parse(item.current);plan.summary='A separately saved table';item.value=semanticJSON(plan);}else response.stale=true;
    const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:delayed.promise}]});await openSavedReview(result);await showTables(result);descendants(cardFor(result,id)).find(node=>node.tagName==='TEXTAREA').value=value;const saving=result.dispatch(buttonNamed(cardFor(result,id),'Save edit'),'click');await settle();await fillTableDraft(result);const field=tableFields(cardFor(result,TABLE_ID),TABLE_CELLS[5]).headers[0];field.value='';(focused?field:result.getNode('page-number')).focus();delayed.resolve(response);await saving;
    assert.equal(tableSummary(cardFor(result,TABLE_ID)).value,change==='server-value'?'A separately saved table':'');assert.equal(tableFields(cardFor(result,TABLE_ID),TABLE_CELLS[5]).headers.length,0);expectOnlyMutations(result,[{url,payload}]);
  });
}
for(const change of ['context','capability']){
  test('DOM tables: a changed '+change+' Save response cannot carry named acceptance to another occurrence',async()=>{
    const saved=tableFixture(),value=semanticJSON(tableDraft()),url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:TABLE_ID,value},response=editedView(saved,TABLE_ID,value);if(change==='context')response.decisions.at(-1).context_sha256='e'.repeat(64);else response.decisions.at(-1).table_context.cells[0].context_text='Different occurrence';
    const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response}]});await openSavedReview(result);await showTables(result);result.getNode('reviewer').value='Authored bound reviewer';await fillTableDraft(result);await result.dispatch(buttonNamed(cardFor(result,TABLE_ID),'Accept this value'),'click');expectOnlyMutations(result,[{url,payload}]);
  });
}
for(const transition of ['next-page','page-round-trip','hide-controls','hide-and-show-controls','checks-tab']){
  test('DOM tables: delayed Save to Accept stops after '+transition,async()=>{
    const saved=tableFixture(),value=semanticJSON(tableDraft()),url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:TABLE_ID,value},delayed=deferredResponse();const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:delayed.promise}]});await openSavedReview(result);await showTables(result);result.getNode('reviewer').value='Authored table reviewer';await fillTableDraft(result);const accepting=result.dispatch(buttonNamed(cardFor(result,TABLE_ID),'Accept this value'),'click');await settle();
    if(transition==='next-page')await result.dispatch('next-page','click');else if(transition==='page-round-trip'){await result.dispatch('next-page','click');await result.dispatch('previous-page','click');}else if(transition==='hide-controls')await showTables(result,false);else if(transition==='hide-and-show-controls'){await showTables(result,false);await showTables(result,true);}else await result.dispatch('tab-checks','click');delayed.resolve(editedView(saved,TABLE_ID,value));await accepting;expectOnlyMutations(result,[{url,payload}]);
  });
}
test('DOM tables: newer invalid fields during Save to Accept remain visible and unaccepted',async()=>{
  const saved=tableFixture(),value=semanticJSON(tableDraft()),url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:TABLE_ID,value},delayed=deferredResponse(),result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:delayed.promise}]});await openSavedReview(result);await showTables(result);result.getNode('reviewer').value='Authored table reviewer';await fillTableDraft(result);const card=cardFor(result,TABLE_ID),accepting=result.dispatch(buttonNamed(card,'Accept this value'),'click');await settle();const field=tableFields(card,TABLE_CELLS[0]).rowSpan;field.value='';field.focus();delayed.resolve(editedView(saved,TABLE_ID,value));await accepting;assert.equal(tableFields(cardFor(result,TABLE_ID),TABLE_CELLS[0]).rowSpan.value,'');assert.equal(result.getNode('apply').disabled,true);expectOnlyMutations(result,[{url,payload}]);
});
test('DOM tables: newer raw header rows survive a known same-decision Save response with focus inside the card',async()=>{
  const saved=tableFixture(),value=semanticJSON(tableDraft()),url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:TABLE_ID,value},delayed=deferredResponse(),result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:delayed.promise}]});await openSavedReview(result);await showTables(result);await fillTableDraft(result);const card=cardFor(result,TABLE_ID),field=tableFields(card,TABLE_CELLS[5]).headers[0];field.focus();const saving=result.dispatch(buttonNamed(card,'Save edit'),'click');await settle();tableFields(card,TABLE_CELLS[6]).headers[1].value='';delayed.resolve(editedView(saved,TABLE_ID,value));await saving;assert.deepEqual(tableFields(cardFor(result,TABLE_ID),TABLE_CELLS[6]).headers.map(header=>header.value),[TABLE_CELLS[3],'']);expectOnlyMutations(result,[{url,payload}]);
});
test('DOM tables: a known Accept response preserves newer partial fields without accepting them',async()=>{
  const saved=tableFixture(),value=semanticJSON(tableDraft()),base='/api/workspaces/'+saved.workspace_id,edited=editedView(saved,TABLE_ID,value),accepted=structuredClone(edited),delayed=deferredResponse();accepted.revision=9;accepted.decisions.at(-1).status='approved';const expected=[{url:base+'/edit',payload:{revision:7,id:TABLE_ID,value},response:edited},{url:base+'/approve',payload:{revision:8,id:TABLE_ID,reviewer:'Authored response reviewer'},response:delayed.promise}];
  const result=await bootSavedReview(saved,{expectedMutations:expected});await openSavedReview(result);await showTables(result);result.getNode('reviewer').value='Authored response reviewer';await fillTableDraft(result);const accepting=result.dispatch(buttonNamed(cardFor(result,TABLE_ID),'Accept this value'),'click');await settle();const field=tableFields(cardFor(result,TABLE_ID),TABLE_CELLS[5]).headers[0];field.value='';field.focus();delayed.resolve(accepted);await accepting;assert.equal(tableFields(cardFor(result,TABLE_ID),TABLE_CELLS[5]).headers[0].value,'');expectOnlyMutations(result,expected.map(({url,payload})=>({url,payload})));
});
for(const returnToA of [false,true]){
  test('DOM tables: a delayed acceptance cannot cross workspace '+(returnToA?'A to B to A':'A to B'),async()=>{
    const first=tableFixture(),second=tableFixture();first.source.path='/authored/workspace-A.pdf';second.source.path='/authored/workspace-B.pdf';second.workspace_id='f'.repeat(24);const value=semanticJSON(tableDraft()),url='/api/workspaces/'+first.workspace_id+'/edit',payload={revision:7,id:TABLE_ID,value},delayed=deferredResponse();const result=await bootNavigation(first,second,{expectedMutations:[{url,payload,response:delayed.promise}]});await openNamedWorkspace(result,'workspace-A.pdf');await showTables(result);result.getNode('reviewer').value='Authored workspace reviewer';await fillTableDraft(result);const accepting=result.dispatch(buttonNamed(cardFor(result,TABLE_ID),'Accept this value'),'click');await settle();await result.dispatch('back','click');await openNamedWorkspace(result,'workspace-B.pdf');if(returnToA){await result.dispatch('back','click');await openNamedWorkspace(result,'workspace-A.pdf');}delayed.resolve(editedView(first,TABLE_ID,value));await accepting;assert.equal(tableSummary(cardFor(result,TABLE_ID)).value,'');expectOnlyMutations(result,[{url,payload}]);
  });
}
test('DOM tables: an active job blocks the plan and every table control after page navigation',async()=>{
  const saved=tableFixture(),base='/api/workspaces/'+saved.workspace_id,expected=[{url:base+'/auto-fix',payload:{revision:7,consent:true,use_ai:false,ai_consent:false,endpoint:'',model:'',include_images:false,reasoning_effort:null},response:{job_id:'authored-table-guard'}}];const result=await bootSavedReview(saved,{captureTimers:true,expectedMutations:expected});await openSavedReview(result);await showTables(result);await result.dispatch('auto-fix','click');await showTables(result,false);await showTables(result,true);await result.dispatch('next-page','click');await result.dispatch('previous-page','click');assert.equal(result.getNode('show-tables').disabled,true);assert(descendants(cardFor(result,TABLE_ID)).filter(node=>['INPUT','SELECT','TEXTAREA','BUTTON'].includes(node.tagName)).every(node=>node.disabled));assert.deepEqual(result.mutationRequests,expected.map(({url,payload})=>({url,payload})));assert.deepEqual(result.remainingMutations,[]);assert.deepEqual(result.unexpectedRequests,[]);assert.deepEqual(result.requests.filter(item=>/\/(apply|group|auto-fix|accept-draft)$|\/models/.test(item.url)).map(item=>item.url),[base+'/auto-fix']);
});
test('DOM tables: changed plans enforce the exact per-cell 32-header cap while preserving an invalid original',async()=>{
  const saved=tableFixture(),c=saved.decisions.at(-1).table_context;c.cells[0].role='TH';c.cells[0].id='original_header';c.cells[5].headers=Array(33).fill(TABLE_CELLS[0]);syncTableOriginal(saved);
  const result=await bootSavedReview(saved);await openSavedReview(result);await showTables(result);const card=cardFor(result,TABLE_ID);assert.equal(tableFields(card,TABLE_CELLS[5]).headers.length,33);tableSummary(card).value='Changed summary';await result.dispatch(buttonNamed(card,'Save edit'),'click');assert.match(result.getNode('notice').textContent,/at most 32/);expectOnlyMutations(result,[]);
});
test('DOM tables: row spans cannot cross separate row groups bearing the same role label',async()=>{
  const saved=tableFixture(),c=saved.decisions.at(-1).table_context;for(const row of c.rows){row.group='TBody';row.group_key=row.index===0?'tbody:first':'tbody:second';}
  const result=await bootSavedReview(saved);await openSavedReview(result);await showTables(result);const card=cardFor(result,TABLE_ID);tableSummary(card).value='A changed summary';await result.dispatch(buttonNamed(card,'Save edit'),'click');assert.match(result.getNode('notice').textContent,/row group/);expectOnlyMutations(result,[]);
});
test('DOM tables: exact negative-span source withdrawal remains possible without approving a repaired grid',async()=>{
  const saved=tableFixture();saved.decisions.at(-1).table_context.cells[0].row_span=-1;syncTableOriginal(saved);const value=saved.decisions.at(-1).current,url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:TABLE_ID,value};
  const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:editedView(saved,TABLE_ID,value)}]});await openSavedReview(result);await showTables(result);const card=cardFor(result,TABLE_ID);await result.dispatch(buttonNamed(card,'Restore original table'),'click');await result.dispatch(buttonNamed(card,'Save edit'),'click');assert.equal(result.getNode('apply').disabled,true);expectOnlyMutations(result,[{url,payload}]);
});
test('DOM tables: a NUL summary is refused locally before a save',async()=>{
  const result=await bootSavedReview(tableFixture());await openSavedReview(result);await showTables(result);const card=cardFor(result,TABLE_ID);tableSummary(card).value='Invalid\u0000summary';await result.dispatch(buttonNamed(card,'Save edit'),'click');assert.equal(result.getNode('notice').classList.contains('error'),true);expectOnlyMutations(result,[]);
});
test('DOM tables: a 4000-code-point Unicode summary retains every astral character',async()=>{
  const saved=tableFixture(),plan=JSON.parse(saved.decisions.at(-1).current);plan.summary='😀'.repeat(4000);const value=semanticJSON(plan),url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:TABLE_ID,value};
  const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:editedView(saved,TABLE_ID,value)}]});await openSavedReview(result);await showTables(result);tableSummary(cardFor(result,TABLE_ID)).value=plan.summary;await result.dispatch(buttonNamed(cardFor(result,TABLE_ID),'Save edit'),'click');assert.equal(tableSummary(cardFor(result,TABLE_ID)).value,plan.summary);expectOnlyMutations(result,[{url,payload}]);
});
test('DOM tables: unchanged empty source IDs remain exact when another field changes',async()=>{
  const saved=tableFixture(),c=saved.decisions.at(-1).table_context;c.cells[0].id='';c.global_ids.push({id:'',element:TABLE_CELLS[0]});syncTableOriginal(saved);const plan=JSON.parse(saved.decisions.at(-1).current);plan.summary='A separately edited summary';const value=semanticJSON(plan),url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:TABLE_ID,value};
  const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:editedView(saved,TABLE_ID,value)}]});await openSavedReview(result);await showTables(result);tableSummary(cardFor(result,TABLE_ID)).value=plan.summary;await result.dispatch(buttonNamed(cardFor(result,TABLE_ID),'Save edit'),'click');expectOnlyMutations(result,[{url,payload}]);
});
test('DOM tables: textarea CRLF normalization cannot rewrite an unchanged source summary or ID',async()=>{
  const saved=tableFixture(),c=saved.decisions.at(-1).table_context;c.table.summary='Original\r\nsummary\rand guidance';c.cells[0].id='Original\r\nUnicodeÜID';c.global_ids.push({id:c.cells[0].id,element:TABLE_CELLS[0]});syncTableOriginal(saved);const plan=JSON.parse(saved.decisions.at(-1).current);Object.assign(plan.cells[0],{role:'TH',scope:'Column'});const value=semanticJSON(plan),url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:TABLE_ID,value};
  const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:editedView(saved,TABLE_ID,value)}]});await openSavedReview(result);await showTables(result);const card=cardFor(result,TABLE_ID);assert.equal(tableSummary(card).value,'Original\nsummary\nand guidance');assert.equal(tableFields(card,TABLE_CELLS[0]).id.value,'Original\nUnicodeÜID');tableFields(card,TABLE_CELLS[0]).role.value='TH';tableFields(card,TABLE_CELLS[0]).scope.value='Column';await result.dispatch(buttonNamed(card,'Save edit'),'click');expectOnlyMutations(result,[{url,payload}]);
});
test('DOM tables: an unchanged source summary longer than 4000 code points survives an unrelated cell edit',async()=>{
  const saved=tableFixture();saved.decisions.at(-1).table_context.table.summary='😀'.repeat(4001);syncTableOriginal(saved);const plan=JSON.parse(saved.decisions.at(-1).current);Object.assign(plan.cells[0],{role:'TH',scope:'Column'});const value=semanticJSON(plan),url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:TABLE_ID,value};
  const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:editedView(saved,TABLE_ID,value)}]});await openSavedReview(result);await showTables(result);const card=cardFor(result,TABLE_ID);tableFields(card,TABLE_CELLS[0]).role.value='TH';tableFields(card,TABLE_CELLS[0]).scope.value='Column';await result.dispatch(buttonNamed(card,'Save edit'),'click');assert.equal(tableSummary(cardFor(result,TABLE_ID)).value,plan.summary);expectOnlyMutations(result,[{url,payload}]);
});
test('DOM tables: restored raw source summary survives page changes when a saved draft differs only in line endings',async()=>{
  const saved=tableFixture(),item=saved.decisions.at(-1);item.table_context.table.summary='Original\r\nsummary';syncTableOriginal(saved);const draft=JSON.parse(item.current);draft.summary='Original\nsummary';item.value=semanticJSON(draft);saved.unapplied_decisions=[TABLE_ID];const value=item.current,url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:TABLE_ID,value};
  const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:editedView(saved,TABLE_ID,value)}]});await openSavedReview(result);await showTables(result);await result.dispatch(buttonNamed(cardFor(result,TABLE_ID),'Restore original table'),'click');await result.dispatch('next-page','click');await result.dispatch('previous-page','click');await showTables(result,false);await showTables(result,true);await result.dispatch(buttonNamed(cardFor(result,TABLE_ID),'Save edit'),'click');expectOnlyMutations(result,[{url,payload}]);
});
test('DOM tables: saved raw summary line endings survive an unrelated cell edit and local draft recovery',async()=>{
  const saved=tableFixture(),item=saved.decisions.at(-1),plan=JSON.parse(item.current);plan.summary='Previously saved\r\nreview guidance';item.value=semanticJSON(plan);Object.assign(plan.cells[0],{role:'TH',scope:'Column'});const value=semanticJSON(plan),url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:TABLE_ID,value};
  const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:editedView(saved,TABLE_ID,value)}]});await openSavedReview(result);await showTables(result);let card=cardFor(result,TABLE_ID);tableFields(card,TABLE_CELLS[0]).role.value='TH';tableFields(card,TABLE_CELLS[0]).scope.value='Column';await result.dispatch('next-page','click');await result.dispatch('previous-page','click');card=cardFor(result,TABLE_ID);assert.equal(tableSummary(card).value,'Previously saved\nreview guidance');await result.dispatch(buttonNamed(card,'Save edit'),'click');expectOnlyMutations(result,[{url,payload}]);
});
test('DOM tables: an unchanged source NUL summary is preserved without allowing newly authored NUL text',async()=>{
  const saved=tableFixture();saved.decisions.at(-1).table_context.table.summary='Original\u0000summary';syncTableOriginal(saved);const plan=JSON.parse(saved.decisions.at(-1).current);Object.assign(plan.cells[0],{role:'TH',scope:'Column'});const value=semanticJSON(plan),url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:TABLE_ID,value};
  const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:editedView(saved,TABLE_ID,value)}]});await openSavedReview(result);await showTables(result);const card=cardFor(result,TABLE_ID);tableFields(card,TABLE_CELLS[0]).role.value='TH';tableFields(card,TABLE_CELLS[0]).scope.value='Column';await result.dispatch(buttonNamed(card,'Save edit'),'click');expectOnlyMutations(result,[{url,payload}]);
});
test('DOM tables: invalid original header counts beyond source-cell count restore exactly and survive local draft recovery',async()=>{
  const saved=tableFixture(),item=saved.decisions.at(-1),c=item.table_context;c.cells[0].role='TH';c.cells[0].id='original_header';c.global_ids.push({id:'original_header',element:TABLE_CELLS[0]});c.cells[5].headers=Array(33).fill(TABLE_CELLS[0]);syncTableOriginal(saved);const plan=JSON.parse(item.current);plan.cells[5].headers=[TABLE_CELLS[0]];plan.summary='A repaired saved draft';item.value=semanticJSON(plan);saved.unapplied_decisions=[TABLE_ID];const value=item.current,url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:TABLE_ID,value};
  const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:editedView(saved,TABLE_ID,value)}]});await openSavedReview(result);await showTables(result);assert.equal(tableFields(cardFor(result,TABLE_ID),TABLE_CELLS[5]).headers.length,1);await result.dispatch(buttonNamed(cardFor(result,TABLE_ID),'Restore original table'),'click');assert.equal(tableFields(cardFor(result,TABLE_ID),TABLE_CELLS[5]).headers.length,33);await result.dispatch('next-page','click');await result.dispatch('previous-page','click');await showTables(result,false);await showTables(result,true);assert.equal(tableFields(cardFor(result,TABLE_ID),TABLE_CELLS[5]).headers.length,33);await result.dispatch(buttonNamed(cardFor(result,TABLE_ID),'Save edit'),'click');assert.equal(result.getNode('apply').disabled,true);expectOnlyMutations(result,[{url,payload}]);
});
for(const change of ['saved-value','saved-status','saved-revision']){
  test('DOM tables: a delayed mismatched '+change+' response cannot approve a different table plan',async()=>{
    const saved=tableFixture(),value=semanticJSON(tableDraft()),url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:TABLE_ID,value},response=editedView(saved,TABLE_ID,value),delayed=deferredResponse();
    if(change==='saved-value'){const different=tableDraft();different.summary='A different server-side table draft';response.decisions.at(-1).value=semanticJSON(different);}else if(change==='saved-status')response.decisions.at(-1).status='approved';else response.revision=10;
    const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:delayed.promise}]});await openSavedReview(result);await showTables(result);result.getNode('reviewer').value='Authored exact-plan reviewer';await fillTableDraft(result);const accepting=result.dispatch(buttonNamed(cardFor(result,TABLE_ID),'Accept this value'),'click');await settle();delayed.resolve(response);await accepting;assert.match(result.getNode('notice').textContent,/Reopen its control and accept it explicitly/);expectOnlyMutations(result,[{url,payload}]);
  });
}


const FORM_PLAN_ID='form:controls:600:0',FORM_FIELDS=['700:0','701:0','702:0'],FORM_WIDGETS=['710:0','711:0','712:0','713:0'],FORM_ELEMENTS=['800:0','801:0','802:0','803:0'],FORM_PARENT='900:0';
function formFixture(){
 const saved=repairControlsFixture(),widget=(index,page,position,alternative=null)=>({widget:FORM_WIDGETS[index],page,index:position,element:FORM_ELEMENTS[index],structure_path:'Document/Form['+(index+1)+']',alternative,rect:[20,30+index*35,180,55+index*35],widget_flags:4,state_sha256:'a'.repeat(64)});
 const fields=[
  {field:FORM_FIELDS[0],path:'Fields/0/Kids/0',name:'Applicant.full_name',partial_name:'full_name',field_type:'Tx',flags:0,tooltip:null,widgets:[widget(0,1,0),widget(3,2,0)]},
  {field:FORM_FIELDS[1],path:'Fields/0/Kids/1',name:'Applicant.course',partial_name:'course',field_type:'Ch',flags:0,tooltip:'Course selection',widgets:[widget(1,1,1,'Existing course description.')]},
  {field:FORM_FIELDS[2],path:'Fields/0/Kids/2',name:'Applicant.confirmed',partial_name:'confirmed',field_type:'Btn',flags:0,tooltip:'Enrollment approved',widgets:[widget(2,1,2)]}];
 const entry=(index,label)=>({annotation:FORM_WIDGETS[index],subtype:'Widget',element:FORM_ELEMENTS[index],widget:true,source_label:label,target_page:null});
 const pages=[{page:1,tabs:'R',widgets:FORM_WIDGETS.slice(0,3),tag_order:[FORM_WIDGETS[1],FORM_WIDGETS[0],FORM_WIDGETS[2]],annotation_order:[entry(1,'Course selection'),entry(0,null),entry(2,'Enrollment approved'),{annotation:'799:0',subtype:'Link',element:'899:0',widget:false,source_label:'Read the instructions',target_page:2}]},
  {page:2,tabs:null,widgets:[FORM_WIDGETS[3]],tag_order:[FORM_WIDGETS[3]],annotation_order:[entry(3,null)]}];
 const orders=[{parent:FORM_PARENT,page:1,structure_path:'Document/FieldGroup[1]',children:[FORM_ELEMENTS[1],FORM_ELEMENTS[0],FORM_ELEMENTS[2]],labels:[{element:FORM_ELEMENTS[1],widget:FORM_WIDGETS[1],field_name:fields[1].name,page:1},{element:FORM_ELEMENTS[0],widget:FORM_WIDGETS[0],field_name:fields[0].name,page:1},{element:FORM_ELEMENTS[2],widget:FORM_WIDGETS[2],field_name:fields[2].name,page:1}]}];
 const form_context={policy:'reviewed-form-1',fields,pages,orders,limits:{fields:100,widgets:200,pages:50,orders:100,children:200,text_chars:4000,payload_chars:150000}};
 saved.decisions.push({id:FORM_PLAN_ID,kind:'form-controls',current:'',value:'',page:null,element:'600:0',structure_path:'AcroForm',context_sha256:'e'.repeat(64),context_text:'A synthetic reviewed form with two pages, four controls and a fixed local link.',structural_eligible:true,structural_limitations:[],status:'pending',human_touched:false,references:[],form_context});
 return syncFormOriginal(saved);
}
function syncFormOriginal(saved){
 const item=saved.decisions.find(row=>row.id===FORM_PLAN_ID),c=item.form_context;
 item.current=item.value=semanticJSON({fields:c.fields.map(field=>({field:field.field,tooltip:field.tooltip,widgets:field.widgets.map(widget=>({widget:widget.widget,alternative:widget.alternative}))})),pages:c.pages.map(page=>({page:page.page,tabs:page.tabs})),orders:c.orders.map(order=>({parent:order.parent,children:order.children.slice()}))});return saved;
}
function formDraft(saved=formFixture()){
 const plan=JSON.parse(saved.decisions.find(row=>row.id===FORM_PLAN_ID).current);
 plan.fields[0].tooltip='Full name — enter your legal name.\nUse the same name as enrollment.';
 plan.fields[0].widgets[0].alternative='Enter the applicant’s full name.';
 plan.fields[0].widgets[1].alternative='Confirm the applicant’s full name on page 2.';
 plan.fields[1].tooltip='Course selection — choose one course.';plan.fields[1].widgets[0].alternative=null;
 plan.fields[2].tooltip='Enrollment approved — check when approved.';plan.fields[2].widgets[0].alternative='Enrollment approval checkbox.';
 plan.pages.forEach(page=>{page.tabs='S';});plan.orders[0].children=[FORM_ELEMENTS[0],FORM_ELEMENTS[1],FORM_ELEMENTS[2]];return plan;
}
async function showForms(result,checked=true){result.getNode('show-forms').checked=checked;await result.dispatch('show-forms','change');}
function formTooltip(card,id){const field=descendants(card).find(node=>node.dataset?.formField===id);assert(field,'Expected one authored source field.');return descendants(field).find(node=>node.tagName==='TEXTAREA'&&node.getAttribute('aria-label')==='Form tooltip '+id+' '+FORM_PLAN_ID);}
function formAlternative(card,id){const widget=descendants(card).find(node=>node.dataset?.formWidget===id);assert(widget,'Expected one authored source widget.');return descendants(widget).find(node=>node.tagName==='TEXTAREA');}
function formTab(card,page){const row=descendants(card).find(node=>node.dataset?.formPage===String(page));assert(row);return selectsFor(row)[0];}
function formOrderRows(card,parent=FORM_PARENT){const group=descendants(card).find(node=>node.dataset?.formOrder===parent);assert(group);return descendants(group).filter(node=>node.dataset?.formOrderChild);}
function formRaw(card){return {fields:FORM_FIELDS.map((field,index)=>({field,tooltip:formTooltip(card,field).value,widgets:(index===0?[FORM_WIDGETS[0],FORM_WIDGETS[3]]:[FORM_WIDGETS[index]]).map(widget=>({widget,alternative:formAlternative(card,widget).value}))})),pages:[1,2].map(page=>({page,setting:formTab(card,page).value})),order:formOrderRows(card).map(row=>row.dataset.formOrderChild)};}
async function fillFormDraft(result,plan=formDraft()){
 const card=cardFor(result,FORM_PLAN_ID),c=formFixture().decisions.at(-1).form_context;
 for(const field of plan.fields){formTooltip(card,field.field).value=field.tooltip??'';for(const widget of field.widgets)formAlternative(card,widget.widget).value=widget.alternative??'';}
 for(const page of plan.pages)formTab(card,page.page).value=page.tabs===c.pages.find(row=>row.page===page.page).tabs?'keep':'S';
 for(const group of plan.orders){for(const [index,id] of group.children.entries()){let rows=formOrderRows(card,group.parent),position=rows.findIndex(row=>row.dataset.formOrderChild===id);assert(position>=index);while(position>index){await result.dispatch(buttonNamed(rows[position],'Move control up'),'click');rows=formOrderRows(card,group.parent);position--;}}}
 return semanticJSON(plan);
}
function expectFormMutations(result,expected){expectOnlyMutations(result,expected.map(({url,payload})=>({url,payload})));}
function formFixtureOnlyLabel(saved=formFixture()){const plan=JSON.parse(saved.decisions.at(-1).current);plan.fields[0].tooltip='Full name — enter your full name.';return plan;}

test('DOM forms: complete source form controls are opt-in and stay document-wide across pages',async()=>{
 const saved=formFixture(),before=JSON.stringify(saved),result=await bootSavedReview(saved);await openSavedReview(result);assert(!decisionCards(result).some(card=>card.dataset.decisionId===FORM_PLAN_ID));await showForms(result);assert.equal(descendants(cardFor(result,FORM_PLAN_ID)).filter(node=>node.dataset?.formField).length,3);
 await result.dispatch('next-page','click');assert(decisionCards(result).some(card=>card.dataset.decisionId===FORM_PLAN_ID));await showForms(result,false);assert(!decisionCards(result).some(card=>card.dataset.decisionId===FORM_PLAN_ID));assertSavedSnapshotUnchanged(result,saved,before);expectOnlyMutations(result,[]);
});
test('DOM forms: tooltip and descriptions are real multiline textareas with source identities',async()=>{
 const result=await bootSavedReview(formFixture());await openSavedReview(result);await showForms(result);const card=cardFor(result,FORM_PLAN_ID);
 for(const id of FORM_FIELDS)assert.equal(formTooltip(card,id).tagName,'TEXTAREA');for(const id of FORM_WIDGETS)assert.equal(formAlternative(card,id).tagName,'TEXTAREA');assert.equal(descendants(card).filter(node=>node.dataset?.formWidget).length,4);assert.equal(formTooltip(card,FORM_FIELDS[0]).value,'');expectOnlyMutations(result,[]);
});
test('DOM forms: full readonly page sequence includes fixed links and their destination without opening them',async()=>{
 const result=await bootSavedReview(formFixture());await openSavedReview(result);await showForms(result);const card=cardFor(result,FORM_PLAN_ID),entries=descendants(card).filter(node=>node.dataset?.formPageAnnotation);assert.deepEqual(entries.map(node=>node.dataset.formPageAnnotation),[FORM_WIDGETS[1],FORM_WIDGETS[0],FORM_WIDGETS[2],'799:0',FORM_WIDGETS[3]]);assert.match(entries[3].textContent,/Link: Read the instructions — destination page 2/);assert.equal(descendants(entries[3]).length,1);expectOnlyMutations(result,[]);
});
test('DOM forms: tab settings offer only the original setting and explicit document tag order',async()=>{
 const result=await bootSavedReview(formFixture());await openSavedReview(result);await showForms(result);const card=cardFor(result,FORM_PLAN_ID);for(const page of [1,2])assert.deepEqual(formTab(card,page).children.map(node=>node.value),['keep','S']);assert.match(formTab(card,1).children[0].textContent,/\(R\)/);assert.match(formTab(card,2).children[0].textContent,/not specified/);expectOnlyMutations(result,[]);
});
test('DOM forms: source names are readonly identification with no value rename fill or field creation controls',async()=>{
 const saved=formFixture(),result=await bootSavedReview(saved);await openSavedReview(result);await showForms(result);const card=cardFor(result,FORM_PLAN_ID),buttons=descendants(card).filter(node=>node.tagName==='BUTTON').map(node=>node.textContent),text=descendants(card).map(node=>node.textContent).join('\n');
 assert.match(text,/Internal field name: Applicant.full_name/);assert.match(text,/printed label/i);assert(!buttons.some(label=>/add field|delete field|rename|fill|submit|generate|guess|add control|remove control/i.test(label)));assert(!descendants(card).some(node=>node.dataset?.aiId));assert.equal(descendants(card).filter(node=>node.tagName==='INPUT').length,0);expectOnlyMutations(result,[]);
});
test('DOM forms: Save sends the exact whole plan and never accepts applies or calls a provider',async()=>{
 const saved=formFixture(),value=semanticJSON(formDraft()),url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:FORM_PLAN_ID,value},response=editedView(saved,FORM_PLAN_ID,value),result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response}]});await openSavedReview(result);await showForms(result);await fillFormDraft(result);const save=buttonNamed(cardFor(result,FORM_PLAN_ID),'Save edit');save.focus();await result.dispatch(save,'click');assertFreshFocus(result,buttonNamed(cardFor(result,FORM_PLAN_ID),'Save edit'),save);expectOnlyMutations(result,[{url,payload}]);
});
test('DOM forms: named acceptance saves then approves only the exact returned pending revision',async()=>{
 const saved=formFixture(),value=semanticJSON(formDraft()),base='/api/workspaces/'+saved.workspace_id,edited=editedView(saved,FORM_PLAN_ID,value),accepted=structuredClone(edited);accepted.revision=9;Object.assign(accepted.decisions.at(-1),{status:'approved',approved_by:'Authored form reviewer'});
 const expected=[{url:base+'/edit',payload:{revision:7,id:FORM_PLAN_ID,value},response:edited},{url:base+'/approve',payload:{revision:8,id:FORM_PLAN_ID,reviewer:'Authored form reviewer'},response:accepted}],result=await bootSavedReview(saved,{expectedMutations:expected});await openSavedReview(result);await showForms(result);result.getNode('reviewer').value=' Authored form reviewer ';await fillFormDraft(result);await result.dispatch(buttonNamed(cardFor(result,FORM_PLAN_ID),'Accept this value'),'click');expectFormMutations(result,expected);
});
test('DOM forms: unnamed acceptance refuses before saving the form plan',async()=>{
 const result=await bootSavedReview(formFixture());await openSavedReview(result);await showForms(result);await fillFormDraft(result);await result.dispatch(buttonNamed(cardFor(result,FORM_PLAN_ID),'Accept this value'),'click');assert.match(result.getNode('notice').textContent,/Enter your name/);expectOnlyMutations(result,[]);
});
test('DOM forms: restoring the exact original withdraws a saved form draft without repair credit',async()=>{
 const saved=formFixture(),item=saved.decisions.at(-1),value=item.current;item.value=semanticJSON(formDraft());saved.unapplied_decisions=[FORM_PLAN_ID];const url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:FORM_PLAN_ID,value},response=editedView(saved,FORM_PLAN_ID,value);response.unapplied_decisions=[];
 const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response}]});await openSavedReview(result);await showForms(result);await result.dispatch(buttonNamed(cardFor(result,FORM_PLAN_ID),'Restore original form'),'click');assert.match(result.getNode('notice').textContent,/does not repair or approve/);await result.dispatch(buttonNamed(cardFor(result,FORM_PLAN_ID),'Save edit'),'click');assert.equal(result.getNode('apply').disabled,true);expectOnlyMutations(result,[{url,payload}]);
});
test('DOM forms: older saved reviews are not silently given form controls',async()=>{
 const saved=repairControlsFixture(),before=JSON.stringify(saved),result=await bootSavedReview(saved);await openSavedReview(result);await showForms(result);assert(!decisionCards(result).some(card=>card.dataset.decisionId===FORM_PLAN_ID));assert.match(result.getNode('form-summary').textContent,/no form authoring controls/);assertSavedSnapshotUnchanged(result,saved,before);expectOnlyMutations(result,[]);
});
test('DOM forms: a form without a proven reorderable group still exposes labels and page setting',async()=>{
 const saved=formFixture(),c=saved.decisions.at(-1).form_context;c.orders=[];syncFormOriginal(saved);const result=await bootSavedReview(saved);await openSavedReview(result);await showForms(result);const card=cardFor(result,FORM_PLAN_ID);assert(!formTooltip(card,FORM_FIELDS[0]).disabled);assert(!formTab(card,1).disabled);assert.match(descendants(card).map(node=>node.textContent).join('\n'),/no safely reorderable sibling group/);expectOnlyMutations(result,[]);
});
test('DOM forms: navigation movement retains every source child and leaves fixed Link outside the group',async()=>{
 const saved=formFixture(),before=JSON.stringify(saved),result=await bootSavedReview(saved);await openSavedReview(result);await showForms(result);const card=cardFor(result,FORM_PLAN_ID),rows=formOrderRows(card);assert(buttonNamed(rows[0],'Move control up').disabled);assert(buttonNamed(rows.at(-1),'Move control down').disabled);await result.dispatch(buttonNamed(rows[1],'Move control up'),'click');assert.deepEqual(formOrderRows(card).map(row=>row.dataset.formOrderChild),[FORM_ELEMENTS[0],FORM_ELEMENTS[1],FORM_ELEMENTS[2]]);assert.deepEqual(saved.decisions.at(-1).form_context.pages[0].annotation_order.map(row=>row.annotation),[FORM_WIDGETS[1],FORM_WIDGETS[0],FORM_WIDGETS[2],'799:0']);assertSavedSnapshotUnchanged(result,saved,before);expectOnlyMutations(result,[]);
});
test('DOM forms: a moved control retains focus on an enabled fresh movement button',async()=>{
 const result=await bootSavedReview(formFixture());await openSavedReview(result);await showForms(result);const card=cardFor(result,FORM_PLAN_ID),previous=buttonNamed(formOrderRows(card)[1],'Move control up');previous.focus();await result.dispatch(previous,'click');assertFreshFocus(result,buttonNamed(formOrderRows(card)[0],'Move control down'),previous);expectOnlyMutations(result,[]);
});
test('DOM forms: labels descriptions settings and order drafts survive page and collapse changes locally',async()=>{
 const saved=formFixture(),before=JSON.stringify(saved),result=await bootSavedReview(saved);await openSavedReview(result);await showForms(result);await fillFormDraft(result);formTooltip(cardFor(result,FORM_PLAN_ID),FORM_FIELDS[0]).value+=' unsaved';const raw=formRaw(cardFor(result,FORM_PLAN_ID));await result.dispatch('next-page','click');assert.deepEqual(formRaw(cardFor(result,FORM_PLAN_ID)),raw);await showForms(result,false);await showForms(result,true);assert.deepEqual(formRaw(cardFor(result,FORM_PLAN_ID)),raw);assertSavedSnapshotUnchanged(result,saved,before);expectOnlyMutations(result,[]);
});
for(const defect of ['unsafe','stale','missing-context','wrong-policy','wrong-limits','duplicate-field','duplicate-widget','duplicate-tag','unknown-type','wrong-state-hash','missing-page','invalid-widget-page','wrong-source-plan','invalid-order','mixed-order','missing-page-sequence','duplicate-page-annotation','missing-widget-sequence','bad-link-target']){
 test('DOM forms: '+defect+' source capability stays readonly',async()=>{
  const saved=formFixture(),item=saved.decisions.at(-1),c=item.form_context;
  if(defect==='unsafe'){item.structural_eligible=false;item.structural_limitations=['A signed or action-bearing form requires a separate repair.'];}else if(defect==='stale')saved.stale=true;else if(defect==='missing-context')delete item.form_context;else if(defect==='wrong-policy')c.policy='unknown';else if(defect==='wrong-limits')c.limits.widgets=201;else if(defect==='duplicate-field')c.fields[1].field=c.fields[0].field;else if(defect==='duplicate-widget')c.fields[1].widgets[0].widget=c.fields[0].widgets[0].widget;else if(defect==='duplicate-tag')c.fields[1].widgets[0].element=c.fields[0].widgets[0].element;else if(defect==='unknown-type')c.fields[2].field_type='Sig';else if(defect==='wrong-state-hash')c.fields[0].widgets[0].state_sha256='unbound';else if(defect==='missing-page')c.pages.pop();else if(defect==='invalid-widget-page')c.fields[0].widgets[0].page=9;else if(defect==='wrong-source-plan')c.fields[0].tooltip='Different source text';else if(defect==='invalid-order')c.orders[0].children.reverse();else if(defect==='mixed-order')c.orders[0].children[1]='899:0';else if(defect==='missing-page-sequence')delete c.pages[0].annotation_order;else if(defect==='duplicate-page-annotation')c.pages[0].annotation_order[3].annotation=FORM_WIDGETS[0];else if(defect==='missing-widget-sequence')c.pages[0].annotation_order.splice(0,1);else c.pages[0].annotation_order[3].target_page=9;
  const before=JSON.stringify(saved),result=await bootSavedReview(saved);await openSavedReview(result);await showForms(result);for(const label of ['Save edit','Accept this value']){const control=buttonNamed(cardFor(result,FORM_PLAN_ID),label);assert(control.disabled);await result.dispatch(control,'click');}assertSavedSnapshotUnchanged(result,saved,before);expectOnlyMutations(result,[]);
 });
}
for(const defect of ['empty-tooltip','spaces-tooltip','unicode-blank-tooltip','NUL-tooltip','C0-tooltip','surrogate-tooltip','long-tooltip','blank-alternative','NUL-alternative','surrogate-alternative','long-alternative','unsupported-tabs','order-without-tag-setting']){
 test('DOM forms: '+defect+' changed draft refuses before any save',async()=>{
  const saved=formFixture(),result=await bootSavedReview(saved);await openSavedReview(result);await showForms(result);await fillFormDraft(result);const card=cardFor(result,FORM_PLAN_ID),tooltip=formTooltip(card,FORM_FIELDS[1]),alternative=formAlternative(card,FORM_WIDGETS[0]);
  if(defect==='empty-tooltip')tooltip.value='';else if(defect==='spaces-tooltip')tooltip.value=' \t\r\n';else if(defect==='unicode-blank-tooltip')tooltip.value='\u0085\u001c';else if(defect==='NUL-tooltip')tooltip.value='Course\u0000label';else if(defect==='C0-tooltip')tooltip.value='Course\u0007label';else if(defect==='surrogate-tooltip')tooltip.value='Course\ud800label';else if(defect==='long-tooltip')tooltip.value='x'.repeat(4001);else if(defect==='blank-alternative')alternative.value=' \n ';else if(defect==='NUL-alternative')alternative.value='Control\u0000description';else if(defect==='surrogate-alternative')alternative.value='Control\udfffdescription';else if(defect==='long-alternative')alternative.value='x'.repeat(4001);else if(defect==='unsupported-tabs')formTab(card,1).value='C';else formTab(card,1).value='keep';
  await result.dispatch(buttonNamed(card,'Save edit'),'click');assert.equal(result.getNode('notice').classList.contains('error'),true);expectOnlyMutations(result,[]);
 });
}
test('DOM forms: changed names at 4000 Unicode code points retain astral characters and exact text',async()=>{
 const saved=formFixture(),plan=formFixtureOnlyLabel(saved);plan.fields[0].tooltip='Full name '+ '😀'.repeat(3990);assert.equal(Array.from(plan.fields[0].tooltip).length,4000);const value=semanticJSON(plan),url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:FORM_PLAN_ID,value},response=editedView(saved,FORM_PLAN_ID,value),result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response}]});await openSavedReview(result);await showForms(result);formTooltip(cardFor(result,FORM_PLAN_ID),FORM_FIELDS[0]).value=plan.fields[0].tooltip;await result.dispatch(buttonNamed(cardFor(result,FORM_PLAN_ID),'Save edit'),'click');expectOnlyMutations(result,[{url,payload}]);
});
test('DOM forms: source CRLF tab and bare-CR metadata survives unrelated label edits and draft recovery',async()=>{
 const saved=formFixture(),c=saved.decisions.at(-1).form_context;c.fields[1].tooltip='Course\r\nselection\tcopy';c.fields[0].widgets[0].alternative='Source\r\ncontrol\rdescription';syncFormOriginal(saved);const plan=formFixtureOnlyLabel(saved),value=semanticJSON(plan),url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:FORM_PLAN_ID,value},response=editedView(saved,FORM_PLAN_ID,value),result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response}]});await openSavedReview(result);await showForms(result);formTooltip(cardFor(result,FORM_PLAN_ID),FORM_FIELDS[0]).value=plan.fields[0].tooltip;await result.dispatch('next-page','click');await showForms(result,false);await showForms(result,true);assert.equal(formTooltip(cardFor(result,FORM_PLAN_ID),FORM_FIELDS[1]).value,'Course\nselection\tcopy');await result.dispatch(buttonNamed(cardFor(result,FORM_PLAN_ID),'Save edit'),'click');expectOnlyMutations(result,[{url,payload}]);
});
test('DOM forms: existing long raw labels remain untouched while another field is edited',async()=>{
 const saved=formFixture(),c=saved.decisions.at(-1).form_context;c.fields[1].tooltip='Existing '+ 'x'.repeat(4001);syncFormOriginal(saved);const plan=formFixtureOnlyLabel(saved),value=semanticJSON(plan),url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:FORM_PLAN_ID,value},response=editedView(saved,FORM_PLAN_ID,value),result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response}]});await openSavedReview(result);await showForms(result);formTooltip(cardFor(result,FORM_PLAN_ID),FORM_FIELDS[0]).value=plan.fields[0].tooltip;await result.dispatch(buttonNamed(cardFor(result,FORM_PLAN_ID),'Save edit'),'click');expectOnlyMutations(result,[{url,payload}]);
});
test('DOM forms: an unknown original tab name can remain unchanged during a label-only edit',async()=>{
 const saved=formFixture();saved.decisions.at(-1).form_context.pages[0].tabs='A';syncFormOriginal(saved);const plan=formFixtureOnlyLabel(saved),value=semanticJSON(plan),url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:FORM_PLAN_ID,value},response=editedView(saved,FORM_PLAN_ID,value),result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response}]});await openSavedReview(result);await showForms(result);formTooltip(cardFor(result,FORM_PLAN_ID),FORM_FIELDS[0]).value=plan.fields[0].tooltip;await result.dispatch(buttonNamed(cardFor(result,FORM_PLAN_ID),'Save edit'),'click');expectOnlyMutations(result,[{url,payload}]);
});
test('DOM forms: exact original withdrawal preserves incomplete labels and unknown tab setting',async()=>{
 const saved=formFixture(),c=saved.decisions.at(-1).form_context;c.fields[1].tooltip=' \t ';c.pages[0].tabs='UnknownSourceSetting';syncFormOriginal(saved);const item=saved.decisions.at(-1),value=item.current;item.value=semanticJSON(formDraft(saved));saved.unapplied_decisions=[FORM_PLAN_ID];const url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id:FORM_PLAN_ID,value},response=editedView(saved,FORM_PLAN_ID,value);response.unapplied_decisions=[];const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response}]});await openSavedReview(result);await showForms(result);await result.dispatch(buttonNamed(cardFor(result,FORM_PLAN_ID),'Restore original form'),'click');await result.dispatch(buttonNamed(cardFor(result,FORM_PLAN_ID),'Save edit'),'click');expectOnlyMutations(result,[{url,payload}]);
});
test('DOM forms: source names and descriptions are literal text rather than executable markup',async()=>{
 const saved=formFixture(),c=saved.decisions.at(-1).form_context;c.fields[0].name=LITERAL_CONTEXT;c.fields[1].tooltip=LITERAL_CONTEXT;c.fields[0].widgets[0].alternative=LITERAL_CONTEXT;c.orders[0].labels[1].field_name=LITERAL_CONTEXT;c.pages[0].annotation_order[0].source_label=LITERAL_CONTEXT;syncFormOriginal(saved);const result=await bootSavedReview(saved);await openSavedReview(result);await showForms(result);const card=cardFor(result,FORM_PLAN_ID);assert.equal(formTooltip(card,FORM_FIELDS[1]).value,LITERAL_CONTEXT);assert.equal(formAlternative(card,FORM_WIDGETS[0]).value,LITERAL_CONTEXT);assert(descendants(card).some(node=>node.textContent.includes('Internal field name: '+LITERAL_CONTEXT)));expectOnlyMutations(result,[]);
});
for(const defect of ['value','status','revision','context']){
 test('DOM forms: a delayed save response with changed '+defect+' cannot carry acceptance',async()=>{
  const saved=formFixture(),value=semanticJSON(formDraft()),base='/api/workspaces/'+saved.workspace_id,response=editedView(saved,FORM_PLAN_ID,value);
  if(defect==='value'){const different=formDraft();different.fields[0].tooltip+=' Other saved text.';response.decisions.at(-1).value=semanticJSON(different);}else if(defect==='status')response.decisions.at(-1).status='approved';else if(defect==='revision')response.revision=9;else response.decisions.at(-1).context_sha256='f'.repeat(64);
  const expected=[{url:base+'/edit',payload:{revision:7,id:FORM_PLAN_ID,value},response}],result=await bootSavedReview(saved,{expectedMutations:expected});await openSavedReview(result);await showForms(result);result.getNode('reviewer').value='Authored form reviewer';await fillFormDraft(result);await result.dispatch(buttonNamed(cardFor(result,FORM_PLAN_ID),'Accept this value'),'click');expectFormMutations(result,expected);assert(!result.mutationRequests.some(row=>row.url.endsWith('/approve')));
 });
}
for(const interruption of ['page','collapse','checks-tab','newer-typing']){
 test('DOM forms: '+interruption+' during pending acceptance saves only and preserves newer fields',async()=>{
  const saved=formFixture(),value=semanticJSON(formDraft()),base='/api/workspaces/'+saved.workspace_id,gate=deferredResponse(),expected=[{url:base+'/edit',payload:{revision:7,id:FORM_PLAN_ID,value},response:gate.promise}],result=await bootSavedReview(saved,{expectedMutations:expected});await openSavedReview(result);await showForms(result);result.getNode('reviewer').value='Authored form reviewer';await fillFormDraft(result);const accepting=result.dispatch(buttonNamed(cardFor(result,FORM_PLAN_ID),'Accept this value'),'click');await settle();
  if(interruption==='page')await result.dispatch('next-page','click');else if(interruption==='collapse'){await showForms(result,false);await showForms(result,true);}else if(interruption==='checks-tab')await result.dispatch('tab-checks','click');else formTooltip(cardFor(result,FORM_PLAN_ID),FORM_FIELDS[0]).value+=' Newer unsaved text.';
  gate.resolve(editedView(saved,FORM_PLAN_ID,value));await accepting;expectFormMutations(result,expected);assert(!result.mutationRequests.some(row=>row.url.endsWith('/approve')));if(interruption==='newer-typing')assert.match(formTooltip(cardFor(result,FORM_PLAN_ID),FORM_FIELDS[0]).value,/Newer unsaved text/);
 });
}
test('DOM forms: Save failure keeps the entered complete draft available for retry',async()=>{
 const saved=formFixture(),value=semanticJSON(formDraft()),base='/api/workspaces/'+saved.workspace_id,expected=[{url:base+'/edit',payload:{revision:7,id:FORM_PLAN_ID,value},ok:false,response:{error:'Authored form save denied'}}],result=await bootSavedReview(saved,{expectedMutations:expected});await openSavedReview(result);await showForms(result);await fillFormDraft(result);const before=formRaw(cardFor(result,FORM_PLAN_ID));await result.dispatch(buttonNamed(cardFor(result,FORM_PLAN_ID),'Save edit'),'click');assert.deepEqual(formRaw(cardFor(result,FORM_PLAN_ID)),before);assert.match(result.getNode('notice').textContent,/Authored form save denied/);expectFormMutations(result,expected);
});
test('DOM forms: active jobs disable the full form plan after page and panel changes',async()=>{
 const saved=formFixture(),base='/api/workspaces/'+saved.workspace_id,expected=[{url:base+'/auto-fix',payload:{revision:7,consent:true,use_ai:false,ai_consent:false,endpoint:'',model:'',include_images:false,reasoning_effort:null},response:{job_id:'authored-form-guard'}}],result=await bootSavedReview(saved,{captureTimers:true,expectedMutations:expected});await openSavedReview(result);await showForms(result);await result.dispatch('auto-fix','click');await showForms(result,false);await showForms(result,true);await result.dispatch('next-page','click');assert.equal(result.getNode('show-forms').disabled,true);assert(descendants(cardFor(result,FORM_PLAN_ID)).filter(node=>['INPUT','SELECT','TEXTAREA','BUTTON'].includes(node.tagName)).every(node=>node.disabled));assert.deepEqual(result.mutationRequests,expected.map(({url,payload})=>({url,payload})));assert.deepEqual(result.remainingMutations,[]);assert.deepEqual(result.unexpectedRequests,[]);assert.deepEqual(result.requests.filter(item=>/\/(apply|group|auto-fix|accept-draft)$|\/models/.test(item.url)).map(item=>item.url),[base+'/auto-fix']);
});


test('DOM forms: an already saved complete draft accepts by named approval without a second edit request',async()=>{
 const saved=formFixture(),value=semanticJSON(formDraft());saved.decisions.at(-1).value=value;saved.unapplied_decisions=[FORM_PLAN_ID];const url='/api/workspaces/'+saved.workspace_id+'/approve',payload={revision:7,id:FORM_PLAN_ID,reviewer:'Authored form reviewer'},response=structuredClone(saved);response.revision=8;response.decisions.at(-1).status='approved';response.decisions.at(-1).approved_by='Authored form reviewer';
 const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response}]});await openSavedReview(result);await showForms(result);result.getNode('reviewer').value='Authored form reviewer';await result.dispatch(buttonNamed(cardFor(result,FORM_PLAN_ID),'Accept this value'),'click');expectOnlyMutations(result,[{url,payload}]);
});
test('DOM forms: individually bounded labels cannot exceed the complete canonical plan limit',async()=>{
 const saved=formFixture(),c=saved.decisions.at(-1).form_context,template=structuredClone(c.fields[0]);c.fields=Array.from({length:40},(_,index)=>{const field=structuredClone(template);field.field='bulk-field-'+index;field.path='Fields/'+index;field.name='field_'+index;field.partial_name=field.name;field.tooltip=null;field.widgets=[structuredClone(template.widgets[0])];Object.assign(field.widgets[0],{widget:'bulk-widget-'+index,index,page:1,element:'bulk-tag-'+index,structure_path:'Document/Form['+index+']',alternative:null});return field;});
 const ids=c.fields.map(field=>field.widgets[0].widget);c.pages=[{page:1,tabs:'R',widgets:ids,tag_order:ids.slice(),annotation_order:c.fields.map(field=>({annotation:field.widgets[0].widget,subtype:'Widget',element:field.widgets[0].element,widget:true,source_label:null,target_page:null}))}];c.orders=[];syncFormOriginal(saved);const result=await bootSavedReview(saved);await openSavedReview(result);await showForms(result);const card=cardFor(result,FORM_PLAN_ID);
 for(const field of c.fields)formTooltip(card,field.field).value='Name '+ 'x'.repeat(3995);await result.dispatch(buttonNamed(card,'Save edit'),'click');assert.match(result.getNode('notice').textContent,/complete form plan exceeds/i);expectOnlyMutations(result,[]);
});
test('DOM forms: a pending acceptance cannot cross into a second workspace with coinciding control IDs',async()=>{
 const first=formFixture(),second=formFixture();first.source.path='/authored/form-A.pdf';second.workspace_id='f'.repeat(24);second.source.path='/authored/form-B.pdf';second.decisions.at(-1).form_context.fields[0].tooltip='Second form original name';syncFormOriginal(second);const before=JSON.stringify(second),value=semanticJSON(formDraft(first)),url='/api/workspaces/'+first.workspace_id+'/edit',payload={revision:7,id:FORM_PLAN_ID,value},gate=deferredResponse(),result=await bootNavigation(first,second,{expectedMutations:[{url,payload,response:gate.promise}]});
 await openNamedWorkspace(result,'form-A.pdf');await showForms(result);result.getNode('reviewer').value='Authored form reviewer';await fillFormDraft(result);const accepting=result.dispatch(buttonNamed(cardFor(result,FORM_PLAN_ID),'Accept this value'),'click');await settle();await result.dispatch('back','click');await openNamedWorkspace(result,'form-B.pdf');await showForms(result);gate.resolve(editedView(first,FORM_PLAN_ID,value));await accepting;
 assert.equal(result.getNode('document-title').textContent,'form-B.pdf');assert.equal(formTooltip(cardFor(result,FORM_PLAN_ID),FORM_FIELDS[0]).value,'Second form original name');assert.equal(JSON.stringify(second),before);assert.equal(result.getNode('notice').hidden,true);expectOnlyMutations(result,[{url,payload}]);
});


// Appended regression group: the complete prior 540 authored cases stay intact.
const EMPTY_TAG_IDS={first:'empty-tag:701:0',second:'empty-tag:702:0',protected:'empty-tag:703:0'};
function emptyTagFixture(){
 const saved=savedReviewFixture();saved.source.sha256='1'.repeat(64);saved.output.sha256='2'.repeat(64);
 saved.decisions=[];saved.unapplied_decisions=[];saved.repair_findings=[];
 for(const [id,element,parent,content,page,safe] of [[EMPTY_TAG_IDS.first,'701:0','690:0','700:0',1,true],[EMPTY_TAG_IDS.second,'702:0','710:0','711:0',2,true],[EMPTY_TAG_IDS.protected,'703:0','720:0','721:0',null,false]]){
  const structure_path='StructTreeRoot/K[0]/'+element;
  const empty_tag_context={policy:'reviewed-empty-tag-removal-1',source:{element,role:safe?'P':'H1',page,parent,index:1,structure_path,k_shape:'empty-array'},parent:{element:parent,role:'Sect',children:[content,element],nonempty_children:[content],retained_minimum:1},limits:{removals:100,children:200}};
  saved.decisions.push({id,kind:'empty-tag-removal',element,page,structure_path,current:'keep',value:'keep',context_sha256:(safe?'a':'b').repeat(64),context_text:'No embedded text; inspect the original structure.',references:[],status:'pending',structural_eligible:safe,structural_limitations:safe?[]:['A protected heading role cannot be removed here.'],allowed_values:safe?['keep','remove']:['keep'],empty_tag_context,human_touched:false});
 }
 return saved;
}
async function showEmptyTags(result,checked=true){result.getNode('show-empty-tags').checked=checked;await result.dispatch('show-empty-tags','change');}
function emptyChoice(result,id=EMPTY_TAG_IDS.first){return selectsFor(cardFor(result,id))[0];}
async function chooseEmptyRemoval(result,id=EMPTY_TAG_IDS.first,value='remove'){const input=emptyChoice(result,id);input.value=value;await result.dispatch(input,'change');return input;}
function emptyAccepted(saved,id=EMPTY_TAG_IDS.first,value='remove'){const answer=editedView(saved,id,value);const row=answer.decisions.find(item=>item.id===id);row.status='approved';row.approved_by='Authored removal reviewer';return answer;}
function onlyFirstEmpty(saved=emptyTagFixture()){saved.decisions=saved.decisions.filter(item=>item.id===EMPTY_TAG_IDS.first);return saved;}
function emptyText(node){return descendants(node).map(item=>item.textContent).join(' ');}

test('DOM empty tags: controls are opt-in, page-scoped and distinguish protected source occurrences',async()=>{
 const saved=emptyTagFixture(),snapshot=JSON.stringify(saved),result=await bootSavedReview(saved);await openSavedReview(result);
 assert.equal(decisionCards(result).length,0);await showEmptyTags(result);assert.deepEqual(decisionCards(result).map(item=>item.dataset.decisionId),[EMPTY_TAG_IDS.first,EMPTY_TAG_IDS.protected]);
 assert.equal(emptyChoice(result).value,'keep');assert.deepEqual(emptyChoice(result).children.map(item=>item.value),['keep','remove']);assert.equal(emptyChoice(result,EMPTY_TAG_IDS.protected).disabled,true);
 assert.match(result.getNode('empty-tag-summary').textContent,/2 empty-looking.*1 have/);await result.dispatch('next-page','click');assert.deepEqual(decisionCards(result).map(item=>item.dataset.decisionId),[EMPTY_TAG_IDS.second,EMPTY_TAG_IDS.protected]);
 assert.equal(descendants(cardFor(result,EMPTY_TAG_IDS.second)).filter(item=>item.dataset.aiId!==undefined).length,0);assertSavedSnapshotUnchanged(result,saved,snapshot);expectOnlyMutations(result,[]);
});
test('DOM empty tags: source paths and protected descriptions render literally without external navigation',async()=>{
 const saved=onlyFirstEmpty(),row=saved.decisions[0];row.structure_path=row.empty_tag_context.source.structure_path=LITERAL_CONTEXT;row.structural_eligible=false;row.allowed_values=['keep'];row.structural_limitations=[LITERAL_CONTEXT];
 const result=await bootSavedReview(saved);await openSavedReview(result);await showEmptyTags(result);const card=cardFor(result,EMPTY_TAG_IDS.first);assert(emptyText(card).includes(LITERAL_CONTEXT));assert.equal(descendants(card).filter(item=>['A','SCRIPT','IMG'].includes(item.tagName)).length,0);expectOnlyMutations(result,[]);
});
test('DOM empty tags: Save creates only a pending removal and restores fresh button focus',async()=>{
 const saved=onlyFirstEmpty(),id=EMPTY_TAG_IDS.first,url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id,value:'remove'},response=editedView(saved,id,'remove');
 const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response}]});await openSavedReview(result);await showEmptyTags(result);await chooseEmptyRemoval(result);const old=buttonNamed(cardFor(result,id),'Save edit');old.focus();await result.dispatch(old,'click');
 assertFreshFocus(result,buttonNamed(cardFor(result,id),'Save edit'),old);assert.equal(emptyChoice(result).value,'remove');assert.equal(result.getNode('apply').disabled,true);expectOnlyMutations(result,[{url,payload}]);
});
test('DOM empty tags: changed removal requires named acceptance and a separate explicit Apply action',async()=>{
 const saved=onlyFirstEmpty(),id=EMPTY_TAG_IDS.first,base='/api/workspaces/'+saved.workspace_id,edited=editedView(saved,id,'remove'),accepted=emptyAccepted(edited);
 const expected=[{url:base+'/edit',payload:{revision:7,id,value:'remove'},response:edited},{url:base+'/approve',payload:{revision:8,id,reviewer:'Authored removal reviewer'},response:accepted},{url:base+'/apply',payload:{revision:9},allowApply:true,response:{job_id:'authored-empty-tag-apply'}}];
 const result=await bootSavedReview(saved,{captureTimers:true,expectedMutations:expected});await openSavedReview(result);await showEmptyTags(result);result.getNode('reviewer').value=' Authored removal reviewer ';await chooseEmptyRemoval(result);await result.dispatch(buttonNamed(cardFor(result,id),'Accept this removal'),'click');
 assert.equal(result.getNode('apply').disabled,false);assert.deepEqual(result.mutationRequests,expected.slice(0,2).map(({url,payload})=>({url,payload})));await result.dispatch('apply','click');
 assert.deepEqual(result.mutationRequests,expected.map(({url,payload})=>({url,payload})));assert.deepEqual(result.remainingMutations,[]);assert.deepEqual(result.unexpectedRequests,[]);
});
test('DOM empty tags: an already saved removal accepts without another edit request',async()=>{
 const saved=onlyFirstEmpty(),id=EMPTY_TAG_IDS.first;saved.decisions[0].value='remove';saved.unapplied_decisions=[id];const url='/api/workspaces/'+saved.workspace_id+'/approve',payload={revision:7,id,reviewer:'Authored removal reviewer'},response=emptyAccepted(saved);
 const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response}]});await openSavedReview(result);await showEmptyTags(result);result.getNode('reviewer').value='Authored removal reviewer';await result.dispatch(buttonNamed(cardFor(result,id),'Accept this removal'),'click');assert.equal(result.getNode('apply').disabled,false);expectOnlyMutations(result,[{url,payload}]);
});
test('DOM empty tags: absent reviewer cannot save or accept a removal implicitly',async()=>{
 const result=await bootSavedReview(onlyFirstEmpty());await openSavedReview(result);await showEmptyTags(result);await chooseEmptyRemoval(result);await result.dispatch(buttonNamed(cardFor(result,EMPTY_TAG_IDS.first),'Accept this removal'),'click');assert.match(result.getNode('notice').textContent,/Enter your name/);expectOnlyMutations(result,[]);
});
test('DOM empty tags: Keep withdraws a saved removal without acceptance or repair credit',async()=>{
 const saved=onlyFirstEmpty(),id=EMPTY_TAG_IDS.first;saved.decisions[0].value='remove';saved.decisions[0].status='approved';saved.decisions[0].approved_by='Authored removal reviewer';saved.unapplied_decisions=[id];
 const url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id,value:'keep'},response=editedView(saved,id,'keep');response.unapplied_decisions=[];
 const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response}]});await openSavedReview(result);await showEmptyTags(result);assert.equal(result.getNode('apply').disabled,false);await result.dispatch(buttonNamed(cardFor(result,id),'Restore original keep choice'),'click');assert.equal(emptyChoice(result).value,'keep');assert.equal(result.getNode('apply').disabled,true);assert.match(result.getNode('notice').textContent,/does not repair or approve/);
 result.getNode('reviewer').value='Authored removal reviewer';await result.dispatch(buttonNamed(cardFor(result,id),'Accept this removal'),'click');assert.match(result.getNode('notice').textContent,/Save Keep/);await result.dispatch(buttonNamed(cardFor(result,id),'Save edit'),'click');assert.equal(result.getNode('apply').disabled,true);expectOnlyMutations(result,[{url,payload}]);
});
test('DOM empty tags: unsaved choices survive page changes and disclosure cycles without becoming authority',async()=>{
 const result=await bootSavedReview(emptyTagFixture());await openSavedReview(result);await showEmptyTags(result);await chooseEmptyRemoval(result);await result.dispatch('next-page','click');await chooseEmptyRemoval(result,EMPTY_TAG_IDS.second);await showEmptyTags(result,false);await showEmptyTags(result,true);assert.equal(emptyChoice(result,EMPTY_TAG_IDS.second).value,'remove');await result.dispatch('previous-page','click');assert.equal(emptyChoice(result).value,'remove');assert.equal(result.getNode('apply').disabled,true);expectOnlyMutations(result,[]);
});
for(const defect of ['policy','missing-context','source-role','source-id','source-path','source-page','source-shape','index','parent-id','parent-role','parent-children','missing-nonempty','nonempty-self','retained-minimum','removal-limit','children-limit','current','saved-value','allowed-values','context-sha','source-sha']){
 test('DOM empty tags: malformed '+defect+' capability stays read-only',async()=>{
  const saved=onlyFirstEmpty(),row=saved.decisions[0],c=row.empty_tag_context;
  if(defect==='policy')c.policy='unproved';else if(defect==='missing-context')delete row.empty_tag_context;else if(defect==='source-role')c.source.role='Figure';else if(defect==='source-id')c.source.element='999:0';else if(defect==='source-path')c.source.structure_path='Different source';else if(defect==='source-page')c.source.page=true;else if(defect==='source-shape')c.source.k_shape='content-reference';else if(defect==='index')c.source.index=false;else if(defect==='parent-id')c.parent.element='999:0';else if(defect==='parent-role')c.parent.role='Table';else if(defect==='parent-children')c.parent.children.reverse();else if(defect==='missing-nonempty')c.parent.nonempty_children=[];else if(defect==='nonempty-self')c.parent.nonempty_children=[row.element];else if(defect==='retained-minimum')c.parent.retained_minimum=0;else if(defect==='removal-limit')c.limits.removals=101;else if(defect==='children-limit')c.limits.children=201;else if(defect==='current')row.current='remove';else if(defect==='saved-value')row.value='delete-content';else if(defect==='allowed-values')row.allowed_values=['keep','remove','delete-content'];else if(defect==='context-sha')row.context_sha256='unproved';else delete saved.source.sha256;
  const result=await bootSavedReview(saved);await openSavedReview(result);await showEmptyTags(result);const card=cardFor(result,row.id);assert.equal(selectsFor(card)[0].disabled,true);assert.equal(buttonNamed(card,'Save edit').disabled,true);assert.equal(buttonNamed(card,'Accept this removal').disabled,true);expectOnlyMutations(result,[]);
 });
}
for(const interruption of ['page-away-back','collapse-reopen','checks-away-back','newer-choice','newer-choice-then-hide','new-workspace']){
 test('DOM empty tags: '+interruption+' during pending acceptance saves only and preserves later intent',async()=>{
  const saved=onlyFirstEmpty(),id=EMPTY_TAG_IDS.first,base='/api/workspaces/'+saved.workspace_id,gate=deferredResponse(),expected=[{url:base+'/edit',payload:{revision:7,id,value:'remove'},response:gate.promise}],other=onlyFirstEmpty();other.workspace_id='f'.repeat(24);
  const result=await bootSavedReview(saved,{expectedMutations:expected,workspaces:{[saved.workspace_id]:saved,[other.workspace_id]:other},documents:(interruption==='new-workspace'?[saved,other]:[saved]).map(item=>({id:item.workspace_id,title:'Authored review '+item.workspace_id,status:item.status,page_count:2,counts:item.counts}))});if(interruption==='new-workspace')await result.dispatch(result.getNode('documents').children[0],'click');else await openSavedReview(result);await showEmptyTags(result);result.getNode('reviewer').value='Authored removal reviewer';await chooseEmptyRemoval(result);const accepting=result.dispatch(buttonNamed(cardFor(result,id),'Accept this removal'),'click');await settle();
  if(interruption==='page-away-back'){await result.dispatch('next-page','click');await result.dispatch('previous-page','click');}else if(interruption==='collapse-reopen'){await showEmptyTags(result,false);await showEmptyTags(result,true);}else if(interruption==='checks-away-back'){await result.dispatch('tab-checks','click');await result.dispatch('tab-decisions','click');}else if(interruption==='new-workspace'){await result.dispatch('back','click');await result.dispatch(result.getNode('documents').children[1],'click');}else{const field=emptyChoice(result);field.value='keep';field.focus();await result.dispatch(field,'change');if(interruption==='newer-choice-then-hide')await showEmptyTags(result,false);}
  gate.resolve(editedView(saved,id,'remove'));await accepting;expectOnlyMutations(result,expected.map(({url,payload})=>({url,payload})));assert(!result.mutationRequests.some(item=>item.url.endsWith('/approve')));
  if(interruption.startsWith('newer-choice')){if(interruption.endsWith('hide'))await showEmptyTags(result,true);assert.equal(emptyChoice(result).value,'keep');assert.equal(result.getNode('apply').disabled,true);}
 });
}
for(const defect of ['revision','approved-status','changed-value','context','capability','kind','element','source','output','missing-row','original-value']){
 test('DOM empty tags: '+defect+' in delayed Save response cannot gain named acceptance',async()=>{
  const saved=onlyFirstEmpty(),id=EMPTY_TAG_IDS.first,base='/api/workspaces/'+saved.workspace_id,response=editedView(saved,id,'remove'),row=response.decisions[0];
  if(defect==='revision')response.revision=9;else if(defect==='approved-status')row.status='approved';else if(defect==='changed-value')row.value='keep';else if(defect==='context')row.empty_tag_context.parent.children.reverse();else if(defect==='capability')row.structural_eligible=false;else if(defect==='kind')row.kind='title';else if(defect==='element')row.element='999:0';else if(defect==='source')response.source.sha256='9'.repeat(64);else if(defect==='output')response.output.sha256='9'.repeat(64);else if(defect==='missing-row')response.decisions=[];else row.current='remove';
  const expected=[{url:base+'/edit',payload:{revision:7,id,value:'remove'},response}],result=await bootSavedReview(saved,{expectedMutations:expected});await openSavedReview(result);await showEmptyTags(result);result.getNode('reviewer').value='Authored removal reviewer';await chooseEmptyRemoval(result);await result.dispatch(buttonNamed(cardFor(result,id),'Accept this removal'),'click');expectOnlyMutations(result,expected.map(({url,payload})=>({url,payload})));assert(!result.mutationRequests.some(item=>item.url.endsWith('/approve')));assert.equal(result.getNode('apply').disabled,true);
 });
}
test('DOM empty tags: stale Save response is displayed read-only and never approved',async()=>{
 const saved=onlyFirstEmpty(),id=EMPTY_TAG_IDS.first,base='/api/workspaces/'+saved.workspace_id,response=editedView(saved,id,'remove');response.stale=true;const expected=[{url:base+'/edit',payload:{revision:7,id,value:'remove'},response}],result=await bootSavedReview(saved,{expectedMutations:expected});
 await openSavedReview(result);await showEmptyTags(result);result.getNode('reviewer').value='Authored removal reviewer';await chooseEmptyRemoval(result);await result.dispatch(buttonNamed(cardFor(result,id),'Accept this removal'),'click');assert.equal(emptyChoice(result).disabled,true);assert.equal(result.getNode('apply').disabled,true);assert.match(result.getNode('notice').textContent,/stale/);expectOnlyMutations(result,expected.map(({url,payload})=>({url,payload})));
});
test('DOM empty tags: newer Keep during pending approval survives and blocks applying the earlier removal',async()=>{
 const saved=onlyFirstEmpty(),id=EMPTY_TAG_IDS.first;saved.decisions[0].value='remove';saved.unapplied_decisions=[id];const gate=deferredResponse(),url='/api/workspaces/'+saved.workspace_id+'/approve',payload={revision:7,id,reviewer:'Authored removal reviewer'};
 const result=await bootSavedReview(saved,{expectedMutations:[{url,payload,response:gate.promise}]});await openSavedReview(result);await showEmptyTags(result);result.getNode('reviewer').value='Authored removal reviewer';const accepting=result.dispatch(buttonNamed(cardFor(result,id),'Accept this removal'),'click');await settle();const field=emptyChoice(result);field.value='keep';field.focus();await result.dispatch(field,'change');gate.resolve(emptyAccepted(saved));await accepting;
 assert.equal(emptyChoice(result).value,'keep');assert.equal(result.getNode('apply').disabled,true);await result.dispatch('apply','click');assert.match(result.getNode('notice').textContent,/unsaved empty-tag/);expectOnlyMutations(result,[{url,payload}]);
});
test('DOM empty tags: failed save retains the local choice and cannot apply or invoke automatic mode',async()=>{
 const saved=onlyFirstEmpty(),id=EMPTY_TAG_IDS.first,url='/api/workspaces/'+saved.workspace_id+'/edit',payload={revision:7,id,value:'remove'},expected=[{url,payload,ok:false,response:{error:'Authored removal save denied'}}],result=await bootSavedReview(saved,{expectedMutations:expected});
 await openSavedReview(result);await showEmptyTags(result);await chooseEmptyRemoval(result);await result.dispatch(buttonNamed(cardFor(result,id),'Save edit'),'click');assert.equal(emptyChoice(result).value,'remove');assert.match(result.getNode('notice').textContent,/Authored removal save denied/);await result.dispatch('auto-fix','click');assert.match(result.getNode('notice').textContent,/unsaved empty-tag/);expectOnlyMutations(result,[{url,payload}]);
});
test('DOM empty tags: busy jobs keep source removal controls disabled after page and disclosure changes',async()=>{
 const saved=onlyFirstEmpty(),base='/api/workspaces/'+saved.workspace_id,expected=[{url:base+'/auto-fix',payload:{revision:7,consent:true,use_ai:false,ai_consent:false,endpoint:'',model:'',include_images:false,reasoning_effort:null},response:{job_id:'authored-empty-busy'}}],result=await bootSavedReview(saved,{captureTimers:true,expectedMutations:expected});
 await openSavedReview(result);await showEmptyTags(result);await result.dispatch('auto-fix','click');await showEmptyTags(result,false);await showEmptyTags(result,true);assert.equal(result.getNode('show-empty-tags').disabled,true);assert(descendants(cardFor(result,EMPTY_TAG_IDS.first)).filter(item=>['SELECT','BUTTON'].includes(item.tagName)).every(item=>item.disabled));assert.deepEqual(result.mutationRequests,expected.map(({url,payload})=>({url,payload})));assert.deepEqual(result.remainingMutations,[]);assert.deepEqual(result.unexpectedRequests,[]);
});
function smallFontRecord(){return {policy:'bounded-small-font-1',status:'fail',advisory:true,threshold_pt:9,comparison:'strictly-less-than',source_sha256:'2'.repeat(64),findings:[{page:1,effective_pt:8.999999999999,sample:LITERAL_CONTEXT}],uncertain:[{page:2,reasons:['Unknown text mapping']}],coverage:{complete:false,supported_digital_text_only:true,unmeasured_pages:[2]},limitations:['Only proved digital text is measured.'],fix_path:'Increase source font size, inspect wrapping, export a separate PDF and reprocess.'};}
test('DOM small font: bounded measurements are advisory, preserve precise size and offer no formatting action',async()=>{
 const saved=savedReviewFixture();saved.repair_findings=[{id:'small-font',status:'fail',evidence:smallFontRecord()}];const result=await bootSavedReview(saved);await openSavedReview(result);const text=emptyText(result.getNode('repair-findings'));assert.match(text,/not a universal accessibility minimum/);assert.match(text,/strictly below 9/);assert.match(text,/8\.999999999999/);assert.match(text,/could not be measured/);assert(text.includes(LITERAL_CONTEXT));assert.equal(descendants(result.getNode('repair-findings')).filter(item=>item.tagName==='BUTTON'&&!/^Page /.test(item.textContent)).length,0);expectOnlyMutations(result,[]);
});
for(const defect of ['policy','threshold','comparison','advisory']){
 test('DOM small font: unproved '+defect+' record cannot claim current measurement coverage',async()=>{
  const saved=savedReviewFixture(),record=smallFontRecord();if(defect==='policy')record.policy='unproved';else if(defect==='threshold')record.threshold_pt=8;else if(defect==='comparison')record.comparison='less-than-or-equal';else record.advisory=false;saved.repair_findings=[{id:'small-font',status:'needs-review',evidence:record}];const result=await bootSavedReview(saved);await openSavedReview(result);const text=emptyText(result.getNode('repair-findings'));assert.match(text,/no verified current small-text/);assert(!text.includes('recorded text regions measure'));expectOnlyMutations(result,[]);
 });
}
test('DOM empty assessment: advisory candidate facts cannot create or authorize removal controls',async()=>{
 const saved=savedReviewFixture();saved.repair_findings=[{id:'empty-structure-tags',status:'fail',evidence:{policy:'bounded-empty-structure-1',advisory:true,findings:[{role:'P',page:1,editable_candidate:true}],uncertain:[{safely_empty:false,reason:'Protected description'}],coverage:{complete:false},limitations:['Descriptions and content references remain protected.']}}];
 const result=await bootSavedReview(saved);await openSavedReview(result);await showEmptyTags(result);assert.equal(decisionCards(result).length,0);const text=emptyText(result.getNode('repair-findings'));assert.match(text,/not permission to remove/);assert.match(text,/separately proved empty-tag controls/);assert.match(text,/coverage is incomplete/);expectOnlyMutations(result,[]);
});

// New source-preparation authority is independent of every older review profile.
function credentialCopyFixture(){
 const saved=savedReviewFixture();saved.source.sha256='1'.repeat(64);saved.status=saved.historical_status='needs-manual';saved.output=null;saved.decisions=[];saved.unapplied_decisions=[];
 saved.credential_copy={policy:'credential-copy-context-1',workspace_id:saved.workspace_id,source:structuredClone(saved.source),report_sha256:'4'.repeat(64),eligible:true,context_sha256:'5'.repeat(64),assessment:{policy:'bounded-c2pa-associated-file-1',status:'supported',supported:true,context_sha256:'6'.repeat(64),files:[{filename:'CAI_Attachment_File.c2pa',mime_subtype:'/application#2Fx-c2pa-manifest-store',relationship:'C2PA_Manifest',decoded_sha256:'7'.repeat(64)}]}};
 return saved;
}
async function authorizeCredentialCopy(result){result.getNode('credential-copy-confirm').checked=true;await result.dispatch('credential-copy-confirm','change');result.getNode('credential-copy-reviewer').value='Named copy reviewer';await result.dispatch('credential-copy-reviewer','input');}
function credentialPayload(saved){return {revision:saved.revision,source_sha256:saved.source.sha256,context_sha256:saved.credential_copy.context_sha256,allow_remove:true,reviewer:'Named copy reviewer'};}

test('DOM credentials: ordinary reviews have no separate-copy authority or implicit consent',async()=>{
 const result=await bootSavedReview(savedReviewFixture());await openSavedReview(result);assert.equal(result.getNode('credential-copy-panel').hidden,true);assert.equal(result.getNode('credential-copy-confirm').checked,false);assert.equal(result.getNode('credential-copy').disabled,true);expectOnlyMutations(result,[]);
});

test('DOM credentials: actual needs-attention blocked status requires checkbox and a separately named consent',async()=>{
 const result=await bootSavedReview(credentialCopyFixture());await openSavedReview(result);assert.equal(result.getNode('credential-copy-panel').hidden,false);assert.equal(result.getNode('credential-copy-confirm').checked,false);
 result.getNode('credential-copy').disabled=false;await result.dispatch('credential-copy','click');assert.match(result.getNode('notice').textContent,/Explicitly authorize/);result.getNode('credential-copy-confirm').checked=true;await result.dispatch('credential-copy-confirm','change');result.getNode('credential-copy').disabled=false;await result.dispatch('credential-copy','click');assert.match(result.getNode('notice').textContent,/Enter your name/);expectOnlyMutations(result,[]);
});

test('DOM credentials: explicit action sends only exact source/revision/context/name authority and starts a separate job',async()=>{
 const saved=credentialCopyFixture(),url='/api/workspaces/'+saved.workspace_id+'/credential-copy',payload=credentialPayload(saved),expected=[{url,payload,allowCredentialCopy:true,response:{job_id:'a'.repeat(24)}}];
 const result=await bootSavedReview(saved,{captureTimers:true,expectedMutations:expected});await openSavedReview(result);await authorizeCredentialCopy(result);assert.equal(result.getNode('credential-copy').disabled,false);await result.dispatch('credential-copy','click');
 expectOnlyMutations(result,[{url,payload}]);assert.equal(result.getNode('credential-copy-confirm').disabled,true);assert.equal(result.getNode('credential-copy-reviewer').disabled,true);assert.match(result.getNode('notice').textContent,/AI and OCR off/);assert.match(result.getNode('notice').textContent,/no earlier approvals/);
});

for(const defect of ['policy','eligible','stale','published-output','historical-status','source-path','source-hash','context-hash','report-hash','assessment-policy','assessment-status','assessment-supported','assessment-context','no-files','multiple-files']){
 test('DOM credentials: unproved '+defect+' source capability stays read-only',async()=>{
  const saved=credentialCopyFixture(),c=saved.credential_copy,a=c.assessment;
  if(defect==='policy')c.policy='unproved';else if(defect==='eligible')c.eligible=false;else if(defect==='stale')saved.stale=true;else if(defect==='published-output')saved.output=structuredClone(saved.source);else if(defect==='historical-status')saved.historical_status='candidate';else if(defect==='source-path')c.source.path+='other';else if(defect==='source-hash')c.source.sha256='9'.repeat(64);else if(defect==='context-hash')c.context_sha256='unproved';else if(defect==='report-hash')c.report_sha256='unproved';else if(defect==='assessment-policy')a.policy='unproved';else if(defect==='assessment-status')a.status='unsupported';else if(defect==='assessment-supported')a.supported=false;else if(defect==='assessment-context')a.context_sha256='unproved';else if(defect==='no-files')a.files=[];else a.files.push({...a.files[0]});
  const result=await bootSavedReview(saved);await openSavedReview(result);await authorizeCredentialCopy(result);assert.equal(result.getNode('credential-copy').disabled,true);await result.dispatch('credential-copy','click');expectOnlyMutations(result,[]);
 });
}

for(const change of ['uncheck','new-name','new-workspace','new-notes']){
 test('DOM credentials: delayed response preserves later '+change+' intent and cannot take over that review',async()=>{
  const saved=credentialCopyFixture(),other=credentialCopyFixture();other.workspace_id='f'.repeat(24);const gate=deferredResponse(),url='/api/workspaces/'+saved.workspace_id+'/credential-copy',payload=credentialPayload(saved),expected=[{url,payload,allowCredentialCopy:true,response:gate.promise}];
  const result=await bootSavedReview(saved,{captureTimers:true,expectedMutations:expected,workspaces:{[saved.workspace_id]:saved,[other.workspace_id]:other},documents:(change==='new-workspace'?[saved,other]:[saved]).map(item=>({id:item.workspace_id,title:'Selected review',status:item.status,page_count:2,counts:item.counts}))});
  if(change==='new-workspace')await result.dispatch(result.getNode('documents').children[0],'click');else await openSavedReview(result);await authorizeCredentialCopy(result);const pending=result.dispatch('credential-copy','click');await settle();
  if(change==='uncheck'){result.getNode('credential-copy-confirm').checked=false;await result.dispatch('credential-copy-confirm','change');}else if(change==='new-name'){result.getNode('credential-copy-reviewer').value='Later name';await result.dispatch('credential-copy-reviewer','input');}else if(change==='new-workspace'){await result.dispatch('back','click');await result.dispatch(result.getNode('documents').children[1],'click');}else{const extra=result.document.createElement('textarea');extra.value='Later local draft';result.getNode('manual-items').append(extra);}
  gate.resolve({job_id:'a'.repeat(24)});await pending;expectOnlyMutations(result,[{url,payload}]);assert(!result.getNode('notice').textContent.includes('is being checked'));if(change==='uncheck')assert.equal(result.getNode('credential-copy-confirm').checked,false);if(change==='new-name')assert.equal(result.getNode('credential-copy-reviewer').value,'Later name');if(change==='new-workspace')assert.equal(result.getNode('credential-copy-confirm').checked,false);
 });
}

test('DOM credentials: denied creation retains the explicit local fields without granting authority',async()=>{
 const saved=credentialCopyFixture(),url='/api/workspaces/'+saved.workspace_id+'/credential-copy',payload=credentialPayload(saved),result=await bootSavedReview(saved,{expectedMutations:[{url,payload,allowCredentialCopy:true,ok:false,response:{error:'Authored creation refusal'}}]});await openSavedReview(result);await authorizeCredentialCopy(result);await result.dispatch('credential-copy','click');assert.equal(result.getNode('credential-copy-confirm').checked,true);assert.equal(result.getNode('credential-copy-reviewer').value,'Named copy reviewer');assert.match(result.getNode('notice').textContent,/Authored creation refusal/);expectOnlyMutations(result,[{url,payload}]);
});

test('DOM credentials: reopening resets checkbox/name consent for the selected original',async()=>{
 const result=await bootSavedReview(credentialCopyFixture());await openSavedReview(result);await authorizeCredentialCopy(result);await result.dispatch('back','click');await openSavedReview(result);assert.equal(result.getNode('credential-copy-confirm').checked,false);assert.equal(result.getNode('credential-copy-reviewer').value,'');expectOnlyMutations(result,[]);
});

test('DOM credentials: removal history is durable literal evidence and never credential or human approval',async()=>{
 const saved=savedReviewFixture();saved.credential_lineage={path:'private/credential-lineage.json',sha256:'7'.repeat(64)};saved.credential_derivative={status:'credentials-removed-original-not-verified',original:{name:LITERAL_CONTEXT,sha256:'8'.repeat(64)},reviewer:'Named source reviewer',scope:'The original credential was not verified and does not apply to this copy.'};saved.ocr_editor={available:false,changed_count:0,accepted_count:0,limits:['OCR text-editor chaining is not supported for a Content Credentials working copy.']};
 const result=await bootSavedReview(saved);await openSavedReview(result);assert.equal(result.getNode('credential-lineage').hidden,false);assert(result.getNode('credential-lineage-text').textContent.includes(LITERAL_CONTEXT));assert.match(result.getNode('credential-lineage-text').textContent,/not verified/);assert.match(result.getNode('ocr-editor-summary').textContent,/not supported/);assert.equal(result.getNode('show-ocr').disabled,true);assert.equal(result.getNode('original-caption').textContent,'Working copy without credentials');expectOnlyMutations(result,[]);
});

test('DOM credentials: generic automatic consent never becomes content-credentials removal consent',async()=>{
 const saved=credentialCopyFixture(),url='/api/workspaces/'+saved.workspace_id+'/auto-fix',payload={revision:7,consent:true,use_ai:false,ai_consent:false,endpoint:'',model:'',include_images:false,reasoning_effort:null};
 const result=await bootSavedReview(saved,{captureTimers:true,expectedMutations:[{url,payload,response:{job_id:'a'.repeat(24)}}]});await openSavedReview(result);await authorizeCredentialCopy(result);assert.deepEqual(result.mutationRequests,[]);await result.dispatch('auto-fix','click');
 assert.deepEqual(result.mutationRequests,[{url,payload}]);assert.deepEqual(result.remainingMutations,[]);assert.deepEqual(result.unexpectedRequests,[]);assert(!result.requests.some(row=>/\/(apply|group|assist|accept-draft)$|\/models/.test(row.url)));assert(!result.mutationRequests.some(row=>row.url.endsWith('/credential-copy')));assert(!Object.hasOwn(result.mutationRequests[0].payload,'allow_remove'));
});

test('DOM credentials: an unsaved title cannot be silently abandoned for a new source copy',async()=>{
 const saved=credentialCopyFixture();saved.decisions=[{id:'credential-title',kind:'title',current:'Current title',value:'Current title',status:'pending'}];
 const result=await bootSavedReview(saved);await openSavedReview(result);await authorizeCredentialCopy(result);const field=descendants(cardFor(result,'credential-title')).find(node=>node.tagName==='TEXTAREA');field.value='Later unsaved title';await result.dispatch(field,'input');await result.dispatch('credential-copy','click');assert.match(result.getNode('notice').textContent,/Save or restore outstanding/);assert.equal(field.value,'Later unsaved title');expectOnlyMutations(result,[]);
});

test('DOM credentials: saved but unapplied choices remain in the original review and refuse new-copy creation',async()=>{
 const saved=credentialCopyFixture();saved.decisions=[{id:'credential-title',kind:'title',current:'Current title',value:'Saved draft title',status:'pending'}];saved.unapplied_decisions=['credential-title'];
 const result=await bootSavedReview(saved);await openSavedReview(result);await authorizeCredentialCopy(result);await result.dispatch('credential-copy','click');assert.match(result.getNode('notice').textContent,/Save or restore outstanding/);expectOnlyMutations(result,[]);
});

test('DOM credentials: Stop invalidates a pending copy response without starting later polling or opening a result',async()=>{
 const saved=credentialCopyFixture(),gate=deferredResponse(),url='/api/workspaces/'+saved.workspace_id+'/credential-copy',payload=credentialPayload(saved),expected=[{url,payload,allowCredentialCopy:true,response:gate.promise},{url:'/api/stop',payload:{},response:{status:'stopping'}}];
 const result=await bootSavedReview(saved,{captureTimers:true,expectedMutations:expected});await openSavedReview(result);await authorizeCredentialCopy(result);const pending=result.dispatch('credential-copy','click');await settle();await result.dispatch('stop','click');const notice=result.getNode('notice').textContent;gate.resolve({job_id:'a'.repeat(24)});await pending;
 expectOnlyMutations(result,expected.map(({url,payload})=>({url,payload})));assert.match(notice,/PDF Remediator has stopped/);assert.equal(result.getNode('notice').textContent,notice);assert.equal(result.scheduledTimers.length,0);
});

test('DOM credentials: a delayed refusal from the previous review cannot overwrite the current review notice',async()=>{
 const saved=credentialCopyFixture(),other=credentialCopyFixture();other.workspace_id='f'.repeat(24);const gate=deferredResponse(),url='/api/workspaces/'+saved.workspace_id+'/credential-copy',payload=credentialPayload(saved),expected=[{url,payload,allowCredentialCopy:true,ok:false,response:gate.promise}];
 const result=await bootSavedReview(saved,{expectedMutations:expected,documents:[saved,other].map(item=>({id:item.workspace_id,title:'Selected original',status:item.status,page_count:2,counts:item.counts})),workspaces:{[saved.workspace_id]:saved,[other.workspace_id]:other}});await result.dispatch(result.getNode('documents').children[0],'click');await authorizeCredentialCopy(result);const pending=result.dispatch('credential-copy','click');await settle();await result.dispatch('back','click');await result.dispatch(result.getNode('documents').children[1],'click');gate.resolve({error:'Old-source refusal must stay scoped'});await pending;assert.equal(result.getNode('notice').hidden,true);expectOnlyMutations(result,[{url,payload}]);
});

test('DOM credentials: source fingerprint is mandatory even when both displayed bindings omit it',async()=>{
 const saved=credentialCopyFixture();delete saved.source.sha256;delete saved.credential_copy.source.sha256;const result=await bootSavedReview(saved);await openSavedReview(result);await authorizeCredentialCopy(result);assert.equal(result.getNode('credential-copy').disabled,true);expectOnlyMutations(result,[]);
});

test('DOM credentials: a malformed job response cannot start polling or imply successful creation',async()=>{
 const saved=credentialCopyFixture(),url='/api/workspaces/'+saved.workspace_id+'/credential-copy',payload=credentialPayload(saved),result=await bootSavedReview(saved,{captureTimers:true,expectedMutations:[{url,payload,allowCredentialCopy:true,response:{job_id:'unbound'}}]});await openSavedReview(result);await authorizeCredentialCopy(result);await result.dispatch('credential-copy','click');assert.match(result.getNode('notice').textContent,/did not identify a current/);assert.equal(result.scheduledTimers.length,0);expectOnlyMutations(result,[{url,payload}]);
});


function completedCredentialFixture(){
 const saved=savedReviewFixture();saved.workspace_id='b'.repeat(24);saved.source={path:'retained/credential-free.pdf',sha256:'8'.repeat(64)};saved.output={path:'checked/credential-free.pdf',sha256:'9'.repeat(64)};
 saved.credential_lineage={path:'private/credential-lineage.json',sha256:'7'.repeat(64)};saved.credential_derivative={status:'credentials-removed-original-not-verified',original:{name:'Preserved credentialed original.pdf',sha256:'1'.repeat(64)},reviewer:'Named copy reviewer',scope:'The original credential was not verified and does not apply to this copy.'};saved.ocr_editor={available:false,changed_count:0,accepted_count:0,limits:['Credential ancestry retained.']};return saved;
}

for(const navigation of ['home','another-review','direct-workspace','return-original']){
 test('DOM credentials: completed copy cannot take over after explicit '+navigation+' navigation',async()=>{
  const saved=credentialCopyFixture(),finished=completedCredentialFixture(),other=savedReviewFixture();other.workspace_id='f'.repeat(24);other.source.path='retained/other-review.pdf';other.decisions=[{id:'other-title',kind:'title',current:'Other title',value:'Other title',status:'pending'}];
  const jobs=[],documents=[saved,other].map(item=>({id:item.workspace_id,title:'Explicit selected '+item.workspace_id,status:item.status,page_count:2,counts:item.counts})),jobid='a'.repeat(24),url='/api/workspaces/'+saved.workspace_id+'/credential-copy',payload=credentialPayload(saved);
  const result=await bootSavedReview(saved,{captureTimers:true,jobs,documents,workspaces:{[saved.workspace_id]:saved,[other.workspace_id]:other,[finished.workspace_id]:finished},expectedMutations:[{url,payload,allowCredentialCopy:true,response:{job_id:jobid}}]});await result.dispatch(result.getNode('documents').children[0],'click');await authorizeCredentialCopy(result);await result.dispatch('credential-copy','click');assert.equal(result.scheduledTimers.length,1);
  jobs.push({id:jobid,label:'Explicit separate-copy job',status:'running',progress:[],error:null,result:null});
  if(navigation==='direct-workspace')await vm.runInContext("openWorkspace('"+other.workspace_id+"')",result.context);else{await result.dispatch('back','click');if(navigation==='another-review')await result.dispatch(result.getNode('documents').children[1],'click');else if(navigation==='return-original')await result.dispatch(result.getNode('documents').children[0],'click');}
  let draft=null;if(navigation==='another-review'||navigation==='direct-workspace'){draft=descendants(cardFor(result,'other-title')).find(node=>node.tagName==='TEXTAREA');assert.equal(draft.disabled,false);draft.value='Later local title that must survive completion';await result.dispatch(draft,'input');}
  const notice=result.getNode('notice').textContent;documents.push({id:finished.workspace_id,title:'Completed separate copy',status:finished.status,page_count:2,counts:finished.counts});jobs[0]={...jobs[0],status:'done',result:{documents:[{workspace_id:finished.workspace_id,status:finished.status}]}};
  await result.scheduledTimers[0].callback();await settle();assert(!result.requests.some(row=>row.url==='/api/workspaces/'+finished.workspace_id));assert.equal(result.getNode('notice').textContent,notice);expectOnlyMutations(result,[{url,payload}]);
  if(navigation==='home'){assert.equal(result.getNode('dashboard').hidden,false);assert.equal(result.getNode('review').hidden,true);assert(result.getNode('documents').children.some(card=>descendants(card).some(node=>node.textContent==='Completed separate copy')));}else{assert.equal(result.getNode('review').hidden,false);assert.equal(result.getNode('document-title').textContent,navigation==='return-original'?saved.source.path.split(/[\\/]/).at(-1):'other-review.pdf');if(draft){assert.equal(draft.value,'Later local title that must survive completion');assert.equal(draft.disabled,false);assert(descendants(result.getNode('decisions')).includes(draft));}}
 });
}

test('DOM credentials: completion still opens its fresh copy when the initiating review stays selected',async()=>{
 const saved=credentialCopyFixture(),finished=completedCredentialFixture(),jobs=[],documents=[{id:saved.workspace_id,title:'Original selected review',status:saved.status,page_count:2,counts:saved.counts}],jobid='a'.repeat(24),url='/api/workspaces/'+saved.workspace_id+'/credential-copy',payload=credentialPayload(saved),result=await bootSavedReview(saved,{captureTimers:true,jobs,documents,workspaces:{[saved.workspace_id]:saved,[finished.workspace_id]:finished},expectedMutations:[{url,payload,allowCredentialCopy:true,response:{job_id:jobid}}]});
 await openSavedReview(result);await authorizeCredentialCopy(result);await result.dispatch('credential-copy','click');documents.push({id:finished.workspace_id,title:'Completed copy',status:finished.status,page_count:2,counts:finished.counts});jobs.push({id:jobid,label:'Explicit copy',status:'done',progress:[],error:null,result:{documents:[{workspace_id:finished.workspace_id,status:finished.status}]}});await result.scheduledTimers[0].callback();await settle();assert.equal(result.getNode('document-title').textContent,'credential-free.pdf');assert.equal(result.getNode('credential-lineage').hidden,false);assert.equal(result.getNode('credential-copy-confirm').checked,false);assert.match(result.getNode('notice').textContent,/Processing finished/);expectOnlyMutations(result,[{url,payload}]);
});

test('DOM credentials: a delayed completed-dashboard response cannot reopen a copy after Home and another selection',async()=>{
 const saved=credentialCopyFixture(),finished=completedCredentialFixture(),other=savedReviewFixture();other.workspace_id='f'.repeat(24);other.source.path='retained/selected-other.pdf';const jobs=[],documents=[saved,other].map(item=>({id:item.workspace_id,title:'Selected '+item.workspace_id,status:item.status,page_count:2,counts:item.counts})),jobid='a'.repeat(24),url='/api/workspaces/'+saved.workspace_id+'/credential-copy',payload=credentialPayload(saved),result=await bootSavedReview(saved,{captureTimers:true,jobs,documents,workspaces:{[saved.workspace_id]:saved,[other.workspace_id]:other,[finished.workspace_id]:finished},expectedMutations:[{url,payload,allowCredentialCopy:true,response:{job_id:jobid}}]});await result.dispatch(result.getNode('documents').children[0],'click');await authorizeCredentialCopy(result);await result.dispatch('credential-copy','click');
 const gate=deferredResponse();result.remainingReads.push({url:'/api/dashboard',response:gate.promise});const polling=result.scheduledTimers[0].callback();await settle();await result.dispatch('back','click');await result.dispatch(result.getNode('documents').children[1],'click');gate.resolve({documents,jobs:[{id:jobid,label:'Completed separate-copy job',status:'done',progress:[],error:null,result:{documents:[{workspace_id:finished.workspace_id,status:finished.status}]}}]});await polling;await settle();assert.equal(result.getNode('document-title').textContent,'selected-other.pdf');assert(!result.requests.some(row=>row.url==='/api/workspaces/'+finished.workspace_id));expectOnlyMutations(result,[{url,payload}]);
});

// --- opening a long review and describing figures ------------------------------------------------------------

function placeholderNotes(card) {
  return descendants(card).filter(node => String(node.className || '').includes('placeholder-warning'));
}

test('REVIEW HTML: the opening note starts hidden and the decisions panel says what the buttons really do', () => {
  const html = fs.readFileSync(path.join(path.dirname(appPath), 'index.html'), 'utf8');
  assert.match(html, /<p id="opening-note" class="field-note" role="status" hidden>Opening your review\./);
  assert.match(html, /choose “Accept this value” \(it saves what you typed first\)\. “Save edit” only keeps a draft\./);
  assert.doesNotMatch(html, /Save a draft, then accept the value you want/);
});

test('REVIEW opening: a slow review says it is opening, a second click is ignored, and the note clears afterwards', async () => {
  const saved = savedReviewFixture();
  const delayed = deferredResponse();
  const url = '/api/workspaces/' + saved.workspace_id;
  const result = await bootSavedReview(saved, {expectedReads: [{url, response: delayed.promise}]});
  result.getNode('opening-note').hidden = true;
  const card = result.nodes.get('documents').children[0];
  const first = result.dispatch(card, 'click');
  await settle();
  assert.equal(result.getNode('opening-note').hidden, false, 'The person is told the review is opening.');
  await result.dispatch(card, 'click');
  assert.equal(result.requests.filter(request => request.url === url).length, 1, 'A second click on the same review must not start another load.');
  delayed.resolve(saved);
  await first;
  await settle();
  assert.equal(result.getNode('opening-note').hidden, true);
  assert.equal(result.getNode('review').hidden, false);
  assert.equal(result.requests.filter(request => request.url === url).length, 1);
  // Once it has finished, the same review can be opened again normally.
  await result.dispatch('back', 'click');
  await result.dispatch(result.nodes.get('documents').children[0], 'click');
  assert.equal(result.getNode('review').hidden, false);
  assert.equal(result.getNode('opening-note').hidden, true);
});

test('REVIEW figures: a placeholder description is called out in plain words and the note follows what is typed', async () => {
  const saved = savedReviewFixture();
  saved.decisions = [
    {id: 'figure-one', kind: 'figure-description', page: 1, current: 'image 1', value: 'image 1', status: 'pending'},
    {id: 'figure-two', kind: 'figure-description', page: 2, current: 'A bar chart of enrolment by year', value: 'A bar chart of enrolment by year', status: 'pending'},
  ];
  const result = await bootSavedReview(saved);
  await openSavedReview(result);
  const cards = result.getNode('decisions').children;
  assert.equal(cards.length, 2);
  const [placeholderNote] = placeholderNotes(cards[0]);
  assert.match(placeholderNote.textContent, /This looks like a placeholder, not a description of the picture\. Look at the picture on page 1/);
  assert.equal(placeholderNote.hidden, false);
  assert.equal(placeholderNotes(cards[1])[0].hidden, true, 'A real description gets no warning.');
  const field = descendants(cards[0]).find(node => node.tagName === 'TEXTAREA');
  for (const [typed, warned] of [['A photo of the main quad in autumn', false], ['Image 7.', true], ['figure', true], ['quad-photo.JPG', true], ['Figure 3 shows enrolment by year', false]]) {
    field.value = typed;
    await result.dispatch(field, 'input');
    assert.equal(placeholderNote.hidden, !warned, JSON.stringify(typed));
  }
});

function figureFixture() {
  const saved = savedReviewFixture();
  const box = (bbox, status = 'valid') => ({status, bbox, page_box: [0, 0, 400, 600], units: 'PDF default user space'});
  saved.decisions = [
    {id: 'figure-one', kind: 'figure-description', page: 1, element: '38:0', current: 'image 1', value: 'image 1', status: 'pending'},
    {id: 'purpose-one', kind: 'figure-purpose', page: 1, element: '38:0', current: 'Figure', value: 'Figure', status: 'pending',
      allowed_values: ['Figure', 'Artifact'], figure_bbox: box([100, 200, 300, 400])},
    {id: 'figure-two', kind: 'figure-description', page: 2, element: '39:0', current: 'image 2', value: 'image 2', status: 'pending'},
    {id: 'purpose-two', kind: 'figure-purpose', page: 2, element: '39:0', current: 'Figure', value: 'Figure', status: 'pending',
      allowed_values: ['Figure', 'Artifact'], figure_bbox: box([-1, 0, 401, 600], 'invalid')},
    {id: 'figure-three', kind: 'figure-description', page: 2, element: '40:0', current: 'image 3', value: 'image 3', status: 'pending'},
  ];
  return saved;
}

function pictureButton(card) {
  return descendants(card).find(node => node.tagName === 'BUTTON' && node.textContent === 'Show this picture');
}

async function showPicture(result, id, natural = [640, 960]) {
  const card = cardFor(result, id);
  await result.dispatch(pictureButton(card), 'click');
  const picture = descendants(card).find(node => node.tagName === 'IMG');
  picture.naturalWidth = natural[0]; picture.naturalHeight = natural[1];
  await result.dispatch(picture, 'load');
  return {card, picture, frame: descendants(card).find(node => String(node.className) === 'figure-frame')};
}

test('REVIEW figures: a figure with recorded bounds shows its own picture, cropped from the page, only on request', async () => {
  const saved = figureFixture();
  const result = await bootSavedReview(saved);
  await openSavedReview(result);
  const card = cardFor(result, 'figure-one');
  assert.equal(descendants(card).filter(node => node.tagName === 'IMG').length, 0, 'Nothing is loaded until it is asked for.');
  const before = result.requests.length;
  await result.dispatch(pictureButton(card), 'click');
  assert.equal(pictureButton(card).disabled, true);
  assert.deepEqual(result.requests.slice(before).map(request => request.url), ['/api/workspaces/' + saved.workspace_id + '/page?kind=original&page=1']);
  const picture = descendants(card).find(node => node.tagName === 'IMG');
  assert.equal(picture.alt, '');
  picture.naturalWidth = 640; picture.naturalHeight = 960; // 400 x 600 points at 1.6 pixels per point
  await result.dispatch(picture, 'load');
  const frame = descendants(card).find(node => String(node.className) === 'figure-frame');
  // A 200 x 200 point figure fits 360 x 260 at 1.3 pixels per point; the page is drawn at that scale and moved so the figure shows.
  assert.deepEqual(frame.style, {width: '260px', height: '260px'});
  assert.deepEqual(picture.style, {width: '520px', left: '-130px', top: '-260px'});
});

test('REVIEW figures: bounds that run past the page are clamped to the page, and a figure without bounds offers no picture', async () => {
  const result = await bootSavedReview(figureFixture());
  await openSavedReview(result);
  const {picture, frame} = await showPicture(result, 'figure-two');
  assert.deepEqual(frame.style, {width: '173px', height: '260px'});
  assert.deepEqual(picture.style, {width: '173px', left: '0px', top: '0px'});
  assert.equal(pictureButton(cardFor(result, 'figure-three')), undefined, 'No recorded bounds, no guess.');
});

test('REVIEW figures: a page whose shape does not match its recorded bounds is not cropped', async () => {
  const result = await bootSavedReview(figureFixture());
  await openSavedReview(result);
  const {card, frame} = await showPicture(result, 'figure-one', [960, 640]);
  assert.equal(frame, undefined);
  assert.equal(descendants(card).filter(node => node.tagName === 'IMG').length, 0);
  assert.match(descendants(card).map(node => node.textContent).join(' '), /turned or sized differently from its recorded figure bounds/);
});

test('REVIEW figures: figures on one page share one page image and a new review releases it', async () => {
  const saved = figureFixture();
  saved.decisions.push({id: 'figure-four', kind: 'figure-description', page: 1, element: '41:0', current: 'image 4', value: 'image 4', status: 'pending'},
    {id: 'purpose-four', kind: 'figure-purpose', page: 1, element: '41:0', current: 'Figure', value: 'Figure', status: 'pending',
      allowed_values: ['Figure', 'Artifact'], figure_bbox: {status: 'valid', bbox: [10, 10, 110, 60], page_box: [0, 0, 400, 600]}});
  const result = await bootSavedReview(saved);
  await openSavedReview(result);
  const before = result.requests.length;
  await showPicture(result, 'figure-one');
  await showPicture(result, 'figure-four');
  const pageReads = result.requests.slice(before).filter(request => request.url.includes('/page?kind=original&page=1'));
  assert.equal(pageReads.length, 1, 'The page image is fetched once for both figures.');
  await result.dispatch('back', 'click');
  const again = result.requests.length;
  await result.dispatch(result.nodes.get('documents').children[0], 'click');
  await showPicture(result, 'figure-one');
  // The reopened page preview reads page 1 once; the figure then needs its own fresh read because the old image was released.
  assert.equal(result.requests.slice(again).filter(request => request.url.includes('/page?kind=original&page=1')).length, 2);
});

// Check for updates: the page shows the local service's answer as text, and only a github.com page as a plain link that opens outside
// the program. The answer is an HTTP double; no test reaches the network.
const UPDATE_PAGE = 'https://github.com/jasonswrench-beep/PDFRemediator/releases/tag/v0.3.0-alpha.8';
test('Check for updates shows a newer version with its download page as a plain link', async () => {
  const answer = {status: 'available', message: 'PDF Remediator 0.3.0 alpha 8 is available. You have 0.3.0 alpha 7. Installing it over this copy keeps your saved reviews.',
    url: UPDATE_PAGE, link_text: 'Open the download page'};
  const result = await boot({stored: VALID, updateCheck: answer});
  await result.dispatch('update-check', 'click');
  const out = result.getNode('update-result');
  assert.equal(out.hidden, false);
  assert.equal(out.textContent, answer.message);
  assert.equal(out.children.length, 1);
  const [link] = out.children;
  assert.equal(link.tagName, 'A');
  assert.equal(link.textContent, 'Open the download page');
  assert.equal(link.href, UPDATE_PAGE);
  assert.equal(link.target, '_blank');
  assert.equal(link.rel, 'noopener noreferrer');
  assert.equal(result.getNode('update-check').disabled, false, 'The button can be used again.');
  assert(result.requests.some(request => request.url === '/api/update-check' && request.token === VALID));
  assert.equal(result.getNode('notice').hidden, true, 'An update check is not an error.');
});

test('Check for updates never makes a link from an address outside github.com', async () => {
  const answer = {status: 'available', message: 'PDF Remediator 9.9.9 is available.', url: 'https://example.org/setup.exe', link_text: 'Download'};
  const result = await boot({stored: VALID, updateCheck: answer});
  await result.dispatch('update-check', 'click');
  assert.equal(result.getNode('update-result').textContent, answer.message);
  assert.equal(result.getNode('update-result').children.length, 0);
});

test('Check for updates says when this is the newest version, without a link', async () => {
  const answer = {status: 'current', message: 'You have the newest version, PDF Remediator 0.3.0 alpha 8.'};
  const result = await boot({stored: VALID, updateCheck: answer});
  await result.dispatch('update-check', 'click');
  assert.equal(result.getNode('update-result').textContent, answer.message);
  assert.equal(result.getNode('update-result').children.length, 0);
});
