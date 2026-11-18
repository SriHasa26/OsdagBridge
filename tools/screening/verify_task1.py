"""Automated GUI verification for Subtask I: 2D CAD inline editing (local only, excluded from git).

    python tools/screening/verify_task1.py              # real visible window
    python tools/screening/verify_task1.py --offscreen  # fallback

Double-clicks the real painted labels (rectangles recorded by the canvases), types with QTest,
and checks input_dict, the InputDock field and the redrawn label text.
"""
import os
import sys
import tempfile
import threading
from pathlib import Path

if "--offscreen" in sys.argv:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

ROOT = Path(__file__).resolve().parents[2]
SHOTS = Path(os.environ.get("SCREENING_SHOTS_DIR", tempfile.gettempdir())) / "osdagbridge_screening" / "task1_screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)
RESULTS = []


def report(code):
    width = max((len(n) for n, _, _ in RESULTS), default=10)
    print("\n" + "=" * (width + 12))
    for name, ok, detail in RESULTS:
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}" + ("" if ok else f"   <- {detail}"))
    failed = sum(1 for _, ok, _ in RESULTS if not ok)
    print("=" * (width + 12))
    print(f"{len(RESULTS) - failed} passed, {failed} failed")
    sys.stdout.flush()
    os._exit(code)


threading.Timer(60, lambda: (RESULTS.append(("TIMEOUT (60 s)", False, "run aborted")), report(3))).start()

from PySide6.QtCore import Qt, QEvent, QPoint, QSize
from PySide6.QtGui import QFocusEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QScrollArea

import osdagbridge.desktop.__main__ as appmod
from osdagbridge.core.utils.common import *                       # noqa: F401,F403
from osdagbridge.core.bridge_types.plate_girder.defaults import solve_extend_basic_input_dict
from osdagbridge.core.bridge_types.plate_girder.plategirderbridge import PlateGirderBridge
from osdagbridge.desktop.ui.docks.cad_cross_section import CrossSectionCADWidget
from osdagbridge.desktop.ui.template_page import CustomWindow
import osdagbridge.desktop.ui.template_page as tp
import osdagbridge.desktop.ui.dialogs.additional_input.additional_inputs as ai_mod
from osdagbridge.desktop.ui.dialogs.custom_messagebox import CustomMessageBox as RealBox, MessageBoxType

app = QApplication(sys.argv)
app.setStyleSheet(appmod.load_stylesheet())

CALLS = []
ANSWER = {"value": "OK"}
SHOT_ON = {"invalid": False}


class RecordingBox(RealBox):
    """Real standard dialog; exec() records, screenshots the first 'invalid value' box, never blocks."""

    def __init__(self, title="Message", text="Message", informativeText="", buttons=["OK"],
                 dialogType=MessageBoxType.Information):
        super().__init__(title=title, text=text, informativeText=informativeText,
                         buttons=buttons, dialogType=dialogType)
        self._rec = {"title": title, "text": text, "type": dialogType}

    def exec(self):
        CALLS.append(self._rec)
        if SHOT_ON["invalid"] and self._rec["title"] == "Input Error":
            SHOT_ON["invalid"] = False
            self.resize(self.sizeHint().expandedTo(QSize(520, 170)))
            self.grab().save(str(SHOTS / "4_invalid_value_error.png"))
        self.deleteLater()
        return ANSWER["value"]


tp.CustomMessageBox = RecordingBox
ai_mod.CustomMessageBox = RecordingBox


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))


def pump(ms=60):
    QTest.qWait(ms)


# ── real window ──────────────────────────────────────────────────────────────
window = CustomWindow("OsdagBridge", PlateGirderBridge)
window.showMaximized()
pump(800)
cross = window.cad_comp_widget.cross_section_widget
top = window.cad_comp_widget.top_view_widget
D = window.input_dict

# spy on the drawn label texts (what the user actually sees)
DRAWN = {}


def spy(canvas, tag):
    orig = canvas.draw_text_with_background

    def wrapper(painter, x, y, text, *a, **k):
        if k.get("label_key"):
            DRAWN[(tag, k["label_key"])] = text.replace("\n", " ")
        return orig(painter, x, y, text, *a, **k)
    canvas.draw_text_with_background = wrapper


spy(cross, "cross")
spy(top, "top")


def repaint_all():
    cross.repaint(); top.repaint(); pump(30)


def drawn(tag, key):
    return DRAWN.get((tag, key), "")


