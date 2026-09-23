// Execute the built page's own script against a stub DOM and assert what it
// renders. A page this size fails silently -- a thrown exception in the IIFE
// leaves the frame, the fonts and the filter rail looking perfectly correct
// above an empty list -- so "it loaded" is not a check. Counts are.
//
//   node check.js bundle/archive.html
const fs = require('fs');

const html = fs.readFileSync(process.argv[2], 'utf8');
const bundle = html.match(/<script id="bundle" type="application\/json">([\s\S]*?)<\/script>/)[1];
const code = html.match(/<script>\n([\s\S]*?)<\/script>/)[1];

const parse = h => [...h.matchAll(/<(button|span|p|div)\b[^>]*>/g)].map(m => m[0]);

class El {
  constructor(id) { this.id = id; this._html = ''; this._attrs = {}; this.value = ''; this.checked = false;
    this.scrollTop = 0; this.clientHeight = 600; this.options = []; }
  get innerHTML() { return this._html; }
  set innerHTML(v) { this._html = v; }
  get scrollHeight() { return Math.max(601, (this._html.match(/class="row"/g) || []).length * 60); }
  insertAdjacentHTML(_, h) { this._html += h; }
  addEventListener() {}
  setAttribute(k, v) { this._attrs[k] = v; }
  removeAttribute(k) { delete this._attrs[k]; }
  getAttribute(k) { return this._attrs[k] ?? null; }
  querySelectorAll() { return []; }
  querySelector() { return null; }
  add(o) { this.options.push(o); }
  get textContent() { return this._html; }
}

const els = {};
const get = id => (els[id] ||= new El(id));
els.bundle = new El('bundle');
els.bundle._html = bundle;

global.document = {
  getElementById: get,
  querySelectorAll: () => [],
};
global.Option = function (t, v) { return { t, v }; };
global.setTimeout = (fn) => fn();
global.clearTimeout = () => {};
global.WeakMap = WeakMap;

new Function(code)();

const rows = get('rows')._html;
const nRows = (rows.match(/class="row"/g) || []).length;
const nIcons = (rows.match(/class="ico"/g) || []).length;
const count = get('count')._html;
const tip = get('tip')._html;
const nSlots = get('slot').options.length;
const nTiers = (get('tiers')._html.match(/class="chip"/g) || []).length;

const total = JSON.parse(bundle).items.length;
const fail = [];
const want = (cond, msg) => { if (!cond) fail.push(msg); };

want(nRows === 120, `first page should draw exactly PAGE=120 rows, drew ${nRows}`);
want(nIcons === nRows, `every drawn row should carry an icon: ${nIcons}/${nRows}`);
want(count.includes(total.toLocaleString()), `count line should name all ${total} items, said "${count}"`);
want(nTiers === 2, `two rarity chips expected, got ${nTiers}`);
want(nSlots > 15, `slot list looks short: ${nSlots}`);
want(/class="tipname/.test(tip), 'tooltip did not render a name');
want(/class="statlist"/.test(tip), 'tooltip rendered no stat lines');
want(/class="skillblock"/.test(tip), 'opener should be an item that grants a skill');
want(/Part of /.test(tip), 'opener should belong to a set');
want(!/undefined|\[object/.test(rows + tip), 'rendered markup contains undefined/[object');

console.log(`rows ${nRows}  icons ${nIcons}  slots ${nSlots}  tiers ${nTiers}`);
console.log(`count: ${count.replace(/<[^>]+>/g, '')}`);
console.log('tooltip: ' + (tip.match(/class="tipname[^"]*">([^<]+)/) || [, '?'])[1]);
if (fail.length) { console.error('\nFAIL\n - ' + fail.join('\n - ')); process.exit(1); }
console.log('\nOK');
