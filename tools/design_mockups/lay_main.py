"""Round 2 · main window: three panel/button layouts on top of variant A."""

from __future__ import annotations

import screen_a as A
import screen_d as D
from kit import Canvas
from lay_common import (
    OUT2,
    SB,
    TB,
    TH,
    W,
    H,
    S,
    clips_grid,
    command_bar,
    filmstrip,
    patient_line,
    proto_panel,
    side_tabs,
    status,
    step_bar,
    title,
    tool_rail_docked,
    viewer_area,
    viewer_corner,
)


def render_m1():
    """Mirrored (EchoPAC-like): protocols left, clips right, step docked under the image."""
    cv = Canvas(W, H, S, bg=TH["bg0"])
    p = cv.p
    title(p)
    A.patient_bar(p, TH)
    top, bottom = TB + A.PB, H - SB
    lpw, rcw = 344, 216
    proto_panel(p, 0, top, lpw, bottom, border="right")
    clips_grid(p, W - rcw, top, rcw, bottom, border="left")
    vx, vw = lpw, W - lpw - rcw
    A.viewer_toolbar(p, TH, vx, top, vw, 42)
    cine_h, step_h = 66, 58
    img_top = top + 42
    img_h = bottom - cine_h - step_h - img_top
    viewer_area(p, vx, img_top, vw, img_h, banner=False, pad=(22, 12, 60, 84))
    step_bar(p, vx, bottom - cine_h - step_h, vw, step_h)
    A.cine_bar(p, TH, vx, bottom - cine_h, vw, cine_h)
    status(p)
    return cv.save(OUT2 / "M1-main-mirrored.png")


def render_m2():
    """Filmstrip at the bottom, labelled tool rail on the left, compact one-row patient strip."""
    cv = Canvas(W, H, S, bg=TH["bg0"])
    p = cv.p
    title(p)
    pl = 42
    patient_line(p, TB, pl)
    top, bottom = TB + pl, H - SB
    rail, rpw = 70, 352
    tool_rail_docked(p, 0, top, rail, bottom)
    proto_panel(p, W - rpw, top, rpw, bottom)
    vx, vw = rail, W - rail - rpw
    film_h, cine_h = 112, 62
    img_h = bottom - film_h - cine_h - top
    viewer_area(p, vx, top, vw, img_h, banner=True, pad=(96, 12, 70, 90))
    viewer_corner(p, vx + vw - 14, top + img_h - 12)
    A.cine_bar(p, TH, vx, bottom - film_h - cine_h, vw, cine_h)
    filmstrip(p, vx, bottom - film_h, vw, film_h)
    status(p)
    return cv.save(OUT2 / "M2-main-filmstrip.png")


SIDE_ITEMS = [
    ("l-film", "Клипы", "24"),
    ("l-list-checks", "Протоколы", None),
    ("l-chart-line", "Расчёты", None),
    ("l-image", "Изображение", None),
    ("l-layers", "DICOM", None),
    (None, None, None),
    ("l-book-open", "Справочник", None),
    ("l-file-text", "Отчёт", None),
]


def render_m3():
    """Windows 11 command bar with labels + one switchable side panel; clips for the step under the image."""
    cv = Canvas(W, H, S, bg=TH["bg0"])
    p = cv.p
    title(p)
    cb = 46
    command_bar(p, TB, cb)
    pl = 36
    patient_line(p, TB + cb, pl, actions=False)
    top, bottom = TB + cb + pl, H - SB
    st, pw = 46, 340
    side_tabs(p, W - st, top, bottom, SIDE_ITEMS, active=1, w=st)
    proto_panel(p, W - st - pw, top, pw, bottom, border="left", tabs=None, header="Протоколы")
    vw = W - st - pw
    sug_h, cine_h = 92, 62
    img_h = bottom - sug_h - cine_h - top
    viewer_area(p, 0, top, vw, img_h, banner=True, pad=(96, 12, 70, 90))
    viewer_corner(p, vw - 14, top + img_h - 12)
    A.cine_bar(p, TH, 0, bottom - sug_h - cine_h, vw, cine_h)
    D.suggested_strip(p, 0, bottom - sug_h, vw, sug_h)
    status(p)
    return cv.save(OUT2 / "M3-main-commandbar.png")


if __name__ == "__main__":
    print(render_m1())
    print(render_m2())
    print(render_m3())