def label_pos(canvas, key):
    for rect, k in canvas._label_rects:
        if k == key:
            return rect.center().toPoint()
    return None


def reveal(canvas, pos):
    p = canvas
    while p is not None and not isinstance(p, QScrollArea):
        p = p.parentWidget()
    if p is not None:
        p.ensureVisible(pos.x(), pos.y(), 120, 40)
        pump(30)


def dbl(canvas, key):
    pos = label_pos(canvas, key)
    if pos is None:
        return None
    reveal(canvas, pos)
    QTest.mouseDClick(canvas, Qt.LeftButton, Qt.NoModifier, pos)
    pump(30)
    return canvas._label_editor


def commit_by_enter(editor_canvas, text):
    ed = editor_canvas._label_editor
    ed.selectAll()
    QTest.keyClicks(ed, text)
    QTest.keyClick(ed, Qt.Key_Return)
    pump(120)           # the commit is delivered via QTimer.singleShot(0)
    repaint_all()


def dock_text(key):
    return window.input_dock.input_widget.findChild(QLineEdit, key).text()


# ── setup: Span 30 / Carriageway 10.5 through the dock ───────────────────────
for key, text in ((KEY_SPAN, "30"), (KEY_CARRIAGEWAY_WIDTH, "10.5")):
    window.input_dock.input_widget.findChild(QLineEdit, key).setText(text)
pump(200)
if not D.get(KEY_TS_NO_OF_GIRDERS):
    solve_extend_basic_input_dict(D)
window.update_cad_from_inputs()
repaint_all()
check("app window launched, canvases painted", cross._label_rects and top._label_rects,
      f"cross={len(cross._label_rects)} top={len(top._label_rects)}")
check("setup: Span 30 / Carriageway 10.5", D[KEY_SPAN] == "30" and D[KEY_CARRIAGEWAY_WIDTH] == "10.5")
n_girders = int(D[KEY_TS_NO_OF_GIRDERS]); overall = float(D[KEY_TS_OVERALL_WIDTH])
check("canvases only editable in the main window",
      cross.inline_edit_enabled and top.inline_edit_enabled)

# screenshots: before
window.cad_comp_widget.grab().save(str(SHOTS / "2_before_edit.png"))

# ── labels registered under KEY_* ────────────────────────────────────────────
need_cross = [KEY_CARRIAGEWAY_WIDTH, KEY_TS_DECK_THICKNESS, KEY_TS_GIRDER_SPACING, KEY_TS_DECK_OVERHANG, KEY_TS_OVERALL_WIDTH]
need_top = [KEY_SPAN, KEY_TS_GIRDER_SPACING, KEY_MP_CB_SPACING]
check("cross-section registers all its labels", all(label_pos(cross, k) for k in need_cross),
      str([k for k in need_cross if not label_pos(cross, k)]))
check("top view registers all its labels", all(label_pos(top, k) for k in need_top),
      str([k for k in need_top if not label_pos(top, k)]))

# ── Carriageway Width (cross-section): double-click, type, Enter ─────────────
ed = dbl(cross, KEY_CARRIAGEWAY_WIDTH)
check("double-click on Carriageway Width opens the editor", ed is not None)
check("editor prefilled with current value (10.5)", ed is not None and ed.text() == "10.5", ed.text() if ed else "")
check("editor text selected", ed is not None and ed.selectedText() == ed.text())
cross.grab()  # layout the overlay before the screenshot
reveal(cross, label_pos(cross, KEY_CARRIAGEWAY_WIDTH))
cross.grab().save(str(SHOTS / "1_editor_open.png"))
commit_by_enter(cross, "12")
check("Carriageway: input_dict updated", D[KEY_CARRIAGEWAY_WIDTH] == "12", D[KEY_CARRIAGEWAY_WIDTH])
check("Carriageway: InputDock field updated", dock_text(KEY_CARRIAGEWAY_WIDTH) == "12", dock_text(KEY_CARRIAGEWAY_WIDTH))
check("Carriageway: label redrawn", drawn("cross", KEY_CARRIAGEWAY_WIDTH) == "Carriageway Width = 12.00 m",
      drawn("cross", KEY_CARRIAGEWAY_WIDTH))
check("Carriageway: layout re-solved, girder count kept",
      float(D[KEY_TS_OVERALL_WIDTH]) > overall and int(D[KEY_TS_NO_OF_GIRDERS]) == n_girders)
