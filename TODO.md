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
