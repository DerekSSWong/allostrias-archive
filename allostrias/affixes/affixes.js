/* GDAffixes:begin -- the affix scorer, spliced into the character sheet.
 *
 * PORTED FROM GD Lens's affixes.js: match, score, the grade scale, the unit
 * collapse and the per-line merge across a unit's level tiers. The corpus is
 * allostrias/affixes/build.py's, out of catalogue.sqlite; the constants are the
 * sheet's copied TARGETS (verdictWeight, coveragePower, bandCoverage,
 * gradeBands), which tests/test_sheet_targets.py holds to GD Lens's. Not one
 * number in this file is written down.
 *
 * Two departures from GD Lens, both the user's (2026-09-24):
 *   - A "+N to <skill>" line is wanted when the skill is in the character's
 *     skill window, and wanted as `priority`. No per-skill verdict.
 *   - Every affix that can drop is listed, not only the ones that match, and
 *     the ones carrying nothing this character wants are F with the rest --
 *     F is Silver, in the view and in the loot filter (2026-09-25).
 *
 * A record is
 *   [tag, name, suffix?, green?, level, lines, [[field, lo, hi]],
 *    [[skill, lineKey, lo, hi]], slotset, [[lineKey, text, hi, pet?]]]
 * with every string interned in the corpus's tables.
 */