check("Carriageway: Overall Bridge Width label follows", "m" in drawn("cross", KEY_TS_OVERALL_WIDTH))
overall = float(D[KEY_TS_OVERALL_WIDTH])
window.cad_comp_widget.grab().save(str(SHOTS / "3_after_edit.png"))

# ── Deck Thickness ───────────────────────────────────────────────────────────
dbl(cross, KEY_TS_DECK_THICKNESS); commit_by_enter(cross, "300")
check("Deck Thickness: dict + label", D[KEY_TS_DECK_THICKNESS] == "300" and
      drawn("cross", KEY_TS_DECK_THICKNESS) == "Deck Thickness = 300 mm", drawn("cross", KEY_TS_DECK_THICKNESS))

# ── Span Length (top view) + derived bracing spacing ─────────────────────────
dbl(top, KEY_SPAN); commit_by_enter(top, "40")
check("Span: dict updated", D[KEY_SPAN] == "40", D[KEY_SPAN])
check("Span: InputDock field updated", dock_text(KEY_SPAN) == "40", dock_text(KEY_SPAN))
check("Span: label redrawn", drawn("top", KEY_SPAN) == "Span Length = 40.0 m", drawn("top", KEY_SPAN))
check("Span: Bracing Spacing derived = span/(n+1) in dict (n=1)", D[KEY_MP_CB_SPACING] == "20.000", D[KEY_MP_CB_SPACING])
check("Span: canvas bracing spacing follows (20 m)", top.params["cross_bracing_spacing"] == 20000.0,
      str(top.params["cross_bracing_spacing"]))
# The canvas only draws the Bracing Spacing dimension when there are >= 2 bracing lines:
D[KEY_MP_CB_NO_OF_CROSS_BRACINGS] = 3          # as if set earlier in Additional Inputs
dbl(top, KEY_SPAN); commit_by_enter(top, "44")
check("Span (n=3): Bracing Spacing = 44/4 in dict", D[KEY_MP_CB_SPACING] == "11.000", D[KEY_MP_CB_SPACING])
check("Span (n=3): Bracing Spacing label redrawn", drawn("top", KEY_MP_CB_SPACING) == "Bracing Spacing = 11.00 m",
      drawn("top", KEY_MP_CB_SPACING))
dbl(top, KEY_SPAN); commit_by_enter(top, "40")  # back to 40 for the rest

# ── Girder Spacing from both views, derived Overhang ─────────────────────────
dbl(cross, KEY_TS_GIRDER_SPACING); commit_by_enter(cross, "2")
check("Girder Spacing (cross-section): dict", float(D[KEY_TS_GIRDER_SPACING]) == 2.0, str(D[KEY_TS_GIRDER_SPACING]))
exp_oh = (overall - (n_girders - 1) * 2.0) / 2.0
check("Girder Spacing: count fixed, overhang derived", int(D[KEY_TS_NO_OF_GIRDERS]) == n_girders and
      abs(float(D[KEY_TS_DECK_OVERHANG]) - exp_oh) < 1e-3, f"{D[KEY_TS_DECK_OVERHANG]} vs {exp_oh}")
check("Girder Spacing: label redrawn in both views",
      drawn("cross", KEY_TS_GIRDER_SPACING) == "Girder Spacing = 2.00 m" and "= 2.00 m" in drawn("top", KEY_TS_GIRDER_SPACING),
      f"{drawn('cross', KEY_TS_GIRDER_SPACING)} | {drawn('top', KEY_TS_GIRDER_SPACING)}")
check("Girder Spacing: Overhang label redrawn", drawn("cross", KEY_TS_DECK_OVERHANG) == f"Overhang = {exp_oh:.2f} m",
      drawn("cross", KEY_TS_DECK_OVERHANG))
dbl(top, KEY_TS_GIRDER_SPACING); commit_by_enter(top, "2.2")
check("Girder Spacing (top view) edit works", float(D[KEY_TS_GIRDER_SPACING]) == 2.2, str(D[KEY_TS_GIRDER_SPACING]))

# ── read-only labels ─────────────────────────────────────────────────────────
for canvas, key, nm in ((cross, KEY_TS_DECK_OVERHANG, "Overhang"), (cross, KEY_TS_OVERALL_WIDTH, "Overall Bridge Width"),
                        (top, KEY_MP_CB_SPACING, "Bracing Spacing")):
    snap = dict(D)
    e = dbl(canvas, key)
    check(f"read-only: {nm} opens no editor", e is None and D == snap)

