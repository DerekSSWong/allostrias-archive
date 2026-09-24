// Execute the page's own script against a stub DOM and assert the sheet it
// computes. The gate that matters is the last one: _Nurgle's Offensive Ability
// must come out 1975 and Defensive Ability 2399 with exactly the three buffs he
// had running, because those are read off the real character sheet the frozen
// save was showing. A desynced roll or a mis-resolved buff chain still produces
// plausible numbers, so nothing weaker than a known-good total is a check.
const fs = require('fs');
const html = fs.readFileSync(process.argv[2], 'utf8');
const bundle = html.match(/<script id="bundle" type="application\/json">([\s\S]*?)<\/script>/)[1];
const code = html.match(/<script>\n([\s\S]*?)<\/script>/)[1];

class El {
  constructor(){ this._html=''; this._a={}; this.style={}; this.hidden=false; }
  get innerHTML(){ return this._html; } set innerHTML(v){ this._html=v; }
  get textContent(){ return this._html; } set textContent(v){ this._html=v; }
  setAttribute(k,v){ this._a[k]=v; } getAttribute(k){ return this._a[k]??null; }
  removeAttribute(k){ delete this._a[k]; }
  querySelectorAll(){ return []; } querySelector(){ return null; }
  getBoundingClientRect(){ return {left:0,top:0,right:340,bottom:200,width:340,height:200}; }
  addEventListener(){}
}
const els={}; const get=id=>(els[id]||=new El());
els.bundle=new El(); els.bundle._html=bundle;
const handlers={};
global.innerWidth=1600; global.innerHeight=900;
// A WORKING localStorage, so the page's persistence path is EXERCISED rather
// than swallowed by the try/catch that lets it run without one. With no
// `window` at all the page still works -- that is the point of the guards --
// but the gate would then be proving nothing about what it stores.
global.window = { localStorage: (() => { const m = new Map(); return {
  getItem: k => (m.has(k) ? m.get(k) : null),
  setItem: (k, v) => m.set(k, String(v)),
  removeItem: k => m.delete(k) }; })() };
global.document={ getElementById:get, querySelectorAll:()=>[],
  addEventListener:(ev,fn)=>{ (handlers[ev]||=[]).push(fn); } };
new Function(code)();

const B=JSON.parse(bundle);
const fail=[]; const want=(c,m)=>{ if(!c) fail.push(m); };
// Branches no frozen character exercises. Reported, never counted as passes.
const uncovered=[];

const sheet=get('sheet')._html, gear=get('gear')._html, tg=get('toggles')._html;
const rows=(sheet.match(/class="row"/g)||[]).length;
const geo=(gear.match(/class="geo"/g)||[]).length;
const tgs=(tg.match(/class="tg"/g)||[]).length;

want(B.characters.length===6, `6 characters expected, got ${B.characters.length}`);
// EVERY row renders now, fed or not, so the expected count is the whole sheet
// definition -- derived from it rather than pinned, so adding a stat to SHEET
// moves this on its own. `fed` still picks which character opens.
const opener=B.characters.reduce((b,c)=>fed(c)>fed(b)?c:b, B.characters[0]);
// Mirrors the page's own chooser, bucketed sections included: they do not
// vote, because "the most to show" means the character sheet and a pet tab is
// a different subject. If this and the page disagree, the gate checks a
// character that is not the one on screen.
function fed(c){ return B.sheet.reduce((n,[,list,bucket])=>bucket ? n :
  n+list.filter(r=>
    r.k==='attr'||r.k==='pool'||r.k==='ability'||(r.f||[]).some(f=>c.contrib[f])
  ).length, 0); }
const allRows=B.sheet.reduce((n,[,list])=>n+list.length,0);
want(rows===allRows, `page rendered ${rows} rows, the sheet defines ${allRows}`);
want(fed(opener)>=50, `the richest character only feeds ${fed(opener)} rows`);
// Stronger than a count: the rows on screen must BE the sheet definition,
// matched by the section and index the page stamps on each one. A count alone
// passes if a row is dropped and another duplicated.
{
  const want_ids=new Set();
  B.sheet.forEach(([sec,list])=>list.forEach((_,i)=>want_ids.add(`${sec}#${i}`)));
  const got_ids=[...sheet.matchAll(/data-sec="([^"]*)" data-ri="(\d+)"/g)]
    .map(m=>`${m[1].replace(/&amp;/g,'&')}#${m[2]}`);
  want(got_ids.length===new Set(got_ids).size, 'a sheet row rendered twice');
  const missing=[...want_ids].filter(k=>!got_ids.includes(k));
  want(missing.length===0, `rows defined but not rendered: ${missing.slice(0,6).join(', ')}`);
}
// ...and the point of showing them all is the empty ones.
const zeroes=(sheet.match(/class="rv zero"/g)||[]).length;
want(zeroes>0, 'not one row rendered as a zero -- empty stats are still hidden');
// A resist that computes to zero must still render -- that is the hole a sheet
// is read for, and dropping it was a real bug.
want(/Resistances/.test(sheet), 'no resistance section rendered');
want(geo===14, `14 worn items expected on the opener, got ${geo}`);
// Every worn item draws. A relic's icon field is `artifactBitmap`, not
// `bitmap`, and reading only the latter left all four relics blank -- an empty
// tile that looks like a styling problem rather than a missing field.
for (const c of B.characters)
  for (const e of c.equipment){
    want(e.icon !== null && e.icon !== undefined,
         `${c.name}: ${e.slot} "${e.n}" has no icon`);
    want(B.frames[e.icon], `${c.name}: ${e.n} points at frame ${e.icon}, which is not packed`);
  }
