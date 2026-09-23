// Run the palette page's own script against a stub DOM and assert what it draws.
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const bundle = html.match(/<script id="bundle" type="application\/json">([\s\S]*?)<\/script>/)[1];
const code = html.match(/<script>\n([\s\S]*?)<\/script>/)[1];

class El {
  constructor(id){ this.id = id; this._html=''; this._attrs={}; this.value=''; this._ls={}; }
  get innerHTML(){ return this._html; } set innerHTML(v){ this._html = v; }
  get textContent(){ return this._html; } set textContent(v){ this._html = v; }
  addEventListener(ev, fn){ (this._ls[ev] ||= []).push(fn); }
  setAttribute(k,v){ this._attrs[k]=v; } removeAttribute(k){ delete this._attrs[k]; }
  getAttribute(k){ return this._attrs[k] ?? null; }
  querySelectorAll(){ return []; } querySelector(){ return null; } select(){}
}
const els = {};
const get = id => (els[id] ||= new El(id));
els.bundle = new El('bundle'); els.bundle._html = bundle;
global.document = { getElementById: get, querySelectorAll: () => [] };
global.setTimeout = fn => fn(); global.clearTimeout = () => {};
global.navigator = {};

new Function(code)();

const B = JSON.parse(bundle);
const secs = get('sections')._html, key = get('key')._html, dt = get('detail')._html;
const nCells = (secs.match(/class="cell"/g) || []).length;
const nOpenSecs = (secs.match(/<details class="sec panel" open>/g) || []).length;
const nSecs = (secs.match(/<details class="sec panel"/g) || []).length;
const nTex = (secs.match(/class="tex"/g) || []).length;
const sheets = new Set([...html.matchAll(/--s(\d+):url\("data:image\/png/g)].map(m => m[1]));
const used = new Set([...secs.matchAll(/var\(--s(\d+)\)/g)].map(m => m[1]));

const fail = []; const want = (c, m) => { if (!c) fail.push(m); };
want(nCells === B.groups.length, `every group should get a cell: ${nCells} vs ${B.groups.length}`);
want(nTex === nCells, `every cell should carry a texture: ${nTex}/${nCells}`);
want(nOpenSecs === 2, `two sections open at rest, got ${nOpenSecs}`);
want(nSecs === 8, `eight sections expected, got ${nSecs}`);
want(sheets.size === B.frames.reduce((m, f) => Math.max(m, f[0] + 1), 0),
     `declared sheets ${sheets.size} != sheets the frames reference`);
want([...used].every(s => sheets.has(s)), `a cell points at a sheet that was never declared`);
want(/class="dtrow"/.test(dt) && /infotabs\/resistance/.test(dt), 'detail did not open on the resistance set');
want((dt.match(/class="dtrow"/g) || []).length === 10, 'the resistance set should list 10 files');
want(/Controls<\/h3>/.test(key) && /Frames<\/h3>/.test(key), 'legend missing');
want(!/undefined|\[object|NaN/.test(secs + dt + key), 'rendered markup contains undefined/NaN');

console.log(`cells ${nCells}  sections ${nSecs} (${nOpenSecs} open)  sheets declared ${sheets.size}, referenced ${used.size}`);
console.log('legend: ' + (key.match(/<b>([\d,]+)<\/b> of <b>([\d,]+)<\/b> elements,\s*from <b>([\d,]+)<\/b>/) || []).slice(1).join(' / '));
if (fail.length){ console.error('\nFAIL\n - ' + fail.join('\n - ')); process.exit(1); }
console.log('\nOK');