# ── Esc cancels ──────────────────────────────────────────────────────────────
before = dict(D)
ed = dbl(cross, KEY_CARRIAGEWAY_WIDTH)
ed.selectAll(); QTest.keyClicks(ed, "13"); QTest.keyClick(ed, Qt.Key_Escape); pump(120)
check("Esc cancels: editor gone, nothing changed", cross._label_editor is None and D == before)

# ── focus-out commits / click elsewhere commits / unchanged = no change ─────
ed = dbl(cross, KEY_TS_DECK_THICKNESS)
ed.selectAll(); QTest.keyClicks(ed, "310")
QApplication.sendEvent(ed, QFocusEvent(QEvent.FocusOut)); pump(120); repaint_all()
check("focus-out commits", D[KEY_TS_DECK_THICKNESS] == "310", D[KEY_TS_DECK_THICKNESS])
ed = dbl(cross, KEY_TS_DECK_THICKNESS)
ed.selectAll(); QTest.keyClicks(ed, "320")
QTest.mouseClick(cross, Qt.LeftButton, Qt.NoModifier, QPoint(3, 3)); pump(120); repaint_all()
check("click elsewhere on the canvas commits", D[KEY_TS_DECK_THICKNESS] == "320", D[KEY_TS_DECK_THICKNESS])
snap = dict(D); CALLS.clear()
dbl(cross, KEY_TS_DECK_THICKNESS); QTest.keyClick(cross._label_editor, Qt.Key_Return); pump(120)
check("Enter without changing the value: no update, no dialog", D == snap and not CALLS)
dbl(cross, KEY_TS_DECK_THICKNESS); e = cross._label_editor; e.selectAll(); QTest.keyClick(e, Qt.Key_Delete)
QTest.keyClick(e, Qt.Key_Return); pump(120)
check("empty box keeps the old value silently", D == snap and not CALLS)

# ── invalid values: error dialog + old value kept ────────────────────────────
def invalid(canvas, key, text, label, dict_key, want_in_msg=None):
    snap = dict(D); CALLS.clear()
    dbl(canvas, key); commit_by_enter(canvas, text)
    ok = (len(CALLS) == 1 and CALLS[0]["title"] == "Input Error" and CALLS[0]["type"] == MessageBoxType.Critical
          and (want_in_msg is None or want_in_msg in CALLS[0]["text"]))
    check(f"invalid {label}: standard Error dialog", ok, str(CALLS))
    check(f"invalid {label}: old value kept in input_dict", D == snap and D[dict_key] == snap[dict_key])


SHOT_ON["invalid"] = True
invalid(cross, KEY_CARRIAGEWAY_WIDTH, "1", "carriageway 1 m (below IRC minimum)", KEY_CARRIAGEWAY_WIDTH)
check("invalid carriageway: dock field + label unchanged",
      dock_text(KEY_CARRIAGEWAY_WIDTH) == "12" and drawn("cross", KEY_CARRIAGEWAY_WIDTH) == "Carriageway Width = 12.00 m")
invalid(top, KEY_SPAN, "5", "span 5 m (out of range)", KEY_SPAN, "Span must be between")
invalid(cross, KEY_TS_DECK_THICKNESS, "50", "deck thickness 50 mm", KEY_TS_DECK_THICKNESS, "at least 100")
too_big = f"{float(D[KEY_TS_OVERALL_WIDTH]) / (n_girders - 1) + 0.5:.2f}"   # passes the range check, overhang < 0
invalid(cross, KEY_TS_GIRDER_SPACING, too_big, f"girder spacing {too_big} m (negative overhang)", KEY_TS_GIRDER_SPACING)
invalid(cross, KEY_TS_GIRDER_SPACING, "-", "non-number '-'", KEY_TS_GIRDER_SPACING, "numeric")

# ── lock guard ───────────────────────────────────────────────────────────────
window.input_dock.is_locked = True
check("locked inputs: double-click opens no editor", dbl(cross, KEY_CARRIAGEWAY_WIDTH) is None)
window.input_dock.is_locked = False

# ── Additional Inputs dialog stays consistent (D2) + redraw cache ────────────
dlg = window._additional_inputs_dialog
preview = dlg.findChild(CrossSectionCADWidget, KEY_TS_CAD_PREVIEW)
check("Additional Inputs preview canvas is not editable", preview is not None and preview.inline_edit_enabled is False)
dbl(cross, KEY_TS_DECK_THICKNESS); commit_by_enter(cross, "280")
solve_extend_basic_input_dict  # (imported above; dict already solved by the edits)
window._show_additional_inputs(); pump(150)
check("dialog opens with the CAD-edited deck thickness",
      float(dlg.findChild(QLineEdit, KEY_TS_DECK_THICKNESS).text()) == 280.0,
      dlg.findChild(QLineEdit, KEY_TS_DECK_THICKNESS).text())
