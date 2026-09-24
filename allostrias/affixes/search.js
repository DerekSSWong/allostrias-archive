/* The text filter, once.
 *
 * Three pages run this: the GD Catalogue's four tabs, the Transfer Stash, and
 * GD Lens's affix tab. It existed as three hand-kept copies until 2026-09-09,
 * and the cost was measurable -- the typed-word-order rule reached two of the
 * three and sat unnoticed on the third for three days, because that page's gate
 * drove only single-word probes and order cannot differ with one word.
 *
 * WHAT THIS OWNS: the matching rules, and nothing else. It is handed a list of
 * strings and a query, and answers whether they match and which spans to mark.
 *
 * WHAT IT DOES NOT OWN, on purpose: which strings go in the list. That is the
 * one genuinely per-surface decision -- the catalogue searches computed effect
 * lines, factions and set bonuses, the stash searches the tooltip lines the game
 * itself wrote, GD Lens searches affix rows -- and each page keeps a function
 * producing them. Same boundary that worked for the trigger vocabulary: the
 * library owns the rule, the page owns what it feeds in.
 *
 * The rules, each of which shipped as a bug first:
 *
 *  - PER LINE, never one merged blob. "aether resist" must not match a card
 *    carrying "Aether Damage" on one line and "Cold Resist" on another.
 *  - Words in the ORDER TYPED, not necessarily adjacent. "converted to physical"
 *    is a different query from "physical converted to"; adjacency is NOT
 *    required, because the same stat is phrased with different filler between
 *    the words and requiring it would defeat the synonym expansion.
 *  - damage <-> dmg, expanded per word, and a PREFIX of either half counts as
 *    the whole word already. Without that, typing "damage" letter by letter
 *    shows nothing until the final keystroke and then jumps.
 *  - Apostrophe-insensitive both ways: "deaths" finds "Death's" and vice versa.
 *  - `flat` and `%` are opposed modifiers over the same stat. Any prefix of
 *    "flat" counts, for the same anti-flicker reason.
 *  - AND/OR/NOT rows combine left to right with no precedence. An empty list has
 *    no opinion, so an untouched box never narrows anything.
 *  - Highlight scope follows search scope and does NOT inherit it: a row marks a
 *    line only when that line is the one satisfying the row's whole word set.
 *    Fixing one side alone is a bug all three pages have shipped.
 */
/* GDSearch:begin -- tools/check_page_search.js cuts between these two markers
   to run the conformance cases against the copy a page shipped. It asserts both
   are present, so renaming one fails loudly instead of checking nothing. */
