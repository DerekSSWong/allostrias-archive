#!/usr/bin/env python3
"""sheet_shell.html + sheet.json -> one self-contained page."""
import json, os
from .. import settings as S
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(S.ROOT, 'cache', 'sheet')

def main(out_dir=None):
    out_dir = out_dir or OUT
    shell = open(os.path.join(HERE, 'shell.html')).read()
    b = json.load(open(os.path.join(out_dir, 'sheet.json')))
    ch = b['chrome']
    # One rule per mastery bar, emitted at build time rather than set inline on
    # every render: the page then carries only the class number on the track.
    bars = '\n'.join(f'.hd .track[data-c="{k}"]{{background-image:url("{v}")}}'
                     for k, v in sorted(ch['masteryBars'].items()))
    badges = '\n'.join(f'.sym[data-q="{k}"]{{background-image:url("{v}")}}'
                       for k, v in sorted(ch['badges'].items()))
    portraits = '\n'.join(f'.classbg[data-c="{k}"]{{background-image:url("{v}")}}'
                          for k, v in sorted(ch['classImages'].items()))

    for token, value in [('__ATLAS__', b['atlas']), ('__BORDER__', ch['border']),
                         ('__BORDER_SLICE__', str(ch['borderSlice'])),
                         ('__SLOT__', ch['slot']),
                         ('__OPT_FRAME__', ch['optFrame']),
                         ('__OPT_SLICE__', str(ch['optSlice'])),
                         ('__BTN_UP__', ch['btnUp']), ('__BTN_OVER__', ch['btnOver']),
                         ('__BTN_DOWN__', ch['btnDown']),
                         ('__BTN_DISABLED__', ch['btnDisabled']),
                         ('__BTN_CAP__', str(ch['btnCap'])),
                         ('__BTN_H__', str(ch['btnHeight'])),
                         ('__TITLE_TOP__', str(ch['titleTop'])),
                         ('__TITLE_H__', str(ch['titleHeight'])),
                         ('__FOOT_B__', str(ch['footBottom'])),
                         ('__FOOT_H__', str(ch['footHeight'])),
                         ('__CREST_T__', ch['crestTop']),
                         ('__CREST_T_W__', str(ch['crestTopSize'][0])),
                         ('__CREST_T_H__', str(ch['crestTopSize'][1])),
                         ('__CREST_T_INSET__', str(ch['crestTopInset'])),
                         ('__CREST_B__', ch['crestBottom']),
                         ('__CREST_B_W__', str(ch['crestBottomSize'][0])),
                         ('__CREST_B_H__', str(ch['crestBottomSize'][1])),
                         ('__CREST_B_INSET__', str(ch['crestBottomInset'])),
                         ('__FOLDER__', ch['folder']),
                         ('__FOLDER_SLICE__', str(ch['folderSlice'])),
                         ('__CLASP__', ch['clasp']),
                         ('__CLASP_W__', str(ch['claspSize'][0])),
                         ('__CLASP_H__', str(ch['claspSize'][1])),
                         ('__NOTCH__', ch['notch']),
                         ('__NOTCH_W__', str(ch['notchSize'][0])),
                         ('__NOTCH_H__', str(ch['notchSize'][1])),
                         ('__TAB_OPEN_W__', str(ch['tabOpenSize'][0])),
                         ('__TAB_OPEN_H__', str(ch['tabOpenSize'][1])),
                         ('__TAB_CLOSE_W__', str(ch['tabCloseSize'][0])),
                         ('__TAB_CLOSE_H__', str(ch['tabCloseSize'][1])),
                         ('__TAB_OPEN__', ch['tabOpen']),
                         ('__TAB_OPEN_OVER__', ch['tabOpenOver']),
                         ('__TAB_CLOSE__', ch['tabClose']),
                         ('__TAB_CLOSE_OVER__', ch['tabCloseOver']),
                         ('__DIVIDER__', ch['divider']), ('__SHEET_BG__', ch['sheetBg']),
                         ('__VD_PRIORITY__', ch['vdPriority']),
                         ('__VD_NICE__', ch['vdNice']),
                         ('__VD_IGNORE__', ch['vdIgnore']),
                         ('__VD_AVOID__', ch['vdAvoid']),
                         ('__DIVIDER_RULE__', ch['dividerRule']),
                         ('__DIVIDER_RULE_H__', str(ch['dividerRuleH'])),
                         ('__ARROW__', ch['panelArrow']),
                         ('__ARROW_OVER__', ch['panelArrowOver']),
                         ('__MASTERY_BARS__', bars), ('__QUALITY_SYMBOLS__', badges),
                         ('__CLASS_IMAGES__', portraits)]:
        if token not in shell:
            raise SystemExit(f'{token} missing from the shell')
        shell = shell.replace(token, value)
    data = {k: b[k] for k in ('characters', 'sheet', 'targets', 'frames', 'sheetSize')}
    shell = shell.replace('__BUNDLE__',
        json.dumps(data, separators=(',', ':')).replace('</', '<\\u002f'))
    p = os.path.join(out_dir, 'character_sheet.html')
    open(p, 'w').write(shell)
    print(f'{os.path.getsize(p)/1e6:.2f} MB -> {p}')

if __name__ == '__main__':
    main()