# NOTE (pre-existing upstream behaviour, not asserted): opening the dialog re-derives the girder
# spacing from the girder count (refresh_typical_section runs the type handlers, which transiently
# change the crash-barrier width); it does so for a spacing saved from the dialog itself as well.
check("input_dict keeps the CAD-edited girder spacing while the dialog is open (2.2)",
      float(D[KEY_TS_GIRDER_SPACING]) == 2.2, str(D[KEY_TS_GIRDER_SPACING]))
dlg.findChild(QLineEdit, KEY_TS_DECK_THICKNESS).setText("260")          # edit inside the dialog...
ANSWER["value"] = "OK"; dlg.save_button.click(); pump(120)              # ...and Save (pushes cad.params directly, bypassing the cache)
dlg.title_bar.btn_close.click(); pump(120)
check("dialog Save commits the dialog's own edit (deck thickness 260)", float(D[KEY_TS_DECK_THICKNESS]) == 260.0,
      str(D[KEY_TS_DECK_THICKNESS]))
repaint_all()
dbl(cross, KEY_TS_DECK_THICKNESS); commit_by_enter(cross, "280")
check("redraw cache stays consistent: edit back to the cached value is not skipped",
      D[KEY_TS_DECK_THICKNESS] == "280" and drawn("cross", KEY_TS_DECK_THICKNESS) == "Deck Thickness = 280 mm",
      drawn("cross", KEY_TS_DECK_THICKNESS))

# ── Interaction with Additional Inputs (D15): a CAD edit syncs the dialog but is not a dialog edit ──
ANSWER["value"] = "OK"; CALLS.clear()
window._show_additional_inputs(); pump(150)
check("D15: dialog open and clean", dlg.isVisible() and dlg.is_modified is False)
# The dialog is application-modal, so the GUI cannot edit the CAD meanwhile; call the slot directly.
window._on_cad_parameter_edited(KEY_TS_DECK_THICKNESS, "290"); pump(150)
check("D15: CAD edit while the dialog is open updates the shared dict", D[KEY_TS_DECK_THICKNESS] == "290",
      str(D[KEY_TS_DECK_THICKNESS]))
check("D15: ...and the dialog's working_input_dict", str(dlg.working_input_dict[KEY_TS_DECK_THICKNESS]) == "290")
check("D15: ...without setting is_modified (the sync is not a dialog edit)", dlg.is_modified is False)
CALLS.clear(); dlg.title_bar.btn_close.click(); pump(150)
check("D15: closing afterwards raises no unsaved-changes prompt", (not dlg.isVisible()) and not CALLS, str(CALLS))
window._show_additional_inputs(); pump(150)
check("D15: reopened dialog shows the CAD-edited value",
      float(dlg.findChild(QLineEdit, KEY_TS_DECK_THICKNESS).text()) == 290.0)
dlg.findChild(QLineEdit, KEY_WC_THICKNESS).setText("60")                 # a real edit inside the dialog
check("D15: a real dialog edit sets is_modified", dlg.is_modified is True)
window._on_cad_parameter_edited(KEY_TS_DECK_THICKNESS, "300"); pump(150)
check("D15: a CAD edit on top keeps is_modified True", dlg.is_modified is True)
CALLS.clear(); dlg.save_button.click(); pump(150)
check("D15: Save commits both the dialog edit and the CAD edit",
      str(D[KEY_TS_DECK_THICKNESS]) == "300" and float(D[KEY_WC_THICKNESS]) == 60.0
      and dlg.is_modified is False, f"{D[KEY_TS_DECK_THICKNESS]} {D[KEY_WC_THICKNESS]} {dlg.is_modified}")
CALLS.clear(); dlg.title_bar.btn_close.click(); pump(150)
check("D15: close after Save: no prompt", (not dlg.isVisible()) and not CALLS)

files = ("1_editor_open.png", "2_before_edit.png", "3_after_edit.png", "4_invalid_value_error.png")
check("4 screenshots written", all((SHOTS / f).exists() for f in files), str(sorted(p.name for p in SHOTS.glob("*.png"))))

report(0 if all(ok for _, ok, _ in RESULTS) else 1)
