# TODO

- [ ] Implement settings.ini regeneration: on launch, if the file is missing or
      any path is empty/invalid, prompt the user to select the three paths and
      write the file. No silent fallback to a guessed path -- an unresolved
      path is an error, not a default.

- [ ] Settle the seed replay for the fields it still refuses, if an item carrying
      one is ever held. Move it into Item Assistant and relaunch:
      `tests/test_seedroll_game.py` reads the game's own tooltip from there.
      Until then such an item shows in the Gear Stash with its stats withheld.
      - prefixes: Thunderstruck (`offensiveStunModifier`), Draining
        (`offensiveManaBurnDrain`), Sapping (`offensivePercentCurrentLife` on an
        affix, `seedroll.BASE_ONLY`)
      - Asterllonos, Star of the North / Stoneplate Waistguard / Ironlord
        Demolisher (`defensiveBonusProtection`), Legion Warhammer
        (`defensivePhysicalChance`), Maw of Despair (`retaliationSlowManaLeach`),
        Malkadarr's Dreadblade (`offensiveFreezeMax`), Frostguard Girdle
        (`defensiveProtectionChance`), Screams of the Aether (`retaliationFearMin`)
      - a crafting bonus with a damage, defence or retaliation field, or one
        sharing a field with an affix (`seedroll.MODIFIER_KINDS`)

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