// ...and the relics specifically, since they are the ones that were broken and
// the only worn class whose icon comes from a different field.
{
  const relics=B.characters.flatMap(c=>c.equipment.filter(e=>e.slot==='relic'));
  want(relics.length>=4, `only ${relics.length} relics worn; this check is going blind`);
  want(new Set(relics.map(e=>e.icon)).size===relics.length,
       'the relics are sharing an icon, so they are not resolving their own');
}
want(tgs>0, 'no buff toggles rendered');
// The switch is gone; the icon and the name are the control.
want(!/class="sw"/.test(tg) && !/\.sw\{/.test(html), 'the toggle switch is still there');
want(/\.tg \.ico\{[^}]*filter:grayscale\(1\)/.test(html)
     && /\.tg\[aria-pressed="true"\] \.ico\{filter:none\}/.test(html),
     'an off buff is not greyscaled');
want(/\.tg \.tn b\{[^}]*color:var\(--faint\)/.test(html)
     && /\.tg\[aria-pressed="true"\] \.tn b\{color:/.test(html),
     'an off buff\'s text is not dimmed');
// Every buff must paint ITS OWN icon: assert the sprite offset each toggle
// rendered is the one its frame says, so a tile showing the wrong buff's art
// -- or the same art for all of them -- fails rather than merely looks odd.
{
  const o=B.characters.reduce((b,c)=>fed(c)>fed(b)?c:b, B.characters[0]);
  const got=[...tg.matchAll(/background-position:(-?[\d.]+)px (-?[\d.]+)px/g)];
  want(got.length===o.toggles.length,
       `${o.name}: ${o.toggles.length} buffs, ${got.length} icons painted`);
  o.toggles.forEach((t,i)=>{
    const f=B.frames[t.icon];
    want(f, `${t.n} has no frame for icon ${t.icon}`);
    const k=Math.min(28/f[2], 28/f[3], 1);
    const [,x,y]=got[i]||[,NaN,NaN];
    want(Math.abs(+x - -f[0]*k)<0.6 && Math.abs(+y - -f[1]*k)<0.6,
         `${t.n}: icon drawn at ${x},${y}, its frame is at ${-f[0]*k},${-f[1]*k}`);
  });
  // Messenger of War is the devotion the request named: its record declares a
  // devotionbuttons_ bufficon, so it must not share art with anything else.
  const m=o.toggles.find(t=>t.n==='Messenger of War');
  if (m) want(o.toggles.filter(t=>t.icon===m.icon).length===1,
              'Messenger of War is sharing an icon with another buff');
}
// The buffs are INSIDE the character sheet's own frame: under its title band,
// above the stats, with one rule between. Order is positional and the nesting
// is the point, so match the whole run rather than each piece separately --
// three adjacent siblings in the right panel, in the right order.
want(!/rail3/.test(html), 'the third rail is gone; a rule still references it');
want(/grid-template-columns:300px minmax\(0,1fr\);/.test(html),
     'the layout should be two columns now that the buff rail is gone');
const shell=html.slice(0, html.indexOf('<script id="bundle"'));
// `statpanel` names a CSS rule too, and that rule comes first in the file --
// match the element, not the word.
want(/<section class="panel statpanel">\s*<div class="hd"><h2>Character Sheet<\/h2><\/div>\s*<div id="toggles"><\/div>\s*<div class="panelrule"><\/div>\s*<div class="bd">/.test(shell),
     'the buffs are not between the sheet title and the stats');
// The tiles are the whole content now: no frame of their own, no heading, no
// count. Each of the three was a separate instruction and each can regress on
// its own, so each gets its own check.
want(!/<section class="panel">/.test(shell), 'a plain panel still wraps something in the column');
want(!/Buffs/.test(shell), 'the Buffs heading is still there');
want(!/id="tgn"/.test(shell) && !/\$\("tgn"\)/.test(html),
     'the buff count is still in the page');
want(!/ of \$\{ch\.toggles\.length\} on/.test(html), 'the buff count text is still built');
// The rule between them is the game's own thin divider rail, stretched (it
// fades at both ends, so repeating it would stamp a fade mid-panel) and only
// as tall as its ink.
{
  const m=html.match(/\.panelrule\{height:(\d+)px;[^}]*url\("(data:image\/png;base64,[^"]+)"\) center\/100% 100% no-repeat\}/);
  want(m, 'the panel rule is not painted with a stretched divider texture');
  if (m){
    const h=Buffer.from(m[2].slice(m[2].indexOf(',')+1), 'base64');
    want(+m[1]===h.readUInt32BE(20),
         `the rule is ${m[1]}px tall, its texture is ${h.readUInt32BE(20)}px`);
    want(m[2]!==(html.match(/\.rule\{[^}]*url\("(data:image\/png;base64,[^"]+)"/)||[])[1],
         'the panel rule and the tooltip rule are the same texture');
  }
}
want(/#toggles\{display:grid;\s*grid-template-columns:repeat\(auto-fill/.test(html),
     'the buff list is not laid out left to right');
// An aura's icon is on its buff record, not on the skill the player invested
// in, so every toggle having one is the check that the hop is being followed.
for (const c of B.characters)
  want(c.toggles.every(t=>t.icon!==null),
    `${c.name}: toggle without an icon: `
    + JSON.stringify(c.toggles.filter(t=>t.icon===null).map(t=>t.n)));
// ---- the character sheet's frame -----------------------------------------
// The options window. Its four corners 9-slice fine; its two crests sit at the
// MIDDLE of an edge, which is the one place a slice must stretch, so they are
// cut out at build time and pinned back. border-width equals the slice so the
// art is drawn 1:1 and the crests line up with the frame they came from.
{
  const m=new RegExp('\\.statpanel\\{position:relative;\\s*border:(\\d+)px solid transparent;'
                     +'\\s*border-image:url\\("data:image/png;base64,([^"]+)"\\) (\\d+) (\\w+)\\}')
          .exec(html);
  want(m, 'the character sheet is not framed with the options window');
  if (m){
    want(m[1]===m[3],
         `border-width ${m[1]}px but slice ${m[3]} -- the frame is being scaled, `
         + `so the pinned crests will no longer line up with it`);
    want(m[4]!=='fill', 'the frame is filling the panel, covering the mastery slate');
    const b=Buffer.from(m[2],'base64');
    want(b.readUInt32BE(16)===880 && b.readUInt32BE(20)===613,
         `the frame is ${b.readUInt32BE(16)}x${b.readUInt32BE(20)}, not the 880x613 texture`);
  }
  for (const [sel,name] of [['before','top crest'],['after','bottom crest']]){
    const r=new RegExp(`\\.statpanel::${sel}\\{[^}]*width:(\\d+)px;\\s*height:(\\d+)px;\\s*`
                       +`background-image:url\\("data:image/png;base64,([^"]+)"\\)`).exec(html);
    want(r, `the ${name} is not pinned to the panel`);
    if (r){
      const b=Buffer.from(r[3],'base64');
      want(b.readUInt32BE(16)===+r[1] && b.readUInt32BE(20)===+r[2],
           `the ${name} is drawn ${r[1]}x${r[2]} but its sprite is `
           + `${b.readUInt32BE(16)}x${b.readUInt32BE(20)} -- it is being scaled`);
      // it spans the full depth of the edge strip, so it sits flush in it
      want(+r[2]===89, `the ${name} is ${r[2]}px deep; the edge strip is 89px`);
    }
  }
  want(/\.statpanel::before, \.statpanel::after\{[^}]*left:50%;\s*transform:translateX\(-50%\)/
       .test(html), 'the crests are not centred on their edge');
  // Same padding-box trap: without the border width in the offset, the crests
  // float 89px inside the frame, in the middle of the sheet.
  for (const [sel, side] of [['before','top'], ['after','bottom']]){
    const r=new RegExp(`\\.statpanel::${sel}\\{${side}:calc\\((\\d+)px - (\\d+)px\\)`).exec(html);
    want(r, `the ${side} crest offset does not account for the border width`);
    if (r) want(+r[2]===+m[3],
      `the ${side} crest pulls back ${r[2]}px but the border is ${m[3]}px -- it will `
      + `sit ${+m[3]-+r[2]}px inside the frame instead of on it`);
  }
}
// ---- the sheet's title sits in the frame's own title band ----------------
// The brown strip between the last two gold rules of the top border, under
// the crest. Both bounds are measured off the texture at build time; assert
// the title lands inside the border and inside that band.
{
  const t=/\.statpanel > \.hd\{position:absolute;[^}]*top:calc\((\d+)px - (\d+)px\);\s*height:(\d+)px/
          .exec(html);
  want(t, 'the character sheet title is not placed in the frame band');
  const sb=/\.statpanel\{position:relative;\s*border:(\d+)px solid transparent/.exec(html);
  want(sb, 'the character sheet has no border width to place the title against');
  if (t && sb){
    const [ , top, back, height ] = t;
    want(+back===+sb[1],
         `the title pulls back ${back}px but the border is ${sb[1]}px -- `
         + `it will sit inside the frame instead of on it`);
    want(+top + +height <= +sb[1],
         `the title band is ${top}..${+top + +height} but the border is only ${sb[1]}px deep`);
    want(+height >= 10, `a ${height}px title band is not the brown strip`);
  }
  want(/\.statpanel > \.hd\{[^}]*border-bottom:0/.test(html),
       'the title still carries the panel header rule over the frame');
}
// ---- the mastery / equipment panel frame ---------------------------------
// The HUD menu folder, and it MUST be the cropped rectangle. The raw texture
// is 174x100 with a clasp at x<21 and a notch at x>=165, both at mid-height,
// where a 9-slice has nowhere to put them but repeated down the edge. Read the
// PNG's own IHDR rather than trusting the build: 144x100 is the crop.
{
  const m=/details\.panel\{[^}]*border-image:url\("data:image\/png;base64,([^"]+)"\)\s*(\d+) fill/
          .exec(html);
  want(m, 'the panels are not framed with the menu-folder texture');
  if (m){
    const b=Buffer.from(m[1],'base64');
    want(b.slice(1,4).toString()==='PNG', 'the panel frame is not a PNG');
    const w=b.readUInt32BE(16), h=b.readUInt32BE(20);
    want(w===144 && h===100,
         `the frame texture is ${w}x${h}; cropped it is 144x100 -- 174 wide means `
         + `the clasp and notch are still in it and will repeat down the edges`);
    want(+m[2]===2, `the slice is ${m[2]}px; the folder's gold rule is 2px`);
  }
  // The two ornaments the crop removed are NOT lost -- each is pinned once to
  // the middle of its edge. Their sizes are the texture's own bounding boxes,
  // read back out of the PNG so a re-crop that clips them fails here.
  const orn=(sel,wantW,wantH,name)=>{
    const r=new RegExp(`details\\.panel::${sel}\\{[^}]*width:(\\d+)px; height:(\\d+)px;\\s*`
                       +`background-image:url\\("data:image/png;base64,([^"]+)"\\)`).exec(html);
    want(r, `the ${name} is not drawn on the panel`);
    if (!r) return;
    const b=Buffer.from(r[3],'base64');
    const w=b.readUInt32BE(16), h=b.readUInt32BE(20);
    want(w===wantW && h===wantH,
         `the ${name} sprite is ${w}x${h}, its bounding box in the texture is ${wantW}x${wantH}`);
    want(+r[1]===w && +r[2]===h,
         `the ${name} is drawn ${r[1]}x${r[2]} but the sprite is ${w}x${h} -- it is being scaled`);
  };
  orn('before', 21, 52, 'clasp');
  orn('after', 9, 15, 'notch');
  // Centred on their edge, and FLUSH with it: the overhang equals the sprite's
  // own width, so the ornament sits wholly outside the panel and never laps
  // over the interior -- which is where it sits in the texture.
  want(/details\.panel::before, details\.panel::after\{[^}]*top:50%/.test(html),
       'the ornaments are not centred on their edge');
  // ⚠️ THE OFFSET MUST INCLUDE THE BORDER WIDTH. An absolutely positioned
  // child is laid out against the PADDING box, so an offset of just the
  // sprite's width leaves it lapping one border-width over the panel.
  const fm=/details\.panel\{position:relative;\s*border:(\d+)px solid transparent/.exec(html);
  want(fm, 'the folder panels have no border width to offset against');
  const fslice=fm ? +fm[1] : 0;
  let claspOut=0;
  for (const [sel, side, name] of [['before','left','clasp'], ['after','right','notch']]){
    const r=new RegExp(`details\\.panel::${sel}\\{${side}:calc\\(-(\\d+)px - (\\d+)px\\);`
                       +`\\s*width:(\\d+)px`).exec(html);
    want(r, `the ${name} offset does not account for the border width`);
    if (r){
      want(+r[2]===fslice, `the ${name} offsets by a ${r[2]}px border; it is ${fslice}px`);
      want(r[1]===r[3], `the ${name} overhangs ${r[1]}px but is ${r[3]}px wide -- it laps `
           + `${+r[3]-+r[1]}px over the panel instead of sitting flush outside it`);
      if (side==='left') claspOut = +r[1] + +r[2];
    }
  }
  // ...and the page must have room for that overhang, or it opens a scrollbar.
  const pad=/--s5:(\d+)px/.exec(html);
  want(pad && +pad[1] >= claspOut,
       `.wrap's side padding is ${pad && pad[1]}px but the clasp hangs ${claspOut}px outside it`);
  want(/\.wrap\{[^}]*padding:var\(--s4\) var\(--s5\)/.test(html),
       'the page padding no longer clears the ornaments');
}
// The frame is mainmenu/borderthin -- an 8px corner, not border's 25px.
want(/border:8px solid transparent/.test(html), 'the thin border was not applied');
want(/statpanel/.test(html) && /center top \/ 100% auto/.test(html),
     'the stats panel is not carrying the mastery-selection slate');
// No badges on a row: not the SOLVED mark, not the difficulty penalty. Both
// still exist -- the first in the hover detail, the second folded into the
// number -- but neither prints beside the label any more.
want(!/class="v"|class="d"/.test(sheet), 'a row is still rendering a badge');
want(!/SOLVED/.test(sheet), 'the SOLVED badge is still on the rows');
want(/\.sheet\{columns:5;/.test(html), 'the character sheet is not five columns');
// The penalty must still be IN the number now that its label is gone.
// Recompute one resist the way the page does -- opener, default toggles on --
// and require the rendered text to match, penalty included. Dropping the badge
// AND the subtraction would otherwise look identical here.
{
  const dflt=new Set(opener.toggles.filter(t=>t.kind==='toggle'||t.kind==='granted')
                                   .map(t=>t.id));
  const T={}; for (const [f,rs] of Object.entries(opener.contrib))
    for (const [v,,tid] of rs) if(!tid||dflt.has(tid)) T[f]=(T[f]||0)+v;
  const TOP=new Set(['Fire','Cold','Lightning','Acid','Pierce']);
  const PEN=[[0,0],[-25,0],[-50,-25]][opener.difficulty]||[0,0];
  const res=B.sheet.find(([n])=>n==='Resistances');
  let checked=0;
  res[1].forEach((r,i)=>{
    const pen=r.label==='Physical'?0:(TOP.has(r.label)?PEN[0]:PEN[1]);
    if (!pen) return;                       // nothing to prove on this row
    const exp=(r.f||[]).reduce((a,f)=>a+(T[f]||0),0)+pen;
    // ...held to the cap the game prints it at: 80 plus the type's own and the
    // all-type max-resist bonus.
    const cap=80+(T[r.f[0]+'MaxResist']||0)+(T.defensiveAllMaxResist||0);
    const shown=Math.min(exp, cap);
    // The verdict marker sits in front of the label now, so the anchor is the
    // row's own data-ri and the label that follows it, not their adjacency.
    const m=sheet.match(new RegExp(
      `data-ri="${i}"[^>]*>[\\s\\S]*?<span class="rl">${r.label}</span>[\\s\\S]*?`
      +`class="rv[^"]*">(-?[\\d,.]+)%`));
    want(m, `${r.label} did not render a percentage`);
    if (m){ checked++;
      want(m[1].replace(/,/g,'')===String(shown),
           `${r.label} renders ${m[1]}%, expected ${shown}% (${exp}% with the ${pen}% penalty, cap ${cap}%)`); }
  });
  // Control resists take NO difficulty penalty. They share the resist row kind,
  // and the damage resists' bottom-row 25 was once taken off every one of them.
  const ctl=B.sheet.find(([n])=>n==='Control Resistances');
  ctl[1].forEach((r,i)=>{
    const exp=(r.f||[]).reduce((a,f)=>a+(T[f]||0),0);
    const m=sheet.match(new RegExp(`data-sec="Control Resistances" data-ri="${i}"[^>]*>`
      +`[\\s\\S]*?class="rv[^"]*">(-?[\\d,.]+)%`));
    want(m && m[1].replace(/,/g,'')===String(exp),
         `${r.label} renders ${m&&m[1]}%, but its sources sum to ${exp}% and control resists take no penalty`);
  });
  want(checked>0, `${opener.name} is on difficulty ${opener.difficulty}; no resist `
       + `carries a penalty, so nothing here proves the penalty survived the badge`);
}
want(!/undefined|NaN|\[object/.test(sheet+gear+tg), 'rendered markup contains undefined/NaN');
want(B.characters.every(c=>c.refused.length===0), 'a character has a refused roll');

// ---- the real gate: recompute _Nurgle exactly as the page does -------------
const N=B.characters.find(c=>c.name==='Nurgle');
want(!!N, 'Nurgle not in the bundle');
want(N.toggles.every(t=>!/^[a-z0-9_]+$/.test(t.n)), 'a toggle is showing a filename: '+JSON.stringify(N.toggles.map(t=>t.n)));
// He had three buffs up. Only ONE of them carries Offensive Ability, and that
// asymmetry is itself load-bearing: Path of the Three has no ability fields
// anywhere and Eldritch Ruminations' buff record carries neither OA nor DA, so
// they must be present as toggles that move nothing. A build that quietly gave
// either of them a value would still hit 1975 by cancelling somewhere else.
const named=n=>N.toggles.find(t=>t.n===n);
want(!!named('Presence of Virtue'), 'Presence of Virtue is not a toggle: '
  + JSON.stringify(N.toggles.map(t=>t.n)));
// A relic's granted aura reaches its stats through buffSkillName, and that
// buff record is NOT in the catalogue's skill index -- reading stats from the
// catalogue made this aura look empty and it silently lost its switch.
const er=named('Eldritch Ruminations');
want(!!er, 'Eldritch Ruminations is missing from the toggles');
want(er && (N.contrib.offensivePoisonModifier||[]).some(([v,,tid])=>tid===er.id && v===155),
     'Eldritch Ruminations should carry +155% Acid');
want(er && (N.contrib.characterManaLimitReserve||[]).some(([,,tid])=>tid===er.id),
     'Eldritch Ruminations reserves energy and that cost should be a contribution');
// ...and it still must not touch OA or DA, which is why it did not change 1975.
for (const f of ['characterOffensiveAbility','characterDefensiveAbility'])
  want(!(N.contrib[f]||[]).some(([,,tid])=>tid===er.id), `Eldritch Ruminations must not feed ${f}`);

// ---- what a buff tile says its level is -----------------------------------
// The second line is the skill's LEVEL now, not the word for what kind of buff
// it is. Both halves are the check: the kind must be gone, and the number must
// be the level the STATS were read at, so a tile cannot advertise one level
// while the sheet folded in another.
{
  const lines=[...tg.matchAll(/<span>Lvl (\d+)([^<]*)<\/span>/g)];
  want(lines.length===opener.toggles.length,
       `${opener.name}: ${opener.toggles.length} buffs, ${lines.length} levels printed`);
  opener.toggles.forEach((t,i)=>want(lines[i] && +lines[i][1]===t.eff,
    `${t.n}: the tile says Lvl ${lines[i]&&lines[i][1]}, its stats were read at ${t.eff}`));
  for (const k of new Set(B.characters.flatMap(c=>c.toggles.map(t=>t.kind))))
    want(!new RegExp(`<span>${k}`).test(tg), `a tile still names its kind ("${k}")`);
}
// ⚠️ A BOUND DEVOTION SKILL IS NOT LEVEL 1 -- the save says 1 for every one of
// them and the level is earned separately. Pinned BY NAME, because the reading
// this replaces produced a perfectly plausible "lvl 1" on every celestial
// power and nothing about the page looked wrong. Dryad's Blessing tops out at
// 25 and Giant's Blood at 20, and Nurgle has both maxed.
{
  const at=n=>(N.toggles.find(t=>t.n===n)||{}).eff;
  want(at("Dryad's Blessing")===25, `Nurgle's Dryad's Blessing is level ${at("Dryad's Blessing")}, not 25`);
  want(at("Giant's Blood")===20, `Nurgle's Giant's Blood is level ${at("Giant's Blood")}, not 20`);
  want(B.characters.some(c=>c.toggles.some(t=>t.kind==='duration'&&t.eff>1)),
       'not one devotion buff is above level 1; the earned level is not being read');
}
// An item grants its aura at ITS OWN level, which the Equipment panel already
// printed. The two panels reading the same record must not disagree -- they did:
// the tooltip said "(level 2)" while the buff pane folded the aura in at 1.
for (const c of B.characters)
  for (const t of c.toggles.filter(t=>t.kind==='granted')){
    const e=c.equipment.find(e=>e.n===t.from);
    want(e && +e.grantLv===t.eff, `${c.name}: ${t.from} grants at level `
      + `${e&&e.grantLv} but ${t.n} folded in at ${t.eff}`);
  }

// ---- the drawer's two tabs ------------------------------------------------
// Neither is scaled: each state's box is exactly its own texture's size, read
// back off the PNG header rather than compared against a number typed here.
// The two textures ARE different sizes (60x244 open, 20x40 close) and that is
// deliberate -- the big one is mostly filigree around a rune plate the size of
// the small one -- so the check is "drawn 1:1", not "drawn the same".
{
  const png=b64=>{ const h=Buffer.from(b64.slice(b64.indexOf(',')+1), 'base64');
    return {w:h.readUInt32BE(16), h:h.readUInt32BE(20)}; };
  const at=re=>html.match(re);
  const open=at(/\.railtab\{flex:none; width:(\d+)px; height:(\d+)px;[\s\S]{0,120}?background:url\("(data:image\/png;base64,[^"]+)"\) center\/contain no-repeat\}/);
  want(open, 'the open tab is not painted at a stated size');
  if (open){
    const a=png(open[3]);
    want(+open[1]===a.w && +open[2]===a.h,
         `the open tab is ${open[1]}x${open[2]}, its texture is ${a.w}x${a.h}`);
  }
  const shut=at(/\.rail\[data-open="1"\] \.railtab\{width:(\d+)px; height:(\d+)px;\s*\n?\s*background-image:url\("(data:image\/png;base64,[^"]+)"\)\}/);
  want(shut, 'the close tab is not painted at a stated size');
  if (shut){
    const b=png(shut[3]);
    want(+shut[1]===b.w && +shut[2]===b.h,
         `the close tab is ${shut[1]}x${shut[2]}, its texture is ${b.w}x${b.h}`);
  }
  // ...and the parity that actually reads is the ARROW, not the box: at 1:1
  // the close tab's whole plate stands within a pixel or two of the rune
  // plate inside the open tab's filigree. Pinned by number because "1:1" on
  // its own would still pass if someone swapped in a differently-cut texture.
  if (open && shut) want(Math.abs(png(shut[3]).h - 39) <= 3,
    `the close tab is ${png(shut[3]).h}px tall; the open tab's rune plate is 39px`);
  for (const [name, re] of [['open hover', /\.railtab:hover\{background-image:url\("(data:image\/png;base64,[^"]+)"\)\}/],
                            ['close hover', /\.rail\[data-open="1"\] \.railtab:hover\{background-image:url\("(data:image\/png;base64,[^"]+)"\)\}/]]){
    const m=at(re); want(m, `the ${name} state is missing`);
  }
}

// ---- the verdict marks ----------------------------------------------------
// Ported from GD Lens. The rules are checked structurally (every row judged by
// a branch that exists, no branch reachable that this page cannot feed) and by
// outcome (each verdict actually produced by the character the page opens on),
// because a rule set that silently collapses to one answer still renders.
{
  const T=B.targets;
  const VERDICTS=(html.match(/const VERDICT_LEGEND = \[([\s\S]*?)\];/)||[,''])[1]
    .match(/\["(\w+)"/g).map(x=>x.slice(2, -1));
  want(VERDICTS.length===4, `the legend declares ${VERDICTS.length} marks, not 4`);
  want(T && T.control && T.endgame && T.pct, 'the bundle carries no targets');
  // Every row is stamped, and only with rules this page can actually answer.
  const RULES=new Set(['resist','control','benchmark','linear','none','withheld','pet']);
  const unruled=B.sheet.flatMap(([sec,l])=>l.filter(r=>!RULES.has(r.rule))
    .map(r=>`${sec}/${r.label}=${r.rule}`));
  want(unruled.length===0, `rows with no usable rule: ${unruled.slice(0,4)}`);
  // `mastery` is ported and must stay unreachable: this sheet has no "+N to a
  // mastery" row, so a row carrying it would be judged by a branch nothing
  // feeds. `pet` IS fed now -- the whole Pet Bonuses section -- and is driven
  // through the page at the bottom of this file.
  const unreachable=B.sheet.flatMap(([sec,l])=>l.filter(r=>r.mastery)
    .map(r=>`${sec}/${r.label}`));
  want(unreachable.length===0, `a row uses a branch this page cannot feed: ${unreachable}`);
  // Without a threshold the pet rule's `>= (T.petBuildDamage || Infinity)`
  // reads false forever and every pet row silently drops to the value test.
  want(T.petBuildDamage>0, 'the bundle carries no pet-build threshold');
  // Every benchmark and control row names a target that exists -- a missing key
  // reads as `ignore`, which is a verdict, so it cannot be left to fall through.
  B.sheet.forEach(([sec,l])=>l.forEach(r=>{
    if (r.rule==='benchmark') want(T.pct[r.tkey]!==undefined||T.endgame[r.tkey]!==undefined,
      `${sec}/${r.label} benchmarks against "${r.tkey}", which is not a target`);
    if (r.rule==='control') want(T.control[r.tkey]!==undefined,
      `${sec}/${r.label} has no control target for "${r.tkey}"`);
  }));
  // The build ships what the page cannot derive. Absent, the damage rules read
  // "blind" and every damage row collapses to neutral -- which renders.
  for (const c of B.characters){
    want(c.vctx && c.vctx.invested && c.vctx.resistUnrolled && c.vctx.conv && c.vctx.intent,
         `${c.name} carries no verdict context`);
  }
  want(Object.keys(opener.vctx.invested).length>0,
       `${opener.name} has no damage investment, so every damage row is an avoid`);
  // Contributions carry their kind: corroboration counts freely-chosen sources
  // and cannot tell them apart without it.
  const kinds=new Set(B.characters.flatMap(c=>Object.values(c.contrib).flat().map(x=>x[3])));
  want(!kinds.has(undefined), 'a contribution has no kind');
  for (const k of T.strongKinds) want(kinds.has(k),
    `no contribution is a "${k}", so that strong kind counts for nothing`);

  // ...and what actually rendered. All four marks, on the opening character.
  const marks=[...sheet.matchAll(/<span class="vd"(?: data-v="(\w+)")?><\/span>/g)]
    .map(m=>m[1]||null);
  want(marks.length===allRows, `${marks.length} verdict gutters for ${allRows} rows`);
  for (const v of ['priority','nice','ignore','avoid'])
    want(marks.indexOf(v)!==-1,
      `${opener.name} renders no "${v}" mark, so that branch is unexercised`);
  // `avoid` is a statement about a damage TYPE, or about a pet bonus nothing
  // can spend -- only a typed row or a pet row may carry it. A row flag that
  // collided with an existing key once sent Health and Energy to avoid on
  // every character with nothing here noticing.
  const avoidUntyped=[...sheet.matchAll(/data-sec="([^"]*)" data-ri="(\d+)" data-v="avoid"/g)]
    .map(m=>[m[1], (B.sheet.find(x=>x[0]===m[1])||[,[]])[1][+m[2]]])
    .filter(([,r])=>!r||!(r.dtype||r.rule==='pet')).map(([sec,r])=>`${sec}/${r&&r.label}`);
  want(avoidUntyped.length===0, `avoid on rows with no damage type: ${avoidUntyped.join(', ')}`);
  // A withheld row shows an empty gutter, never the neutral mark. Nothing is
  // withheld today, so assert the mechanism on the rule rather than on a row.
  want(/\.vd\{[^}]*background:center\/contain no-repeat\}/.test(html)
       && !/\.vd\{[^}]*background-image/.test(html),
       'the empty verdict gutter would paint an icon');
  for (const v of ['priority','nice','ignore','avoid'])
    want(new RegExp(`\\.vd\\[data-v="${v}"\\]\\{background-image:url\\("data:image/png;base64,`).test(html),
      `the ${v} mark has no texture`);
  // Four distinct textures -- one image reused would make two verdicts identical.
  {
    const srcs=[...html.matchAll(/\.vd\[data-v="\w+"\]\{background-image:url\("(data:image\/png;base64,[^"]+)"/g)]
      .map(m=>m[1]);
    want(new Set(srcs).size===4, `the four marks share ${4-new Set(srcs).size+1} textures`);
  }
  // ⚠️ "ALL FOUR MARKS APPEAR" IS NOT ENOUGH, and mutation-testing said so: the
  // resist rule can lose its whole priority branch while Health and the two
  // abilities keep a star on screen. So recompute the resist verdict here from
  // the contribution list and require the rendered mark to match it, row by
  // row -- the one branch with a formula of its own gets checked as a formula.
  {
    const dflt=new Set(opener.toggles.filter(t=>t.kind==='toggle'||t.kind==='granted').map(t=>t.id));
    const tot={}; for (const [f,rs] of Object.entries(opener.contrib))
      for (const [v,,tid] of rs) if(!tid||dflt.has(tid)) tot[f]=(tot[f]||0)+v;
    const TOP=new Set(['Fire','Cold','Lightning','Acid','Pierce']);
    const PEN=[[0,0],[-25,0],[-50,-25]][opener.difficulty]||[0,0];
    const MAXF=l=>'defensive'+{Fire:'Fire',Cold:'Cold',Lightning:'Lightning',Acid:'Poison',
      Pierce:'Pierce',Vitality:'Life',Aether:'Aether',Chaos:'Chaos',Bleeding:'Bleeding'}[l]+'MaxResist';
    let seen=0;
    B.sheet.forEach(([sec,rows])=>rows.forEach((r,ri)=>{
      if (r.rule!=='resist') return;
      const raw=(r.f||[]).reduce((n,f)=>n+(tot[f]||0),0);
      const eff=raw+(TOP.has(r.label)?PEN[0]:PEN[1]);
      const cap=80+(tot[MAXF(r.label)]||0)+(tot.defensiveAllMaxResist||0);
      let un=opener.vctx.resistUnrolled[r.label]; if (un===undefined) un=raw;
      const exp = eff-un*T.residual<=cap ? 'priority' : (eff<cap+T.resistSigma ? 'nice' : 'ignore');
      // The row button carries its verdict too, for the legend's focus, so the
      // gutter is no longer the next thing after data-ri.
      const m=sheet.match(new RegExp(
        `data-sec="${sec}" data-ri="${ri}"[^>]*>\\s*<span class="vd"(?: data-v="(\\w+)")?>`));
      want(m, `${sec}/${r.label} rendered no verdict gutter`);
      if (m){ seen++;
        want(m[1]===exp, `${sec}/${r.label}: marked ${m[1]}, recomputed ${exp} `
          + `(eff ${eff.toFixed(1)}, cap ${cap}, unrolled ${un})`); }
    }));
    want(seen>=9, `only ${seen} resist rows checked against the formula`);
    /* ⚠️ ONE HALF OF THAT FORMULA IS UNEXERCISED, and this says so rather than
       leaving it to look checked. The residual margin only changes an answer
       for a resist sitting within `unrolled * residual` of its cap, and NO row
       of any of the six saves here is in that window -- mutation-tested: drop
       the margin and every gate still passes. So the margin is asserted as
       SOURCE, which catches its deletion, and the count is printed so the first
       fixture that does exercise it is visible rather than silent. */
    let flipped=0;
    for (const c of B.characters){
      const on=new Set(c.toggles.filter(t=>t.kind==='toggle'||t.kind==='granted').map(t=>t.id));
      const tt={}; for (const [f,rs] of Object.entries(c.contrib))
        for (const [v,,tid] of rs) if(!tid||on.has(tid)) tt[f]=(tt[f]||0)+v;
      const pen=[[0,0],[-25,0],[-50,-25]][c.difficulty]||[0,0];
      B.sheet.forEach(([,rows])=>rows.forEach(r=>{
        if (r.rule!=='resist') return;
        const raw=(r.f||[]).reduce((n,f)=>n+(tt[f]||0),0);
        const eff=raw+(TOP.has(r.label)?pen[0]:pen[1]);
        const cap=80+(tt[MAXF(r.label)]||0)+(tt.defensiveAllMaxResist||0);
        let un=c.vctx.resistUnrolled[r.label]; if (un===undefined) un=raw;
        if ((eff<=cap) !== (eff-un*T.residual<=cap)) flipped++;
      }));
    }
    want(flipped>0 || /eff - unrolled \* T\.residual <= r\.cap/.test(html),
      'the residual margin is gone from the resist rule and no save exercises it');
    console.log(`resist residual margin decides ${flipped} row(s) across `
      + `${B.characters.length} saves`);
  }
  // The legend reads in the frame's own band ink, the same one the title uses.
  // One token, asserted as one token -- two hex literals that happen to match
  // today is how the two drift apart tomorrow.
  {
    want(/--band-ink:\s*#[0-9A-Fa-f]{3,8}/.test(html), 'there is no band ink token');
    want(/\.statpanel > \.hd h2\{[^}]*color:var\(--band-ink\)/.test(html),
         'the sheet title no longer uses the band ink');
    want(/\.legend span\{[^}]*color:var\(--band-ink\)/.test(html),
         'the legend does not use the band ink the title uses');
  }
  // ...and it is a READOUT. The marks are the control, on the rows.
  want(!/\.legend button/.test(html), 'the legend is still a set of controls');
  want(!/data-focus/.test(html), 'the legend focus feature is still in the page');
  want(!/<button[^>]*class="legend|class="legend"[^>]*>\s*<button/.test(get('legendmarks')._html)
       && !/<button/.test(get('legendmarks')._html),
       'the legend still renders buttons');

  // ---- the marks are controls ---------------------------------------------
  // ⚠️ THE KEY IS (section, label) AND IT HAS TO BE UNIQUE. "Physical" is a row
  // in four sections; a label-only key moves four marks at once, and a row
  // INDEX re-points every stored override the first time a row is inserted.
  {
    const keys=B.sheet.flatMap(([sec,l])=>l.map(r=>sec+' / '+r.label));
    const dupes=keys.filter((k,i)=>keys.indexOf(k)!==i);
    want(dupes.length===0, `the override key is not unique: ${[...new Set(dupes)].slice(0,3)}`);
    want(new Set(B.sheet.flatMap(([,l])=>l.map(r=>r.label))).size < keys.length,
         'no label repeats across sections, so the section half of the key is untested');
  }
  // The cycle IS the scale, worst to best -- gear.js-style ranking elsewhere
  // would disagree with a legend ordered any other way.
  {
    const cyc=(html.match(/const VCYCLE = \[([^\]]*)\]/)||[,''])[1]
      .match(/"(\w+)"/g).map(x=>x.slice(1,-1));
    want(cyc.join()==='avoid,ignore,nice,priority', `the cycle is ${cyc}`);
    for (const v of cyc) want(VERDICTS.indexOf(v)!==-1, `"${v}" is cycled but not in the legend`);
    want(cyc.length===VERDICTS.length, 'the cycle and the legend list different marks');
  }
  // Driven through the page's OWN handlers, so what is checked is the behaviour
  // a pointer gets rather than a function called directly.
  {
    const fire=(ev,el)=>(handlers[ev]||[]).forEach(fn=>fn({target:el, preventDefault(){}}));
    const rowEl=(sec,ri)=>({ dataset:{sec, ri:String(ri)},
      closest(sel){ return sel==='.row' ? this : null; } });
    const markOf=(sec,ri)=>{
      const m=get('sheet')._html.match(new RegExp(
        `data-sec="${sec}" data-ri="${ri}"[^>]*>\\s*<span class="vd"(?: data-v="(\\w+)")?>`));
      return m ? (m[1]||null) : undefined;
    };
    // A row whose computed verdict is known, and not at either end of the scale.
    const pick=(()=>{
      for (const [sec,rows] of B.sheet) for (let ri=0; ri<rows.length; ri++){
        const v=markOf(sec,ri);
        if (v==='nice') return {sec, ri, v};
      }
      return null;
    })();
    want(pick, 'no row starts at "nice", so the cycle has nothing to step from');
    if (pick){
      const {sec, ri}=pick;
      want(markOf(sec,ri)==='nice', 'precondition');
      fire('click', rowEl(sec,ri));
      want(markOf(sec,ri)==='priority', `a click took nice to ${markOf(sec,ri)}`);
      fire('click', rowEl(sec,ri));
      want(markOf(sec,ri)==='avoid', `the cycle does not wrap: ${markOf(sec,ri)}`);
      fire('contextmenu', rowEl(sec,ri));
      want(markOf(sec,ri)==='priority', `a right-click did not reverse: ${markOf(sec,ri)}`);
      // ⚠️ AN OVERRIDE MUST SURVIVE A BUFF TOGGLE. renderSheet rebuilds every
      // row, which is exactly what destroys an override kept on a DOM node.
      const tg={id:'', dataset:{t:opener.toggles[0].id}, closest(sel){ return sel==='.tg'?this:null; }};
      fire('click', tg);
      want(markOf(sec,ri)==='priority',
           `the override did not survive a buff toggle: ${markOf(sec,ri)}`);
      fire('click', tg);
      // Landing back on the engine's own answer CLEARS it rather than pinning
      // it -- so the store holds only rows a reader actually moved.
      fire('contextmenu', rowEl(sec,ri));
      want(markOf(sec,ri)==='nice', `stepping back to the computed value left ${markOf(sec,ri)}`);
      want(!(global.window.localStorage.getItem('allostria.verdicts.'+opener.dir)||'')
             .includes(`${sec} / `),
           'returning a row to the engine left its override stored');
      // ...and one that is NOT the computed value persists under the key the
      // page will look for on the next load.
      fire('click', rowEl(sec,ri));
      const raw=global.window.localStorage.getItem('allostria.verdicts.'+opener.dir);
      want(raw && JSON.parse(raw)[`${sec} / ${B.sheet.find(x=>x[0]===sec)[1][ri].label}`]==='priority',
           `the override was not stored under its own key: ${raw}`);
      fire('contextmenu', rowEl(sec,ri));   // leave the page as it was found
    }
  }

  // The legend is generated from the same table the rows are marked from.
  const legend=get('legendmarks')._html;
  for (const v of ['priority','nice','ignore','avoid'])
    want(legend.includes(`data-v="${v}"`), `the legend omits the ${v} mark`);
  want(/Priority[\s\S]*Nice[\s\S]*Neutral[\s\S]*Avoid/.test(legend),
       `the legend does not read Priority, Nice, Neutral, Avoid: ${legend}`);
  want(shell.indexOf('<div class="legend"')>shell.indexOf('<div class="sheet"'),
       'the legend is not below the stats');
  want(shell.indexOf('<div class="legend"')<shell.indexOf('</section>'),
       'the legend is outside the sheet panel, so the bottom crest is not below it');
  // The band carries a line of prose ABOVE the generated marks -- the marks
  // are a control and nothing else on the page says so. Two lines only fit a
  // band sized for one because they stack, so that is checked with them.
  {
    const band=shell.slice(shell.indexOf('<div class="legend"'),
                           shell.indexOf('</section>'));
    want(/class="hint"[\s\S]*id="legendmarks"/.test(band),
         'the legend band is not a hint line above the marks');
    want(/click/i.test(band), 'the legend hint does not name the gesture');
    want(/\.statpanel > \.legend\{[^}]*flex-direction:column/.test(html),
         'the legend band does not stack, so the hint sits beside the marks');
  }
  // It sits IN the frame's own footer band -- between the thin rule and the
  // scrollwork -- which means it is positioned against the border rather than
  // laid out in the flow, and offset by the border width for the same
  // padding-box reason the title and the crests are. Both offsets come off the
  // texture, so the check is that they agree with the frame, not that they are
  // any particular number.
  {
    const slice=(html.match(/\.statpanel\{position:relative;\s*\n?\s*border:(\d+)px solid transparent/)||[])[1];
    want(slice, 'the stat panel has no measured border width');
    const m=html.match(/\.statpanel > \.legend\{position:absolute;[\s\S]*?bottom:calc\((\d+)px - (\d+)px\); height:(\d+)px/);
    want(m, 'the legend is not positioned into the frame footer band');
    if (m && slice){
      want(m[2]===slice, `the legend offsets by ${m[2]}px, the frame border is ${slice}px`);
      want(+m[1]+ +m[3] < +slice,
        `a ${m[3]}px band ${m[1]}px up does not fit inside a ${slice}px border`);
      // ...and it must clear the flow, or the stats would run under it.
      const t=html.match(/\.statpanel > \.hd\{position:absolute;[\s\S]*?top:calc\((\d+)px - (\d+)px\)/);
      want(t && t[2]===slice, 'the title band and the footer band disagree about the frame');
    }
  }
}

// ---- the buff tile is the options menu's button ---------------------------
// Three states, painted as a HORIZONTAL 3-slice: the ornate ends are drawn 1:1
// and only the middle stretches, so border-width must equal the slice and the
// tile must stand exactly as tall as the texture. Both are read back off the
// PNG's own header rather than typed, so a re-cut texture moves them together.
{
  const png=b64=>{ const h=Buffer.from(b64.slice(b64.indexOf(',')+1), 'base64');
    return {w:h.readUInt32BE(16), h:h.readUInt32BE(20)}; };
  const m=html.match(/\.tg\{[\s\S]*?height:(\d+)px;[\s\S]*?border-width:0 (\d+)px;\s*\n?\s*border-image:url\("(data:image\/png;base64,[^"]+)"\) 0 (\d+) fill stretch/);
  want(m, 'the buff tile is not painted with the options button');
  if (m){
    const art=png(m[3]);
    want(+m[1]===art.h, `the tile is ${m[1]}px tall, the button texture is ${art.h}px`);
    want(m[2]===m[4], `border-width ${m[2]}px does not match the slice ${m[4]}`);
    want(+m[4]*3 < art.w, `a ${m[4]}px end cap leaves nothing to stretch in ${art.w}px`);
    const other=[...html.matchAll(/\.tg[^{]*\{border-image-source:url\("(data:image\/png;base64,[^"]+)"\)\}/g)]
      .map(x=>x[1]);
    const all=new Set([m[3], ...other]);
    want(all.size===4, `the button has ${all.size} distinct state textures, not 4`);
    for (const src of other) want(png(src).w===art.w && png(src).h===art.h,
      'a button state is not the same size as the others');
  }
}
// Nothing anywhere may render a filename or a leaked colour code. Checked over
// EVERY character, not just Nurgle: relics name themselves through
// `description` and components through a string that can open with a bare ^X,
// and both were showing raw.
// ---- an affixed item is not its base --------------------------------------
// 49 of 77 worn items printed as a bare base because the name came from the
// base record alone. Each item carries the affixes it rolled, so the claim is
// direct: the display name must show every one of them.
{
  let affixed=0, labelled=0;
  for (const c of B.characters){
    for (const e of c.equipment){
      const names=Object.values(e.affixes||{});
      if (!names.length) continue;
      affixed++;
      for (const a of names)
        want(e.n.includes(a), `${c.name}: "${e.n}" rolled "${a}" but its name does not show it`);
    }
    // An affix's contributions are labelled by the affix and its slot --
    // `Impervious (Shoulders)` -- never by the whole item name.
    const srcs=new Set(c.equipment.flatMap(e=>
      Object.values(e.affixes||{}).map(a=>`${a} (${e.slotLabel})`)));
    for (const rows of Object.values(c.contrib))
      for (const [,src,,kind] of rows){
        if (kind==='prefix'||kind==='suffix'){
          want(srcs.has(src), `${c.name}: ${kind} source "${src}" is not an affix on a worn slot`);
          if (srcs.has(src)) labelled++;
        }
        if (kind==='component'||kind==='augment')
          want(!src.includes(' \u00b7 '), `${c.name}: ${kind} source "${src}" still carries its item`);
      }
  }
  // This is the bug's own scale: if it ever reads zero, the check went blind.
  want(affixed>=40, `only ${affixed} worn items carry an affix; the fix covered 49`);
  want(labelled>0, 'no contribution is labelled by its affix');
}
// An affix must never be credited by name as well as by role -- that was the
// redundant `... of Heroism \u00b7 of Heroism` form.
for (const c of B.characters)
  for (const rows of Object.values(c.contrib))
    for (const [,src] of rows){
      const m=/^(.*) \u00b7 (.+)$/.exec(src);
      if (m && m[2]!=='prefix' && m[2]!=='suffix')
        want(!m[1].endsWith(m[2]), `${c.name}: "${src}" names the same thing twice`);
    }

// ---- displayed tier and the nameplate badge -------------------------------
// The rule the records state: MI is green from the BASE, a plain Rare is green
// from an AFFIX, and the two-diamond badges need Rare on BOTH sides. Assert
// against the contributions, which are the only place the bundle still says
// which affixes an item has.
{
  let green=0, mi=0;
  for (const c of B.characters){
    for (const e of c.equipment){
      const badge=e.badge||null;
      want(badge===null||['mi','dr','drmi'].includes(badge),
           `${c.name}: ${e.n} carries an unknown badge ${JSON.stringify(badge)}`);
      // A badge is a Rare-family state: nothing Epic or Legendary may wear one.
      if (badge) want(e.rarity==='Rare',
        `${c.name}: ${e.n} is ${e.rarity} and still shows the ${badge} badge`);
      if (e.rarity==='Rare') green++;
      if (badge==='mi') mi++;
      // An affixed item must not still be reporting a bare base tier.
      const affixed=Object.keys(e.affixes||{}).length>0;
      if (affixed) want(e.rarity!=='Common',
        `${c.name}: ${e.n} has an affix and still displays as Common`);
    }
  }
  want(green>=40 && mi>=10,
       `${green} green items and ${mi} MI badges -- the tier rule looks inert`);
  // Every badge the page can emit must have art behind it.
  for (const k of ['mi','dr','drmi'])
    want(new RegExp(`\\.sym\\[data-q="${k}"\\]\\{background-image:url\\("data:image/png;base64,[^"]{400,}"\\)\\}`)
         .test(html), `the ${k} badge has no image`);
  want(/<span class="sym" data-q="mi"/.test(gear), 'no MI badge rendered on the gear list');
  // ...and the badge sits BEFORE the name, which is the placement asked for.
  want(/<span class="nm t-[^"]*"><span class="sym"[^>]*><\/span>[^<]/.test(gear),
       'the badge is not to the left of the item name');
}
// The two double-rare states are UNREACHABLE in this bundle -- no worn item has
// Rare on both sides -- so nothing above exercises them. Pin the precondition:
// the day one drops, this fires and says that branch has gone live untested.
{
  const dr=B.characters.flatMap(c=>c.equipment.filter(e=>e.badge==='dr'||e.badge==='drmi'));
  want(dr.length===0,
       `a double rare is now worn (${dr.map(e=>e.n).join(', ')}) -- the dr/drmi `
       + `branches of quality() are live and nothing here has ever tested them`);
}

const RAW_NAME=/\.dbr$|\^|^[a-z0-9_]{6,}$/;
// ---- set bonuses, and the tooltip blocks ---------------------------------
// The set bonus fed NOTHING before this: Nurgle wears three of three and was
// missing +100% Acid, +100% Acid Decay and +100% Total Retaliation Damage.
// Derive the expectation from the pieces worn, not from a number typed here.
{
  let sets=0;
  for (const c of B.characters){
    const byset=new Map();
    for (const e of c.equipment) if (e.set){
      sets++;
      const k=e.set.n;
      if(!byset.has(k)) byset.set(k, []);
      byset.get(k).push(e);
      want(e.set.worn>=2, `${c.name}: ${e.n} claims a set bonus at ${e.set.worn} piece(s)`);
      want(e.set.worn<=e.set.total, `${c.name}: ${e.set.n} counts ${e.set.worn}/${e.set.total}`);
      want(e.set.members.filter(m=>m.worn).length===e.set.worn,
           `${c.name}: ${e.set.n} says ${e.set.worn} worn but marks `
           + `${e.set.members.filter(m=>m.worn).length} members`);
      want(e.set.lines.length>0, `${c.name}: ${e.set.n} is active and lists no bonus`);
    }
    // every piece of one set must agree, and the bonus must reach the sheet ONCE
    for (const [nm, pieces] of byset){
      want(new Set(pieces.map(p=>JSON.stringify(p.set))).size===1,
           `${c.name}: pieces of ${nm} disagree about the set`);
      const label=`set \u00b7 ${nm}`;
      const fields=Object.entries(c.contrib)
        .filter(([,rows])=>rows.some(([,s])=>s===label)).map(([f])=>f);
      want(fields.length>0, `${c.name}: ${nm} is active but feeds no stat`);
      for (const f of fields){
        const dup=c.contrib[f].filter(([,s])=>s===label).length;
        want(dup===1, `${c.name}: ${nm} credited to ${f} ${dup} times -- once per piece?`);
      }
    }
  }
  want(sets>=3, `only ${sets} set pieces worn; the set path is going untested`);
}
// ⚠️ THE TIER ALIGNMENT IS NOT TESTABLE FROM HERE AND MUST NOT BE ASSUMED
// TESTED. The only set worn is Daega's Oath -- 3 members, worn complete, every
// array as long as the slot count -- and for that shape left- and
// right-alignment produce IDENTICAL output. Flipping the decode passes
// everything below. `gate_setbonus.py` is what actually pins the direction,
// against Explorer's Garments; run it after any edit to set_bonus().
// If a set with a SHORT array is ever worn, that becomes testable here too.
for (const c of B.characters)
  for (const e of c.equipment)
    if (e.set) want(e.set.worn!==e.set.total || e.set.lines.length>=1,
                    `${c.name}: a complete ${e.set.n} grants nothing`);

// The other three blocks. Each must be absent rather than empty when it does
// not apply -- an empty heading reads as a bonus that exists and is blank.
{
  let grants=0, mods=0, bonus=0;
  for (const c of B.characters)
    for (const e of c.equipment){
      if (e.grantName){ grants++;
        want(!RAW_NAME.test(e.grantName), `${c.name}: ${e.n} grants raw "${e.grantName}"`); }
      want(e.granted ? !!e.grantName : true,
           `${c.name}: ${e.n} names a granted skill but could not resolve it`);
      for (const m of e.mods||[]){ mods++;
        want(/^\+\d+ /.test(m) && !RAW_NAME.test(m.replace(/^\+\d+ /,'')),
             `${c.name}: ${e.n} skill modifier reads "${m}"`); }
      for (const l of e.bonus||[]){ bonus++;
        want(!RAW_NAME.test(l), `${c.name}: ${e.n} completion bonus reads "${l}"`); }
      // a relic bonus record that produced no line at all is unread, not absent
      if (e.slot==='relic')
        want((e.bonus||[]).length>0, `${c.name}: ${e.n} shows no completion bonus`);
    }
  want(grants>=15 && mods>=25 && bonus>=4,
       `grants ${grants}, modifiers ${mods}, completion bonuses ${bonus} -- a block went blind`);
}

const RAW=/\.dbr$|\^|^[a-z0-9_]{6,}$/;
for (const c of B.characters){
  for (const e of c.equipment){
    want(!RAW.test(e.n), `${c.name}: item renders raw "${e.n}"`);
    for (const a of e.attached) want(!RAW.test(a.name), `${c.name}: attachment renders raw "${a.name}"`);
  }
  for (const t of c.toggles){
    want(!RAW.test(t.n), `${c.name}: toggle renders raw "${t.n}"`);
    want(!RAW.test(t.from||''), `${c.name}: toggle source renders raw "${t.from}"`);
  }
}
const pot=named('Path of the Three');
want(!!pot, 'Path of the Three is not a toggle');
// It moves plenty -- +195% Acid and Vitality -- but carries no ABILITY field,
// which is why folding it in does not move OA. That is the claim worth pinning.
for (const f of ['characterOffensiveAbility','characterDefensiveAbility',
                 'characterOffensiveAbilityModifier','characterDefensiveAbilityModifier'])
  want(!(N.contrib[f]||[]).some(([,,tid])=>tid===(pot||{}).id),
       `Path of the Three must not feed ${f}`);
want(Object.values(N.contrib).some(rs=>rs.some(([,,tid])=>tid===(pot||{}).id)),
     'Path of the Three feeds nothing at all -- its buff chain did not resolve');
for (const meta of ['skillMaxLevel','skillTier','skillUltimateLevel'])
  want(!N.contrib[meta], `${meta} is record metadata and must not be a contribution`);
const on=new Set([named('Presence of Virtue').id]);

const tot={}; for(const [f,rs] of Object.entries(N.contrib))
  for(const [v,,tid] of rs) if(!tid||on.has(tid)) tot[f]=(tot[f]||0)+v;
const attr=(w,F)=>(N.base[w]+(tot[F]||0))*(1+(tot[F+'Modifier']||0)/100);
const ability=(F,w)=>Math.floor(((tot[F]||0)+N.level*12+(attr(w,{physique:'characterStrength',
  cunning:'characterDexterity'}[w])+130)*0.5)*(1+(tot[F+'Modifier']||0)/100)+53);
const oa=ability('characterOffensiveAbility','cunning');
const da=ability('characterDefensiveAbility','physique');
want(oa===1975, `Offensive Ability ${oa}, in game 1975`);
want(da===2399, `Defensive Ability ${da}, in game 2399`);

// ---- the mastery tree ----------------------------------------------------
// Shaped after the earlier pass's own checker: re-derive what was declared and
// fail if the tree dropped one, then pin a corrected fact BY NAME, because a
// tree that silently loses an edge still renders as a perfectly tidy list.
for (const c of B.characters){
  const t=c.tree||[];
  want(t.every(s=>!s.dev), `${c.name}: devotion leaked into the mastery window`);
  want(t.every(s=>s.cls!=='Skill_Mastery'), `${c.name}: a mastery bar is in its own tree`);
  want(t.every(s=>s.parent===null||(s.parent>=0&&s.parent<t.length)),
       `${c.name}: a parent index points outside the tree`);
  // no cycles, and every node reachable from a root
  let seen=0;
  for(let i=0;i<t.length;i++){ let n=i,hops=0;
    while(t[n].parent!==null&&hops++<64) n=t[n].parent;
    want(hops<64,`${c.name}: cycle in the tree at ${t[i].n}`); seen++; }
  want(seen===t.length, `${c.name}: unreachable node`);
  want(c.treeDropped.length===0 || c.treeDropped.every(d=>Array.isArray(d)),
       `${c.name}: malformed dropped-edge record`);
}
// A declared skillDependancy between two INVESTED skills must survive as an
// edge -- that is the shape the stray-semicolon bug takes.
const naz=B.characters.find(c=>c.name==='Nazeem');
const idx=n=>naz.tree.findIndex(s=>s.n===n);
const wr=idx('Wereraven');
want(wr>=0, 'Nazeem has Wereraven invested and it is not in the tree');
for(const child of ['Glacial Talons','Everwinter'])
  want(idx(child)>=0 && naz.tree[idx(child)].parent===wr,
       `${child} should hang off Wereraven (skillDependancy), got `
       + JSON.stringify(idx(child)>=0?naz.tree[naz.tree[idx(child)].parent||0]?.n:'missing'));
// ...and the family route, where no dependency is declared at all.
const nu=B.characters.find(c=>c.name==='Nurgle');
const ni=n=>nu.tree.findIndex(s=>s.n===n);
const aegis=ni('Aegis of Menhir');
for(const child of ['Avenging Shield','Reprisal','Aegis of Thorns'])
  want(ni(child)>=0 && nu.tree[ni(child)].parent===aegis,
       `${child} should hang off Aegis of Menhir (tag family)`);
want(nu.tree.filter(s=>s.parent===null).length===12,
     `Nurgle should show 12 roots, got ${nu.tree.filter(s=>s.parent===null).length}`);
// the page must actually nest it
const panels=get('skillpanels')._html;
const depths=[...panels.matchAll(/padding-left:(\d+)px/g)].map(m=>+m[1]);
want(new Set(depths).size>=2, `the skill list rendered flat: depths ${[...new Set(depths)]}`);

// ---- one panel per mastery, titled by name and level ----------------------
// 50 is NOT typed into the page: the fill divides by the mastery record's own
// max_level. Pin that it is 50 and that no bar exceeds it -- the fill is
// clamped at 100%, so a bar over its cap would otherwise paint full and say
// nothing. Derived over every character, not just the opener's two.
for (const c of B.characters){
  const bars=c.skills.filter(s=>s.cls==='Skill_Mastery');
  want(bars.length===c.masteries.length,
       `${c.name}: ${bars.length} mastery records but ${c.masteries.length} masteries`);
  for (const m of bars){
    want(m.max===50, `${c.name}: ${m.n} caps at ${m.max}, the bar assumes 50`);
    want(m.lv>=0 && m.lv<=m.max, `${c.name}: ${m.n} is ${m.lv}/${m.max} -- over its own cap`);
  }
}
// ...and the opener actually rendered one panel per mastery, each carrying the
// name, a proportional fill and the level, with every root skill still placed.
const openerBars=opener.skills.filter(s=>s.cls==='Skill_Mastery');
const heads=[...panels.matchAll(
  /<summary class="hd"><h2>([^<]*)<\/h2>[\s\S]*?class="track" data-c="(\d*)"[\s\S]*?class="unlit"\s*style="width:([\d.]+)%"[\s\S]*?class="mv">([^<]*)</g)];
want(heads.length===openerBars.length,
     `${opener.name}: ${openerBars.length} masteries, ${heads.length} panels rendered`);
openerBars.forEach((m,i)=>{
  const [,name,cls,unlit,lvl]=heads[i]||[,'','','',''];
  want(name===m.n, `panel ${i} is titled "${name}", expected "${m.n}"`);
  want(lvl===`${m.lv}`, `${m.n}: title reads "${lvl}", expected "${m.lv}"`);
  // The class number comes off the record path, so re-derive it the same way
  // rather than restating a name-to-id table the page deliberately avoids.
  const want_c=(m.path.match(/playerclass(\d+)/)||[])[1];
  want(cls===want_c, `${m.n}: track tagged class "${cls}", its record is ${m.path}`);
  // The overlay masks what the mastery has NOT reached, so it is the inverse
  // of the fill. Asserting it against the level is what makes a bar that is
  // full at 40/50 -- or empty at 50/50 -- fail rather than merely look odd.
  want(Math.abs(+unlit - (100 - m.lv/m.max*100))<0.01,
       `${m.n}: ${unlit}% of the bar masked off at ${m.lv}/${m.max}, expected `
       + `${100 - m.lv/m.max*100}%`);
});
// Every class the game defines carries a bar, and each is real image data --
// a rule whose url went missing leaves the track painted flat with no error.
// The overlay is styled by class name, so the name is part of the contract:
// rename it and the track paints full at every level with nothing to say so.
want(/\.hd \.unlit\{margin-left:auto/.test(html), 'the .unlit overlay has no rule');
for (let i=1;i<=10;i++){
  const k=String(i).padStart(2,'0');
  const rule=new RegExp(`\\.hd \\.track\\[data-c="${k}"\\]\\{background-image:url\\("(data:image/png;base64,[^"]{400,})"\\)\\}`);
  want(rule.test(html), `class ${k} has no mastery bar image`);
}
// ...and the ones this page actually shows must be among them.
for (const c of B.characters)
  for (const m of c.skills.filter(s=>s.cls==='Skill_Mastery')){
    const k=(m.path.match(/playerclass(\d+)/)||[])[1];
    want(k && new RegExp(`data-c="${k}"\\]`).test(html),
         `${c.name}: ${m.n} resolves to class "${k}", which has no bar rule`);
  }
// No invested skill may fall off the end because its mastery matched no bar.
const placed=(panels.match(/class="sk"/g)||[]).length;
want(placed===opener.tree.length,
     `${opener.name}: ${opener.tree.length} skills in the tree, ${placed} rendered`);
// ...and that count cannot currently catch the case it is aimed at: in THIS
// bundle every root's mastery matches a bar, so the fallback panel is never
// built and dropping it would change nothing. Pin the precondition instead --
// the day a character carries a root with no bar, this fires and says that
// branch has gone live untested.
for (const c of B.characters){
  const named=new Set(c.skills.filter(s=>s.cls==='Skill_Mastery').map(s=>s.n));
  const orphans=(c.tree||[]).filter(s=>s.parent===null&&(s.mastery||'Other')!==null
    &&!named.has(s.mastery||'Other')).map(s=>s.n);
  want(orphans.length===0,
       `${c.name}: root skills with no mastery bar ${JSON.stringify(orphans)} -- the `
       + `fallback panel in renderSkills is now reachable and nothing here exercises it`);
}
want((panels.match(/<details class="panel" open>/g)||[]).length===openerBars.length,
     'a mastery panel is missing or is not collapsible');

// ---- the detail tooltip ---------------------------------------------------
// The detail used to be a panel under the equipment list, rendered on click by
// render(). It is a floating tooltip driven by pointerover/focusin now, so the
// only way to know it still resolves is to fire the handler. Both anchors are
// derived from what the page just rendered, not typed here: a tooltip that
// silently resolved to the wrong item would otherwise look identical.
const tip=get('tip');
want(!/id="tipwrap"/.test(html), 'the old detail panel is still in the markup');
// Equipment is collapsible in the static markup; the mastery panels are built
// at render time and are checked against #skillpanels further down. Count only
// the markup above the script, or the <details> template inside renderSkills
// makes this pass on its own.
const markup=html.slice(0, html.indexOf('<script id="bundle"'));
want((markup.match(/<details class="panel" open>/g)||[]).length===1,
     'Equipment should be a collapsible <details>, open by default');
want(/<summary class="hd"><h2>Equipment<\/h2>/.test(markup),
     'the Equipment panel header is not a <summary>');
want(/<div id="skillpanels"><\/div>/.test(html),
     'the per-mastery skill panels have no container to render into');
want(tip.hidden===true, 'the tooltip should start hidden');

const fire=(ev,target)=>(handlers[ev]||[]).forEach(fn=>fn({target}));
// A stand-in for one rendered button: `kind` is the selector it answers to,
// so tipFor's .geo/.row probe resolves exactly as it does in a browser.
const anchor=(kind,dataset)=>{
  const el={ id:'', dataset,
    getBoundingClientRect:()=>({left:20,top:120,right:300,bottom:172,width:280,height:52}) };
  el.closest=sel=>(sel==='.geo'||sel==='.row') ? (sel===kind?el:null) : el;
  return el;
};

// first worn item, as the page ORDERED it (SLOT_ORDER lives in the page)
const firstGear=(get('gear')._html.match(/class="nm t-[^"]*">([^<]*)</)||[])[1];
const gAnchor=anchor('.geo', {e:'0'});
fire('pointerover', gAnchor);
want(tip.hidden===false, 'hovering a worn item did not open the tooltip');
want(!!firstGear && tip._html.includes(firstGear),
     `tooltip should show "${firstGear}", got ${tip._html.slice(0,120)}`);

// first stat row, keyed by the section/index the page itself stamped on it
const m=get('sheet')._html.match(/data-sec="([^"]*)" data-ri="(\d+)"[\s\S]*?class="rl">([^<]*)</);
const rAnchor=anchor('.row', {sec:m[1], ri:m[2]});
fire('pointerover', rAnchor);
want(tip.hidden===false, 'hovering a stat row did not open the tooltip');
want(tip._html.includes(m[3]), `tooltip should show the "${m[3]}" breakdown`);
want(/class="srcs"/.test(tip._html), 'the stat tooltip lost its contribution list');

// off both -- and the tooltip itself must NOT dismiss itself, or a long
// contribution list could never be scrolled
fire('pointerover', {id:'', closest:()=>null});
want(tip.hidden===true, 'leaving the row did not close the tooltip');
fire('pointerover', rAnchor);
fire('pointerover', {id:'tip', closest(sel){ return sel.includes('#tip') ? this : null; }});
want(tip.hidden===false, 'moving onto the tooltip closed it');
want(!/undefined|NaN|\[object/.test(tip._html), 'the tooltip rendered undefined/NaN');
// The stat tooltip carries contributions and nothing else -- there is no
// blurb left to stand in for them, because a row with nothing feeding it now
// opens no tooltip at all.
want(/class="srcs"/.test(tip._html) && !/class="note"/.test(tip._html),
     'the stat tooltip prints a note alongside its contribution list');
// A long SOURCE is text wider than the box, and overflow-y:auto makes
// overflow-x compute to auto -- which put a horizontal scrollbar on the panel.
// Nothing here can measure layout, so assert the rules that make overflow
// impossible, and assert they are still needed against the data rather than
// against a width that happened to fit.
want(/\.tip\{[^}]*overflow-wrap:anywhere/.test(html),
     'the tooltip can still be forced wider by an unbreakable source name');
want(/\.srcs div > span\{min-width:0\}/.test(html),
     'a long contribution source can still hold the tooltip open');
{
  const longest=[...new Set(B.characters.flatMap(c=>
    Object.values(c.contrib).flat().map(([,src])=>src)))]
    .sort((a,b)=>b.length-a.length)[0];
  want(longest.length>=40,
       `the longest source is only ${longest.length} chars (${longest}) -- the `
       + `overflow this guards against may no longer be reachable`);
}

// ---- the stat row's hover detail ------------------------------------------
// It is the contributions and nothing else now: no classification subtitle,
// and no raw field names (they were on the same line).
{
  for (const dead of ['solved formula', 'sum of records'])
    want(!tip._html.includes(dead), `the tooltip still carries its "${dead}" subtitle`);
  const fields=new Set(B.sheet.flatMap(([,l])=>l.flatMap(r=>(r.f||[]).concat(r.m||[]))));
  const leaked=[...fields].filter(f=>tip._html.includes(f));
  want(leaked.length===0, `the tooltip prints raw field names: ${leaked.slice(0,3)}`);
}
// ⚠️ AND IT MUST LIST THE PERCENTAGE FIELD THE ROW FINISHES WITH. `r.f` is the
// additive half; the four formula kinds also multiply through `r.m`, and the
// detail used to walk `r.f` alone -- so a +80% Health Regeneration sat inside
// the number with nothing in the panel explaining it. Checked over EVERY such
// row of the opener, with the counts derived from the contribution list, so
// this cannot be satisfied by one row happening to look right.
{
  let checked=0, withMod=0;
  B.sheet.forEach(([sec, rows])=>rows.forEach((r, ri)=>{
    if (!r.m) return;
    checked++;
    want(r.pct===false, `${r.label} carries a modifier AND prints a percentage; `
      + 'the % on each source line can no longer be read off the field');
    const flat=(r.f||[]).reduce((n,f)=>n+(opener.contrib[f]||[]).length,0);
    const pct=(opener.contrib[r.m]||[]).length;
    if (!pct) return;
    withMod++;
    fire('pointerover', anchor('.row', {sec, ri:String(ri)}));
    const lines=(tip._html.match(/<span class="sv">/g)||[]).length;
    const pcts=(tip._html.match(/<span class="sv">[^<]*%<\/span>/g)||[]).length;
    want(lines===flat+pct,
      `${r.label}: ${lines} sources listed, the contribution list has ${flat+pct}`);
    want(pcts===pct,
      `${r.label}: ${pcts} of them carry a %, ${pct} come from ${r.m}`);
  }));
  want(checked>0, 'no row declares a modifier field; `m` is not reaching the page');

  // ---- the pet resist ceiling, on the RENDERED number --------------------
  // ⚠️ THE BUILD SHIPS RAW SUMS AND THE PAGE APPLIES THE CAP, so this has to
  // read what was drawn. Rows summing 108 and 90 both display exactly 80 in
  // game while every row under 80 matches, so a row rendering 115 is wrong
  // rather than generous. Checked in BOTH directions: a capped row must show
  // the cap, and an uncapped one must show its own sum -- "always 80" would
  // otherwise pass as easily as "never".
  {
    const petSec=B.sheet.find(s=>s[2]==='pet');
    want(petSec, 'no section declares the pet bucket');
    if (petSec){
      const [pname, prows] = petSec;
      let capped=0, under=0;
      prows.forEach((r, ri)=>{
        const raw=(r.f||[]).reduce((n,f)=>
          n+((opener.petContrib||{})[f]||[]).reduce((m,c)=>m+c[0],0), 0);
        const m=get('sheet')._html.match(new RegExp(
          `data-sec="${pname}" data-ri="${ri}"[\\s\\S]*?class="rv[^"]*">([^<]*)<`));
        want(m, `${pname}/${r.label} did not render`);
        if (!m) return;
        // ⚠️ THE PAGE FORMATS WITH toLocaleString, so a four-figure value
        // renders "1,371%" and parseFloat stops at the comma and returns 1.
        // This passed while the opener's pet numbers were all under 1000 --
        // a check that only works on small values is not a check.
        const shown=parseFloat(m[1].replace(/[^\d.-]/g, ''));
        if (r.cap!=null && raw>r.cap){ capped++;
          want(shown===r.cap,
               `${r.label} sums ${raw} and must display ${r.cap}, showed ${shown}`); }
        else { under++;
          want(Math.abs(shown-raw)<0.51,
               `${r.label} sums ${raw} but displays ${shown} with no cap to reach`); }
      });
      if (!capped) uncovered.push(
        'the opener has no pet resist row summing above 80, so the RENDERED '
        + 'ceiling is unproven here -- the page\'s functions are private to '
        + 'new Function(code), so this can only read the character on screen. '
        + 'tests/test_pet_bonuses.py proves the data side, where 5 rows do '
        + 'exceed it');
      console.log(`pet bonuses: ${prows.length} rows, ${capped} at the 80 cap, ${under} below it`);
    }
  }
  // Flat and percentage are separate lists with a rule between them, and the
  // rule appears ONLY when both sides are fed -- a divider under an empty
  // block reads as a missing section. Checked over every row of the opener,
  // both directions, so "always draw it" and "never draw it" both fail.
  let mixed=0, single=0, empty=0, penalised=0;
  B.sheet.forEach(([sec, rows, bucket])=>rows.forEach((r, ri)=>{
    // A bucketed section is fed by its OWN contribution list. Reading the
    // player's for a pet row asks whether the wrong number has a panel.
    const from=(bucket ? opener.petContrib : opener.contrib)||{};
    // `r.f` is percent when the ROW is; `r.m` always is.
    const listed=(r.f||[]).reduce((n,f)=>n+(from[f]||[]).length,0);
    const nFlat=r.pct ? 0 : listed;
    const nPct=(r.pct ? listed : 0) + (r.m ? (from[r.m]||[]).length : 0);
    fire('pointerover', anchor('.row', {sec, ri:String(ri)}));
    // ⚠️ hideTip() only flips `hidden`; `_html` still holds the LAST panel
    // rendered. Read it only when the panel is actually up, or an unfed row
    // is silently checked against its predecessor's markup.
    // A penalised damage resist also lists the penalty, under its own rule --
    // the row's number is held to the cap, so the tooltip is the only place
    // the penalty still shows.
    const PENS=[[0,0],[-25,0],[-50,-25]][opener.difficulty]||[0,0];
    const pen=sec!=='Resistances'||r.label==='Physical' ? 0
      : (['Fire','Cold','Lightning','Acid','Pierce'].includes(r.label) ? PENS[0] : PENS[1]);
    if (pen){
      want(tip.hidden===false && tip._html.includes('difficulty penalty'),
           `${sec}/${r.label} carries a ${pen}% penalty its tooltip does not list`);
      penalised++;
    }
    const xtra=pen||/Over cap/.test(tip.hidden ? '' : tip._html) ? 1 : 0;
    if (!nFlat && !nPct && !pen){ empty++;
      want(tip.hidden===true,
           `${sec}/${r.label} has no contributor but still opened a tooltip`);
      return; }
    want(tip.hidden===false, `${sec}/${r.label} is fed but opened no tooltip`);
    const ruled=(tip._html.match(/<div class="rule"><\/div>/g)||[]).length;
    if (nFlat && nPct){ mixed++;
      want(ruled===1+xtra, `${sec}/${r.label} mixes flat and percent but drew ${ruled} rules`);
      want(tip._html.indexOf('%</span>') > tip._html.indexOf('<div class="rule">'),
           `${sec}/${r.label}: a percentage is above the rule`);
    } else { single++;
      want(ruled===xtra, `${sec}/${r.label} is all one kind but drew ${ruled} rules`); }
  }));
  want(mixed>0, `${opener.name} has no row mixing flat and percent, so the rule is never exercised`);
  want(single>0, 'every row mixes both kinds, so "always draw it" would pass here');
  // An unfed row shows a number and no panel. Both halves are the check: the
  // ROW must still render (0% Fire Resist on Ultimate is the hole a sheet is
  // read for) while the tooltip must not open.
  want(empty>0, `every row of ${opener.name} is fed, so "never suppress" would pass here`);
  want(!/Nothing on this character/.test(html),
       'the empty-tooltip blurb is still in the page');
  want(withMod>0, `${opener.name} feeds none of the ${checked} modifier fields, `
    + 'so nothing here proves the percentages are listed');
}
// The footer named the checked rows by hand once and outlived the badge it
// described. It is generated from the table now, so assert it IS the table.
{
  const solved=B.sheet.flatMap(([,l])=>l.filter(r=>r.v).map(r=>r.label));
  want(solved.length>0, 'no row is marked as a checked formula');
  want(get('solvedrows')._html===solved.join(', '),
    `the footer lists "${get('solvedrows')._html}", the table says "${solved.join(', ')}"`);
  want(!/SOLVED/.test(shell), 'the footer still refers to a per-row SOLVED mark');
}

// ---- a buff toggle must not rebuild the skill panels ----------------------
// Collapsing a panel is browser state on the <details> element, so ANY rewrite
// of #skillpanels throws it away -- and a rewrite is invisible in the output,
// because renderSkills would produce byte-identical markup. Stamp a sentinel,
// fire a real toggle click, and see whether it survived.
{
  const panelEl=get('skillpanels'), gearEl=get('gear');
  const SENTINEL='<!--collapse-state-lives-here-->';
  panelEl._html+=SENTINEL; gearEl._html+=SENTINEL;
  const sheetBefore=get('sheet')._html;
  const tgEl={id:'', dataset:{t:opener.toggles[0].id}};
  tgEl.closest=sel=>sel==='.tg'?tgEl:null;
  fire('click', tgEl);
  want(panelEl._html.includes(SENTINEL),
       'toggling a buff re-rendered #skillpanels, which resets every collapsed pane');
  want(gearEl._html.includes(SENTINEL),
       'toggling a buff re-rendered the equipment list');
  // ...and it still has to do its actual job.
  want(get('sheet')._html!==sheetBefore,
       'toggling a buff did not recompute the character sheet');
  want(/class="tg"/.test(get('toggles')._html), 'the buff list vanished on toggle');
  panelEl._html=panelEl._html.replace(SENTINEL,'');
}
// ---- the character drawer -------------------------------------------------
// The page title block is gone; the <title> TAG is not the same thing and must
// stay, since it is what names the artifact.
want(!/<h1[ >]/.test(html), 'the masthead heading is still on the page');
want(!/class="mast"/.test(html), 'the masthead block is still on the page');
want(/<title>Allostria's Archive<\/title>/.test(html),
     "the <title> tag was removed with the heading -- it names the artifact");
want(!/__ORN_TOP__/.test(html), 'an unfilled ornament token is left in the page');
// The handle is the devotion tab, both states, and the list runs downward.
want(/\.railtab\{[^}]*background:url\("data:image\/png;base64,[^"]{400,}"\)/.test(html),
     'the drawer handle is not the tabopen texture');
want(/\.rail\[data-open="1"\] \.railtab\{[^}]*background-image:url\("data:image\/png;base64,/
     .test(html), 'the open drawer does not switch to the close button');
// Both boxes used to be pinned here as numbers (60x244 and a doubled 30x60).
// They are read off the textures now -- see "the drawer's two tabs" above --
// so a re-cut tab moves the page and the check together instead of failing
// here for being right.
want(/\.picker\{[^}]*flex-direction:column/.test(html),
     'the character list is not vertical');
want(/\.rail\[data-open="1"\] \.railbody\{width:\d+px\}/.test(html),
     'the drawer does not expand sideways');
// It floats OVER the page: fixed, above the hover tooltip, the handle first so
// that opening it cannot shove the handle sideways, and nothing indented to
// make room -- the rail reserves no space, so the sheet must not reflow.
want(/\.rail\{position:fixed;[^}]*z-index:(\d+)/.test(html) && +RegExp.$1 > 20,
     'the drawer does not clear the hover tooltip');
// The handle rides the drawer's RIGHT edge, so the panel comes first in the
// flex row. Shut, that puts the tab at the viewport edge; open, against the
// list. Nothing about this reflows the sheet -- the rail is fixed.
{
  const b=html.indexOf('id="railbody"'), t=html.indexOf('id="railtab"');
  want(b >= 0 && t >= 0, 'the drawer is missing its panel or its handle');
  want(b < t, "the handle is before the panel, so it sits on the drawer's left");
}
want(!/\.wrap\{[^}]*margin-left:|\.cols\{[^}]*margin-left:/.test(html),
     'the page is being indented to make room for the drawer');
{
  const rail=get('rail'), tab=get('railtab');
  const at=sel=>{const el={id:'',dataset:{}};el.closest=s=>s===sel?el:null;return el;};
  // the picker must have LEFT the top bar, not merely exist somewhere
  const bar=html.slice(html.indexOf('<div class="bar">'));
  want(!bar.slice(0, bar.indexOf('</div>\n\n')).includes('id="picker"'),
       'the character list is still inside the top bar');
  want(html.indexOf('id="picker"') < html.indexOf('<div class="bar">'),
       'the character list is not in the drawer');
  // The navigation bar sits between the character bar and the columns, seven
  // buttons wide, and every state it can wear has art behind it.
  const nb=html.indexOf('id="navbar"');
  want(nb>html.indexOf('<div class="bar">') && nb<html.indexOf('<div class="cols"'),
       'the navigation bar is not between the character bar and the columns');
  const navHtml=html.slice(nb, html.indexOf('</nav>', nb));
  const navBtns=navHtml.match(/<button class="navbtn[ "][^>]*>[^<]*/g)||[];
  want(navBtns.length===7, `the navigation bar has ${navBtns.length} buttons, not 7`);
  // The first is Character: its own art, this view, and selected on load.
  want(/class="navbtn char"[^>]*data-view="character"[^>]*aria-current="page"[^>]*>Character$/
         .test(navBtns[0]||''), `the first navigation button is not a selected Character: ${navBtns[0]}`);
  for (const st of ['', ':hover', ':active', ':disabled'])
    want(new RegExp(`\\.navbtn\\.char${st}\\{[^}]*border-image(-source)?:url\\("data:image/png;base64,[^"]{200,}`).test(html),
         `the Character button has no ${st||'resting'} art`);
  want(/\.navbtn\[aria-current="page"\]::after\{[^}]*url\("data:image\/png;base64,[^"]{200,}/.test(html),
       'the selected navigation button has no marker art');
  for (const st of [':hover', ':active', ':disabled'])
    want(new RegExp(`\\.navbtn${st}[^{]*\\{border-image-source:url\\("data:image/png;base64,[^"]{200,}`).test(html),
         `the navigation button has no ${st} art`);
  want(/\.navbtn\{[^}]*border-image:url\("data:image\/png;base64,[^"]{200,}/.test(html),
       'the navigation button has no resting (up) art');
  // Enabled, or the up/over/down states can never show.
  want(!/class="navbtn"[^>]*\bdisabled\b/.test(navHtml), 'a navigation button is still disabled');
  // The top bar shows difficulty, name and level -- in that order, a gem
  // between each -- and nothing else about the character.
  const who=get('who')._html, oc=B.characters.find(c=>c.name===opener.name)||opener;
  const parts=[...who.matchAll(/class="(ft|nm|gem)"[^>]*>([^<]*)</g)].map(m=>m[1]==='gem'?'◆':m[2]);
  want(JSON.stringify(parts)===JSON.stringify([['Normal','Elite','Ultimate'][oc.difficulty],'◆',oc.name,'◆',`Level ${oc.level}`]),
       `the top bar reads ${JSON.stringify(parts)}`);
  // shut -> open -> shut
  fire('click', at('.railtab'));
  want(rail.getAttribute('data-open')==='1' && tab.getAttribute('aria-expanded')==='true',
       'the tab did not open the drawer');
  fire('click', at('.railtab'));
  want(rail.getAttribute('data-open')==='0' && tab.getAttribute('aria-expanded')==='false',
       'the tab did not close the drawer again');
  // choosing a character closes it
  fire('click', at('.railtab'));
  const pick={id:'',dataset:{c:'1'}}; pick.closest=s=>s==='.pick'?pick:null;
  fire('click', pick);
  want(rail.getAttribute('data-open')==='0', 'picking a character left the drawer open');
  want(get('picker')._html.includes('class="pick"'), 'the drawer renders no characters');
  // ...and put the opener back. Every gate below reads the rendered DOM against
  // `opener`; leaving the page on character 1 made them check whoever sits
  // there, which passed only while that happened to be the opener.
  const back={id:'',dataset:{c:String(B.characters.indexOf(opener))}};
  back.closest=s=>s==='.pick'?back:null;
  fire('click', back);
  // The game's own character-select palette, off its style records. Resting
  // and highlighted are DIFFERENT records, so both must be present -- a page
  // carrying only one looks finished and is half the screen.
  for (const [v, hex, why] of [['--cs-name','#A68C66','name, resting'],
                               ['--cs-name-on','#FFE659','name, highlighted'],
                               ['--cs-class','#73664C','class line, resting'],
                               ['--cs-class-on','#F2BF4C','class line, highlighted']])
    want(new RegExp(`${v}:${hex}`,'i').test(html),
         `${v} (${why}) is not ${hex}, the value style_mainmenu_* carries`);
  want(/\.pick\{[^}]*font-family:Cinzel/.test(html),
       'the picker is not using the display face that stands in for Sava Pro');
  // Two lines, name over `Level N <title>`, and the title must be real.
  want(/class="cn">[^<]+<\/span>[\s\S]{0,40}class="cl">Level \d+/.test(get('picker')._html),
       'the picker rows are not name-over-level as the game prints them');
  for (const c of B.characters){
    want(c.title === null || typeof c.title === 'string',
         `${c.name}: class title is ${JSON.stringify(c.title)}`);
    if (c.masteries.length) want(c.title, `${c.name} has masteries but no class title`);
    if (c.title) want(!/^tag|\.dbr$/.test(c.title),
                      `${c.name}: class title renders raw "${c.title}"`);
  }
  // Pinned by name, because a title derived from the WRONG id order still
  // produces a real-looking class: 0309 is Sentinel, 0903 is nothing.
  const nu=B.characters.find(c=>c.name==='Nurgle');
  want(nu && nu.title==='Sentinel',
       `Nurgle is Occultist + Oathkeeper, which is Sentinel, got ${nu && nu.title}`);
  // A single mastery titles as ITSELF -- derived, not pinned to a name. It
  // used to name Leoric, who has since been played and taken a second mastery:
  // a character is not a fixed shape, so the RULE is what gets asserted and
  // whichever character currently has one mastery is what it is asserted on.
  const one=B.characters.filter(c=>c.masteries.length===1);
  for (const c of one)
    want(c.title===c.masteries[0].n,
         `${c.name} has one mastery (${c.masteries[0].n}) and should title as `
         + `it, got ${c.title}`);
  if (!one.length) uncovered.push(
    'no character has exactly one mastery, so "a single mastery titles as '
    + 'itself" is asserted against nothing');
}

// ---- the mastery portraits behind the page --------------------------------
// One per mastery of the SELECTED character, first left and second right, the
// right mirrored. The class number is re-derived from the record path the same
// way the bars are, so a portrait that does not match its mastery fails here.
{
  const bars=opener.skills.filter(s=>s.cls==='Skill_Mastery');
  const id=m=>(m && (m.path.match(/playerclass(\d+)/)||[])[1])||'';
  want(get('bgL').getAttribute('data-c')===id(bars[0]),
       `left portrait is class "${get('bgL').getAttribute('data-c')}", `
       + `${opener.name}'s first mastery is ${id(bars[0])}`);
  want(get('bgR').getAttribute('data-c')===id(bars[1]),
       `right portrait is class "${get('bgR').getAttribute('data-c')}", `
       + `${opener.name}'s second mastery is ${id(bars[1])}`);
  for (let i=1;i<=10;i++){
    const k=String(i).padStart(2,'0');
    want(new RegExp(`\\.classbg\\[data-c="${k}"\\]\\{background-image:url\\("data:image/png;base64,[^"]{2000,}"\\)\\}`)
         .test(html), `class ${k} has no portrait`);
  }
  want(/\.classbg\.right\{right:0; transform:scaleX\(-1\)\}/.test(html),
       'the right-hand portrait is not mirrored');
  want(/\.classbg\.left\{left:0\}/.test(html), 'the left portrait is not left-aligned');
  // Behind the content, not over it.
  want(/\.classbg\{[^}]*z-index:-1/.test(html) && /\.classbg\{[^}]*pointer-events:none/.test(html),
       'the portraits are not behind the page');
  // A one-mastery character must leave the other side empty rather than
  // repeating the first -- Leoric is the case, and he opens nothing here, so
  // drive it directly.
  const solo=B.characters.find(c=>c.skills.filter(s=>s.cls==='Skill_Mastery').length===1);
  if (!solo) uncovered.push(
    'no single-mastery character, so the empty-portrait-side branch runs in no '
    + 'gate -- freeze one to cover it');
  if (solo){
    const p=(solo.skills.find(s=>s.cls==='Skill_Mastery').path.match(/playerclass(\d+)/)||[])[1];
    want(p, `${solo.name}'s only mastery has no class number`);
  }
}
// ---- the navigation bar switches the view ---------------------------------
// Character is this view; any other button hides it. Both directions, so
// "never hides" and "never comes back" each fail.
{
  const nav=v=>{ const el={id:'', dataset:{view:v}};
    el.closest=s=>s==='.navbtn'?el:null; return el; };
  const mv=get('mainview');
  want(mv.hidden===false, 'the character view starts hidden');
  fire('click', nav('nav2'));
  want(mv.hidden===true, 'choosing another section did not hide the character view');
  fire('click', nav('character'));
  want(mv.hidden===false, 'choosing Character did not bring the character view back');
}

// ---- the pet verdict, driven through the page -----------------------------
// ⚠️ THE BRANCH THAT MATTERS BELONGS TO A CHARACTER THE PAGE DOES NOT OPEN ON.
// The opener fields a summon that scales off the PLAYER and can use nothing on
// this tab, so a gate that only reads what boots would prove the pet rule by
// never running it. The page's functions are private to new Function(code), so
// reach the other character the way a reader does -- pick them, and read the
// marks the page's own verdict() drew.
//
// LAST, and it puts the opener back: every gate above reads the rendered DOM,
// and this is the only block that moves off the character they were written
// against.
{
  const T=B.targets;
  const petRows=(B.sheet.find(x=>x[0]==='Pet Bonuses')||[,[]])[1];
  want(petRows.length>0 && petRows.every(r=>r.rule==='pet'),
       'the Pet Bonuses rows are not stamped with the pet rule');
  const pick=i=>{ const el={id:'',dataset:{c:String(i)}};
                  el.closest=sel=>sel==='.pick'?el:null; fire('click', el); };
  const petMarks=()=>{
    const grp=(get('sheet')._html.split('<div class="grp">')
      .find(g=>g.includes('>Pet Bonuses<')))||'';
    return [...grp.matchAll(/<span class="vd"(?: data-v="(\w+)")?><\/span>/g)].map(m=>m[1]||null);
  };
  const petDamage=c=>{
    const on=new Set(c.toggles.filter(t=>t.kind==='toggle'||t.kind==='granted').map(t=>t.id));
    return ((c.petContrib||{}).offensiveTotalDamageModifier||[])
      .reduce((n,[v,,tid])=>n+(!tid||on.has(tid)?v:0), 0);
  };
  const iOpen=B.characters.indexOf(opener);

  // 1. NO REAL PET -> every row avoid, however well fed the bucket is. This
  //    is the player-scaling trap as it renders: the opener has pet bonuses,
  //    and no summon that can spend them.
  want((opener.vctx.pets||[]).length===0,
       `${opener.name} has a real pet now, so this block no longer checks the `
       + `"summon that is not a pet" case -- rewrite it against a character that does not`);
  want(Object.keys(opener.petContrib||{}).length>0,
       `${opener.name} has no pet bonuses at all, so "fed but unusable" is vacuous here`);
  {
    const m=petMarks();
    want(m.length===petRows.length, `${m.length} pet gutters for ${petRows.length} rows`);
    want(m.every(v=>v==='avoid'),
         `${opener.name} has no pet that can use a bonus, so every pet row is `
         + `avoid -- got ${[...new Set(m)]}`);
  }

  // 2. A PET BUILD -> priority on every row, the zeroes included. That is the
  //    claim the rule makes and the one worth getting wrong: at this much
  //    invested pet damage a 0% pet resist is a hole, not a non-issue.
  const iPet=B.characters.findIndex(c=>(c.vctx.pets||[]).length>0
                                       && petDamage(c)>=T.petBuildDamage);
  if (iPet<0) uncovered.push(
    'no frozen character is a pet build, so the pet rule\'s priority branch '
    + 'runs in no gate -- freeze one to cover it');
  else {
    const c=B.characters[iPet];
    pick(iPet);
    const m=petMarks();
    want(m.length===petRows.length, `${m.length} pet gutters for ${c.name}`);
    want(m.every(v=>v==='priority'),
         `${c.name} carries ${petDamage(c)}% pet damage over ${T.petBuildDamage} `
         + `and ${c.vctx.pets.length} real pet skill(s), so every pet row is a `
         + `priority -- got ${[...new Set(m)]}`);
    const bt={}; for (const [f,rs] of Object.entries(c.petContrib||{}))
      for (const [v] of rs) bt[f]=(bt[f]||0)+v;
    const zero=petRows.filter(r=>!(r.f||[]).some(f=>bt[f]));
    want(zero.length>0 && m[petRows.indexOf(zero[0])]==='priority',
         `${c.name}'s empty pet rows must be priorities too -- a zero on a pet `
         + `build is the gap, and ${zero.length} row(s) are empty`);
    console.log(`pet verdict: ${opener.name} avoid on ${petRows.length} rows `
      + `(no real pet, ${Object.keys(opener.petContrib||{}).length} fields fed), `
      + `${c.name} priority on ${petRows.length} (${petDamage(c)}% pet damage, `
      + `pets: ${c.vctx.pets.join(', ')})`);
    pick(iOpen);                      // back to the character every gate above read
  }

  // 3. The middle of the rule -- a real pet, but not a pet build -- is where
  //    the row's own VALUE decides, and it is the only place the bucket the
  //    number comes from can be seen. No frozen character is in that window,
  //    so the bucket choice is asserted as SOURCE and the gap is printed
  //    rather than left looking covered.
  if (!B.characters.some(c=>(c.vctx.pets||[]).length>0 && petDamage(c)<T.petBuildDamage))
    uncovered.push('no frozen character has a real pet without being a pet '
      + 'build, so the pet rule never reads a row VALUE here -- which is the '
      + 'only case where judging a pet row against the player bucket would show');
  want(/const bt = bucket \? pt : t;/.test(html)
       && /rowNumber\(ch, entry\[2\] \? pt : t, row\)/.test(html),
       'a pet row is judged against the player bucket somewhere -- defensiveFire '
       + 'is a field in both, so the mark drawn and the mark a click steps from '
       + 'would silently differ');
  // Choosing a character must leave the same state booting does. The picker
  // used to clear every toggle, and a buff-gated pet bonus can cross the
  // pet-build threshold, so "which character you came from" could change advice.
  want(/function select\(i\)\{/.test(html)
       && !/if \(p\)\{ state\.i = /.test(html),
       'the picker sets the character up its own way again');
  {
    const on=(get('toggles')._html.match(/aria-pressed="true"/g)||[]).length;
    const dflt=opener.toggles.filter(t=>t.kind==='toggle'||t.kind==='granted').length;
    want(on===dflt, `after picking a character ${on} toggles are on, `
      + `${opener.name} boots with ${dflt}`);
  }
}

// ---- the collapse arrow is the game's own panel button --------------------
want(/details\.panel > summary\.hd::after\{[^}]*background:url\("data:image\/png;base64,[^"]{400,}"\)/
     .test(html), 'the collapse arrow is not the vendor panel texture');
want(/details\.panel:not\(\[open\]\) > summary\.hd::after\{transform:scaleY\(-1\)\}/.test(html),
     'the arrow does not flip when the pane is collapsed');
want(/summary\.hd:hover::after\{background-image:url\("data:image\/png;base64,/.test(html),
     'the arrow has no hover state');

console.log(`characters ${B.characters.length}  sheet rows ${rows}  worn ${geo}  toggles ${tgs}`);
console.log(`mastery tree: Nurgle ${nu.tree.length} skills, ${nu.tree.filter(s=>s.parent===null).length} roots, depths ${[...new Set(depths)].sort((a,b)=>a-b).join('/')}`);
console.log(`Nurgle with his 3 buffs: OA ${oa} (1975)  DA ${da} (2399)`);
// ⚠️ NOT failures, and NOT silence either. A branch no frozen character
// exercises is a branch this gate cannot speak for, and a green run that does
// not say so implies cover it does not have -- the same reason P7 prints which
// case a build is in rather than passing quietly.
if(uncovered.length) console.log('\nUNCOVERED (no frozen character exercises these)\n - '
                                 +uncovered.join('\n - '));
if(fail.length){ console.error('\nFAIL\n - '+fail.join('\n - ')); process.exit(1); }
console.log('\nOK');