(function (root) {
  'use strict';

  var IDX = null, T = null;

  function load(idx, targets) { IDX = idx; T = targets; return IDX; }

  /* ---- the scale -------------------------------------------------------
     Derived from the shipped constants the way targets.grade_thresholds()
     derives it. ⚠️ THE SIGN IS KEPT: `avoid` weighs -4 and plain w*w would
     score it +4, a line the reader rejected reading as one they asked for. */
  function points(w) { return (w < 0 ? -1 : 1) * (w * w) / 4.0; }

  function weight(v) {
    /* Throws rather than returning 0: an unknown verdict scored as "not wanted"
       makes the affix vanish with nothing to show it was considered. */
    if (!(v in T.verdictWeight)) throw new Error('no weight for verdict ' + v);
    return T.verdictWeight[v];
  }

  function thresholds() {
    var step = points(T.verdictWeight.priority) * T.bandCoverage;
    return T.gradeBands.map(function (g, i) { return [g, (i + 1) * step]; })
      .sort(function (a, b) { return b[1] - a[1]; });
  }

  function gradeOrder() { return ['F'].concat(T.gradeBands); }

  function grade(s) {
    var th = thresholds();
    for (var i = 0; i < th.length; i++) if (s >= th[i][1]) return th[i][0];
    return 'F';
  }

  /* ---- what the character wants -----------------------------------------
     ⚠️ `avoid` RANKS BELOW BOTH POSITIVES. One line can be read by several
     rows -- Elemental Resist is Fire, Cold AND Lightning -- and marking Cold
     `avoid` must not punish the line that is also delivering the Fire the
     character asked for. A positive on any row reading the line wins. */
  var RANK = { ignore: 0, avoid: 1, nice: 2, priority: 3 };

  function isPositive(v) { return v === 'priority' || v === 'nice'; }

  function usefulOf(got) {
    var out = {};
    Object.keys(got).forEach(function (k) { if (isPositive(got[k])) out[k] = got[k]; });
    return out;
  }

  /* field index -> the strongest verdict any row reading it holds. */
  function wantedFields(verdicts) {
    var want = {};
    IDX.fr.forEach(function (rows, fi) {
      var best = 'ignore';
      rows.forEach(function (key) {
        var v = verdicts[key] || 'ignore';
        if (RANK[v] > RANK[best]) best = v;
      });
      if (best !== 'ignore') want[fi] = best;
    });
    return want;
  }

  /* ---- one record ------------------------------------------------------
     (line -> best verdict), keyed on the LINE, never the field: a Min and its
     Max are one line, and counting them as two made a one-line affix a 2/2. */
  function match(rec, want, skills) {
    var best = {}, i, k;
    for (i = 0; i < rec[6].length; i++) {
      var fi = rec[6][i][0], v = want[fi];
      if (!v) continue;
      k = 'f' + IDX.lk[fi];
      if (RANK[v] > (best[k] ? RANK[best[k]] : 0)) best[k] = v;
    }
    for (i = 0; i < rec[7].length; i++) {
      var sv = skills[IDX.k[rec[7][i][0]]];
      if (sv) best['s' + rec[7][i][1]] = sv;
    }
    return best;
  }

  /* points x coverage ** coveragePower, coverage being useful lines over lines
     CARRIED -- so padding the sheet cannot use still costs.
     ⚠️ THE TWO SUMS RUN OVER DIFFERENT SETS: points over every MATCHED line so
     an avoided one subtracts; coverage over the USEFUL ones only. */
  function score(rec, want, skills) {
    var got = match(rec, want, skills), keys = Object.keys(got), total = rec[5];
    var good = Object.keys(usefulOf(got));
    if (!good.length || !total) return [0.0, 'F'];
    var pts = 0;
    keys.forEach(function (k) { pts += points(weight(got[k])); });
    var s = pts * Math.pow(good.length / total, T.coveragePower);
    return [s, grade(s)];
  }

  /* ---- a unit's lines --------------------------------------------------
     A unit is one affix on one slot family at every level tier it has, and
     the tiers are NOT a clean ladder: a line's best roll can sit below the top
     tier, and the top tier can lack a line a lower one carries. So each line is
     taken from whichever tier rolls it highest, and says which tier that is
     when it is not the top one. Lines the top tier prints come first, in its
     order; lines only lower tiers carry follow. */
  function linesOf(recs) {
    var top = recs.reduce(function (a, b) { return b[4] > a[4] ? b : a; });
    var best = {}, order = [];
    function consider(r, d, i) {
      var key = d[0] + '#' + i;
      var cur = best[key];
      if (!cur) { best[key] = { d: d, lvl: r[4] }; order.push(key); return; }
      if (d[2] !== null && (cur.d[2] === null || d[2] > cur.d[2] ||
          (d[2] === cur.d[2] && r[4] > cur.lvl))) best[key] = { d: d, lvl: r[4] };
    }
    /* `#i` numbers the lines sharing one key within a record -- a granted
       skill prints several -- so they merge position by position. */
    function each(r) {
      var seen = {};
      r[9].forEach(function (d) {
        seen[d[0]] = (seen[d[0]] || 0) + 1;
        consider(r, d, seen[d[0]]);
      });
    }
    each(top);
    recs.forEach(function (r) { if (r !== top) each(r); });
    return order.map(function (key) {
      var b = best[key];
      return { text: b.d[1], pet: !!b.d[3], lvl: b.lvl === top[4] ? null : b.lvl };
    });
  }

  /* ---- the whole corpus, for one character -----------------------------
     grade -> [card]. THE UNIT IS (tag, slot family, granted skills the
     character has), as GD Lens keys it: `Glacial` is four affixes, one tag can
     be armour in one record and jewellery in another, and two `Oathkeeper's`
     at one level grant different skills. A unit's grade is the best any of its
     records reaches; LEVEL IS NOT A TERM.

     ⚠️ F INCLUDES THE UNITS THAT MATCH NOTHING. GD Lens kept those apart as
     "ungraded"; the user merged them into F on 2026-09-25, in the view and in
     the loot filter alike, so F reads "little or nothing this character
     wants". */
  function catalogue(verdicts, skills) {
    var want = wantedFields(verdicts), units = {}, i;
    for (i = 0; i < IDX.r.length; i++) {
      var rec = IDX.r[i];
      var mine = rec[7].filter(function (s) { return skills[IDX.k[s[0]]]; })
        .map(function (s) { return s[0]; }).sort().join('|');
      var key = rec[0] + '|' + rec[8] + '|' + mine;
      (units[key] = units[key] || []).push(rec);
    }
    var order = gradeOrder(), by = {};
    order.forEach(function (g) { by[g] = []; });
    Object.keys(units).forEach(function (key) {
      var recs = units[key], g = 'F', union = {};
      recs.forEach(function (r) {
        var got = match(r, want, skills);
        var gg = score(r, want, skills)[1];
        if (order.indexOf(gg) > order.indexOf(g)) g = gg;
        Object.keys(usefulOf(got)).forEach(function (k) { union[k] = 1; });
      });
      var top = recs.reduce(function (a, b) { return b[4] > a[4] ? b : a; });
      var lv = recs.map(function (r) { return r[4]; });
      var card = {
        tag: IDX.t[top[0]], name: IDX.n[top[1]],
        kind: top[2] ? 'Suffix' : 'Prefix', tier: top[3] ? 'Rare' : 'Magical',
        slots: IDX.s[top[8]], lmin: Math.min.apply(null, lv), lmax: Math.max.apply(null, lv),
        lines: Math.max.apply(null, recs.map(function (r) { return r[5]; })),
        useful: Object.keys(union).length,
        effects: linesOf(recs), grade: g
      };
      by[card.grade].push(card);
    });
    Object.keys(by).forEach(function (g) {
      by[g].sort(function (a, b) {
        return a.kind === b.kind ? a.name.localeCompare(b.name) || a.lmin - b.lmin
                                 : (a.kind < b.kind ? -1 : 1);
      });
    });
    return by;
  }

  /* tag -> grade, collapsed best-of: the loot filter has one line per tag and
     cannot say two. Tags matching nothing are absent. `by` is a catalogue()
     already computed for the same inputs, when the caller has one. */
  function gradesByTag(verdicts, skills, by) {
    by = by || catalogue(verdicts, skills);
    var order = gradeOrder(), best = {};
    order.forEach(function (g) {
      by[g].forEach(function (c) {
        if (!(c.tag in best) || order.indexOf(g) > order.indexOf(best[c.tag])) best[c.tag] = g;
      });
    });
    return best;
  }

  /* ---- the loot filter --------------------------------------------------
     GENERATED, not rewritten: the header, the 481 affix names and the base
     lines ship from allostrias/affixes/filter.py, so the only thing decided
     here is each affix's colour -- the character-dependent part.

     ⚠️ SORTED BY TAG. Tags are ASCII (filter.py refuses anything else), so the
     default sort orders them by codepoint, as Python's `sorted` does. */
  function renderFilter(best, character) {
    var F = IDX.filter, lines = {}, t, counts = {};
    for (t in F.names) {
      var g = best[t];
      /* A tag no card holds -- an affix that cannot drop -- is F like any
         other affix this character has no use for. */
      g = g || 'F';
      counts[g] = (counts[g] || 0) + 1;
      lines[t] = [F.names[t], F.gradeColour[g]];
    }
    for (t in F.bases) lines[t] = F.bases[t];
    var out = F.header.map(function (l) { return l.split(F.mark).join(character); });
    Object.keys(lines).sort().forEach(function (tag) {
      out.push(tag + '={^' + lines[tag][1] + '}' + lines[tag][0] + F.reset);
    });
    return { text: out.join(F.eol) + F.eol, filename: F.filename, counts: counts,
             affix: Object.keys(F.names).length, base: Object.keys(F.bases).length };
  }

  root.GDAffixes = {
    load: load, catalogue: catalogue, gradesByTag: gradesByTag, renderFilter: renderFilter,
    score: score, match: match, wantedFields: wantedFields, grade: grade,
    gradeOrder: gradeOrder, thresholds: thresholds, linesOf: linesOf,
    index: function () { return IDX; }
  };
})(typeof globalThis !== 'undefined' ? globalThis : this);
/* GDAffixes:end */
