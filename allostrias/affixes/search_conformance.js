/* What the shared text filter promises, as cases.
 *
 *   node tools/search_conformance.js            # check the library's own copy
 *   require('.../search_conformance.js')(impl)  # check a page's spliced copy
 *
 * EVERY PAGE RUNS THIS AGAINST THE COPY IT SHIPPED, not against the library's
 * file. A page splices the engine in at build time, so "the library is correct"
 * and "this page has the correct library" are different claims, and only the
 * second one is about the page in front of the reader.
 *
 * ⚠️ A NEW RULE GOES HERE FIRST. That is the whole point: three hand-kept copies
 * drifted because a rule could be added to one page and simply not exist on the
 * others, with nothing anywhere asking. A case added here fails on any surface
 * that has not taken the rule.
 *
 * These cases do NOT test what each page searches -- which lines go in is the
 * one per-surface decision, and each page's own gate covers it.
 */
'use strict';

// [label, lines, query, expected]
var MATCH_CASES = [
  ['a plain word matches',            ['+40 Health'], 'health', true],
  ['a word not present does not',     ['+40 Health'], 'energy', false],

  // PER LINE, never one merged blob.
  ['words must land on the SAME line', ['Aether Damage', 'Cold Resist'], 'aether resist', false],
  ['...and do match when they do',     ['Aether Resist', 'Cold Damage'], 'aether resist', true],

  // Typed word ORDER, adjacency NOT required.
  ['words in the order typed',         ['15% Physical converted to Aether'], 'physical converted', true],
  ['reversed is a different query',    ['15% Physical converted to Aether'], 'converted physical', false],
  ['order holds with filler between',  ['of Attack Damage converted to Health'], 'attack converted health', true],

  // damage <-> dmg, per word, prefix counts as the whole word.
  ['dmg is found by damage',           ['+25% Chaos dmg'], 'chaos damage', true],
  ['damage is found by dmg',           ['+25% Chaos Damage'], 'chaos dmg', true],
  ['a PREFIX of the synonym counts',   ['+25% Chaos dmg'], 'chaos dam', true],
  ['...from the first letter',         ['+25% Chaos dmg'], 'chaos d', true],

  // Apostrophes, both directions.
  ['typed without, present with',      ["Death's Whisper Hood"], 'deaths whisper', true],
  ['typed with, present without',      ['Deaths Whisper Hood'], "death's whisper", true],

  // flat and % are opposed modifiers over the same stat.
  ['flat excludes a percentage line',  ['+3% Health'], 'flat health', false],
  ['flat keeps the flat line',         ['+200 Health'], 'flat health', true],
  ['any prefix of flat counts',        ['+3% Health'], 'f health', false],
  ['% is just a character to find',    ['+3% Health', '+200 Health'], '% health', true],
  ['flat is not searched as a word',   ['+200 Health'], 'flat', true],
];

// [label, lines, rows, expected]
var ROW_CASES = [
  ['an empty row set has no opinion', ['+40 Health'], [], true],
  ['an empty row narrows nothing',    ['+40 Health'], [{ text: '  ' }], true],
  ['AND needs both',                  ['+40 Health', '+10 Energy'],
                                      [{ text: 'health' }, { op: 'AND', text: 'energy' }], true],
  ['AND fails on one',                ['+40 Health'],
                                      [{ text: 'health' }, { op: 'AND', text: 'energy' }], false],
  ['OR needs either',                 ['+40 Health'],
                                      [{ text: 'energy' }, { op: 'OR', text: 'health' }], true],
  ['NOT excludes',                    ['+40 Health'],
                                      [{ text: 'health' }, { op: 'NOT', text: 'health' }], false],
  ['NOT keeps what it does not name', ['+40 Health'],
                                      [{ text: 'health' }, { op: 'NOT', text: 'energy' }], true],
  ['left to right, no precedence',    ['+40 Health'],
                                      [{ text: 'energy' }, { op: 'OR', text: 'health' },
                                       { op: 'NOT', text: 'health' }], false],
];

// [label, line, rows, expected spans]
var MARK_CASES = [
  ['marks the word it matched',       '+40 Health', [{ text: 'health' }], [[4, 10]]],
  ['marks both words of a row',       '+25% Chaos Damage', [{ text: 'chaos damage' }], [[5, 10], [11, 17]]],
  ['marks nothing on an unmatched line', 'Cold Resist', [{ text: 'aether resist' }], []],
  ['a NOT row marks nothing',         '+40 Health', [{ text: 'health', op: 'NOT' }], []],
  ['marks through the synonym',       '+25% Chaos dmg', [{ text: 'chaos damage' }], [[5, 10], [11, 14]]],
  ['overlapping spans merge, never nest', 'health health', [{ text: 'health' }], [[0, 6], [7, 13]]],
];

function run(S, label) {
  var fails = [];
  function eq(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
  MATCH_CASES.forEach(function (c) {
    var got = S.termMatches(c[1], c[2]);
    if (got !== c[3]) fails.push(`${c[0]}: ${JSON.stringify(c[2])} on ${JSON.stringify(c[1])} gave ${got}`);
  });
  ROW_CASES.forEach(function (c) {
    var got = S.rowsMatch(c[1], c[2]);
    if (got !== c[3]) fails.push(`${c[0]}: gave ${got}`);
  });
  MARK_CASES.forEach(function (c) {
    var got = S.markRanges(c[1], c[2]);
    if (!eq(got, c[3])) fails.push(`${c[0]}: ${JSON.stringify(c[1])} gave ${JSON.stringify(got)}, wanted ${JSON.stringify(c[3])}`);
  });
  // Non-vacuity: a suite that ran nothing agrees with every bug.
  var n = MATCH_CASES.length + ROW_CASES.length + MARK_CASES.length;
  if (n < 25) fails.push(`only ${n} cases -- the suite has been emptied`);
  return { fails: fails, count: n, label: label || 'search conformance' };
}

module.exports = run;
module.exports.CASE_COUNT = MATCH_CASES.length + ROW_CASES.length + MARK_CASES.length;

if (require.main === module) {
  require('../search.js');
  var r = run(globalThis.GDSearch, 'gd-lib/search.js');
  r.fails.forEach(function (f) { console.error('FAIL: ' + f); });
  if (r.fails.length) process.exit(1);
  console.log(`search conformance ok -- ${r.count} cases against ${r.label}`);
}
