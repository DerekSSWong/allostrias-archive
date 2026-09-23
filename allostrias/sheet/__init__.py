"""The character sheet: profile.sqlite + catalogue.sqlite + the game archives
rendered as one local page.

    python3 -m allostrias.sheet.build      # cache/sheet/sheet.json
    python3 -m allostrias.sheet.assemble   # + shell.html -> one page
    python3 -m allostrias.sheet.serve      # the same page, with Refresh live

Build output goes to cache/, never beside the source: the bundle carries the
icon atlas, and that is Crate's art in a public repo.
"""