(function (root) {
  'use strict';

  var APOSTROPHE_RE = /['’]/g;
  function stripApostrophes(s) { return String(s).replace(APOSTROPHE_RE, ''); }

  var SYNONYMS = [['damage', 'dmg']];

  function expandTermVariants(text) {
    var variants = {};
    variants[text] = 1;
    SYNONYMS.forEach(function (pair) {
      var a = pair[0], b = pair[1], next = {};
      Object.keys(variants).forEach(function (v) {
        next[v] = 1;
        if (v.indexOf(a) >= 0) next[v.split(a).join(b)] = 1;
        if (v.indexOf(b) >= 0) next[v.split(b).join(a)] = 1;
        // Still mid-word ("dam" on the way to "damage"): treat it as if the full
        // word were already typed, so the result set does not jump on the last key.
        if (a.indexOf(v) === 0) next[b] = 1;
        if (b.indexOf(v) === 0) next[a] = 1;
      });
      variants = next;
    });
    return Object.keys(variants);
  }

  function parseSearchWords(text) {
    var raw = stripApostrophes(String(text).toLowerCase()).split(/\s+/).filter(Boolean);
    var isFlat = function (w) { return w.length > 0 && 'flat'.indexOf(w) === 0; };
    return {
      requireFlat: raw.some(isFlat),
      words: raw.filter(function (w) { return !isFlat(w); }),
    };
  }

  /* Greedy: the EARLIEST occurrence of any of a word's variants at or after the
     previous word's end. Optimal for a subsequence test, since accepting a later
     occurrence can only lose matches; where two variants start at the same index
     the shorter wins, leaving the most room for the words still to place. */
  function wordsInOrder(line, variantsList) {
    var pos = 0;
    for (var i = 0; i < variantsList.length; i++) {
      var at = -1, len = 0, vs = variantsList[i];
      for (var j = 0; j < vs.length; j++) {
        var k = line.indexOf(vs[j], pos);
        if (k < 0) continue;
        if (at < 0 || k < at || (k === at && vs[j].length < len)) { at = k; len = vs[j].length; }
      }
      if (at < 0) return false;
      pos = at + len;
    }
    return true;
  }

  /* A query, parsed once. Callers memoize this per row: a keystroke repaints
     every row and the parse cannot have changed between them. */
  function parseQuery(text) {
    var p = parseSearchWords(text);
    return { requireFlat: p.requireFlat, variants: p.words.map(expandTermVariants) };
  }

  /* Does this ONE line satisfy this parsed query? The predicate both matching
     and highlighting call, so the same-line rule cannot be corrected on one side
     only. `line` must already be lowercased and apostrophe-stripped. */
  function lineMatches(line, q) {
    if (q.requireFlat && line.indexOf('%') >= 0) return false;
    return wordsInOrder(line, q.variants);
  }

  function normalise(s) { return stripApostrophes(String(s).toLowerCase()); }

  /* Any of these lines. `lines` may be raw: normalise() is applied here unless
     the caller says it has already done it, which every page does, since the
     normalised lines are memoized per record. */
  function termMatches(lines, text, alreadyNormalised) {
    var q = parseQuery(text);
    return lines.some(function (l) {
      return lineMatches(alreadyNormalised ? l : normalise(l), q);
    });
  }

  /* AND/OR/NOT rows, left to right, no precedence. Each row's operator applies
     to the running result so far against that row's own match. */
  function rowsMatch(lines, rows, alreadyNormalised) {
    var live = rows.filter(function (r) { return String(r.text).trim() !== ''; });
    if (!live.length) return true;
    var result = null;
    live.forEach(function (row, i) {
      var m = termMatches(lines, String(row.text).trim(), alreadyNormalised);
      if (i === 0) { result = m; return; }
      if (row.op === 'OR') result = result || m;
      else if (row.op === 'NOT') result = result && !m;
      else result = result && m;
    });
    return result;
  }

  /* The spans to mark in ONE line, as [start, end) pairs over the line's PLAIN
     text. A NOT row marks nothing: the card is here in spite of it, not because.
     A row contributes its words only when this line satisfies that row's whole
     word set -- the same test termMatches just made. */
  function markRanges(line, rows) {
    var lower = normalise(line), out = [];
    rows.forEach(function (r) {
      var t = String(r.text || '').trim();
      if (!t || r.op === 'NOT') return;
      var q = parseQuery(t);
      if (!lineMatches(lower, q)) return;
      q.variants.forEach(function (vs) {
        vs.forEach(function (v) {
          if (!v) return;
          var from = 0, i;
          while ((i = lower.indexOf(v, from)) >= 0) { out.push([i, i + v.length]); from = i + 1; }
        });
      });
    });
    if (!out.length) return out;
    // Merge overlaps so a span is not marked twice, which nests <mark> elements.
    out.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
    var merged = [out[0]];
    for (var i = 1; i < out.length; i++) {
      var last = merged[merged.length - 1];
      if (out[i][0] <= last[1]) last[1] = Math.max(last[1], out[i][1]);
      else merged.push(out[i]);
    }
    return merged;
  }

  root.GDSearch = {
    stripApostrophes: stripApostrophes,
    normalise: normalise,
    expandTermVariants: expandTermVariants,
    parseSearchWords: parseSearchWords,
    parseQuery: parseQuery,
    wordsInOrder: wordsInOrder,
    lineMatches: lineMatches,
    termMatches: termMatches,
    rowsMatch: rowsMatch,
    markRanges: markRanges,
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
/* GDSearch:end */
