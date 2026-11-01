'use strict';

if (Number(process.versions.node.split('.')[0]) < 20) throw new Error('Node.js 20 or newer is required for the plain-evidence tests.');

// Standalone developer regression: the real shipped function plainEvidenceLines, taken out of app.js and run alone.
// It reads only plain data and builds sentences; it touches no page, no service and no PDF.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

const appPath = process.argv[2] || path.resolve(__dirname, '../src/pdf_remediator/web_assets/app.js');
const source = fs.readFileSync(appPath, 'utf8');
const start = source.indexOf('const OCR_GRADE_WORDS=');
const end = source.indexOf('function evidence(data)');
assert.ok(start >= 0 && end > start, 'the evidence code must be in app.js');
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(source.slice(start, end) + '\nthis.plainEvidenceLines=plainEvidenceLines;', sandbox);
const lines = data => Array.from(sandbox.plainEvidenceLines(data));

const RULE = {sure_at_least: 80, counts_words_of_at_least_letters: 3, few_words_below: 8, many_unsure_below: 0.60, some_unsure_below: 0.90};
const row = (page, grade, words, sure) => ({page, grade, words, sure_words: sure, share_sure: words ? Math.round(1000 * sure / words) / 1000 : null});

test('pages the text recognition read unsurely are said one to a line, with how many of their words were confident', () => {
  const said = lines({policy: 'p', rule: RULE, flagged: [row(3, 'poor', 120, 49), row(5, 'check', 200, 170)], not_measured_pages: [], pages_read: 12});
  assert.equal(said[0], 'Page 3: many words were unsure (40 percent of its 120 words were read confidently).');
  assert.equal(said[1], 'Page 5: some words were unsure (85 percent of its 200 words were read confidently).');
  assert.equal(said[2], '12 pages were read in all.');
});

test('the percentage is rounded down, so a page listed for being under a line never reads as sitting on it', () => {
  assert.match(lines({rule: RULE, flagged: [row(1, 'poor', 100, 59)]})[0], /\(59 percent of its 100 words/);
  assert.match(lines({rule: RULE, flagged: [row(1, 'check', 1000, 899)]})[0], /\(89 percent of its 1000 words/);
});

test('a page with too little text, and one with none, are said without a percentage', () => {
  const said = lines({rule: RULE, flagged: [row(2, 'little-text', 5, 5), row(4, 'little-text', 1, 1), row(7, 'no-words', 0, 0)]});
  assert.equal(said[0], 'Page 2: too little text to judge (5 words counted).');
  assert.equal(said[1], 'Page 4: too little text to judge (1 word counted).');
  assert.equal(said[2], 'Page 7: no words were found.');
});

test('pages that could not be measured are listed, one page or several', () => {
  assert.ok(lines({rule: RULE, flagged: [], not_measured_pages: [4]}).includes("The text recognition's confidence could not be measured on page 4."));
  assert.ok(lines({rule: RULE, flagged: [], not_measured_pages: [4, 9, 10]}).includes("The text recognition's confidence could not be measured on pages 4, 9, 10."));
  assert.equal(lines({rule: RULE, flagged: [], not_measured_pages: []}).some(text => text.includes('could not be measured')), false);
});

test('how pages are rated is said once, from the numbers the program used, so it cannot drift from them', () => {
  const rule = lines({rule: RULE, flagged: [row(1, 'poor', 10, 1)]}).find(text => text.startsWith('How pages are rated'));
  assert.ok(rule.includes('at least 80 percent sure'));
  assert.ok(rule.includes('fewer than 3 letters'));
  assert.ok(rule.includes('fewer than 8 counted words'));
  assert.ok(rule.includes('Under 60 percent confident means many words are probably misread, and under 90 percent means some are.'));
  assert.ok(rule.endsWith('never a check that the text is right.'));
  const changed = lines({rule: {...RULE, sure_at_least: 70, many_unsure_below: 0.5}, flagged: []}).find(text => text.startsWith('How pages are rated'));
  assert.ok(changed.includes('at least 70 percent') && changed.includes('Under 50 percent'));
});

test('a rule that is not all numbers is not guessed at: the rating is left out and the pages are still said', () => {
  const said = lines({rule: {sure_at_least: 80}, flagged: [row(3, 'poor', 120, 49)]});
  assert.equal(said.length, 1);
  assert.match(said[0], /^Page 3: many words were unsure/);
});

test('anything else, or anything malformed, gives no sentences, so the recorded data is shown as it was', () => {
  for (const data of [null, undefined, 5, 'text', [], {}, {flagged: 'x', rule: RULE}, {flagged: [], rule: 3}, {a: 1, b: {c: 2}}, {id: 'x', page: 2}]) {
    assert.deepEqual(lines(data), [], JSON.stringify(data));
  }
  const odd = lines({rule: RULE, flagged: [null, {page: 'x'}, {page: 8, grade: 'new-grade', words: 'many'}, row(2, 'poor', 50, 10)]});
  assert.deepEqual(odd.filter(text => text.startsWith('Page ')), ['Page 8: needs a closer look.', 'Page 2: many words were unsure (20 percent of its 50 words were read confidently).']);
});

test('what is said is words only: no braces, quotes from the data, or code', () => {
  const said = lines({rule: RULE, flagged: [row(3, 'poor', 120, 49)], not_measured_pages: [1], pages_read: 1}).join(' ');
  assert.equal(/[{}[\]]|undefined|NaN|null/.test(said), false, said);
});
