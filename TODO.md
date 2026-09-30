# TODO

- [ ] Implement settings.ini regeneration: on launch, if the file is missing or
      any path is empty/invalid, prompt the user to select the three paths and
      write the file. No silent fallback to a guessed path -- an unresolved
      path is an error, not a default.

- [ ] Settle the seed replay for the fields it still refuses, if an item carrying
      one is ever held. Move it into Item Assistant and relaunch:
      `tests/test_seedroll_game.py` reads the game's own tooltip from there.
      Until then such an item shows in the Gear Stash with its stats withheld.
      Where you'd get the most for the least effort:
      1. Craft any blueprint item and pick a resistance bonus. That should pin
         where defence bonuses sit in the roll order, which covers most of the
         42 refused bonuses in one go.
      2. Do the same with a damage bonus, which covers the rest.
      3. Buy a Legion Warhammer from a faction vendor.
      - affixes: Thunderstruck and of the Wind (`offensiveStunModifier`), of
        the Swamp (`offensiveSlowDefensiveReductionMin`), Draining
        (`offensiveManaBurnDrain`), Sapping (`offensivePercentCurrentLife` on an
        affix, `seedroll.BASE_ONLY`), of Fortification / of the Mountain / of
        the Tortoise (`defensiveBonusProtection` on an affix,
        `seedroll.BASE_ONLY`; on a base it is fixed, settled 2026-09-30)
      - items: Legion Warhammer
        (`defensivePhysicalChance`), Maw of Despair (`retaliationSlowManaLeach`),
        Malkadarr's Dreadblade (`offensiveFreezeMax`), Frostguard Girdle
        (`defensiveProtectionChance`), Screams of the Aether (`retaliationFearMin`)
      - crafting bonuses: 42 of the 69 are refused -- every resistance, damage,
        Armor-percent, block and duration bonus; only Char ones roll
        (`seedroll.MODIFIER_KINDS`). Also one sharing a field with an affix.

- [ ] Settle which item level an AFFIX's granted skill uses. An affix record
      has no `itemLevel`, so `item_stats.granted_skill_level()` hands it the
      level of the item it sits on -- assumed, not yet checked against the game
      (items themselves are: floor of the equation, 23 held items agree). Move
      any item carrying **Immovable** (Seismic Blast), **Frostborn** (Ice Spike)
      or **of Death's Chill** (Frigid Nova) into Item Assistant and relaunch:
      `tests/test_granted_level_game.py` then checks it and stops printing
      UNCHECKED. The Grim Dawn database's affix pages can't settle it: they show
      an affix detached from any item, i.e. at item level 0.
      - Floor vs round-half-even is not separated by any held item either; an
        item whose `itemLevel/4+1` ends in .5 and moves a printed line would.

- [ ] LOW VALUE. Let `bonuses` join the shared pass. Of its 6.5 s, 3.8 s is
      re-reading the 9,926 item records the pass already read; the other 1.3 s
      is 3,981 pool, bonus and skill records the pass would also have to hold.
      So about 3.8 s off a rebuild after a game patch (55.8 s), about 11 s off
      `test_rebuild`. Shape: a fourth consumer keeping only `bonusTableName`,
      the pet-bonus field and the skill-reference fields of any record carrying
      them, resolved against `item` in `finish` as `eligibility` does. Not worth
      the coupling `shared_pass.py` warns about unless suite time matters.
