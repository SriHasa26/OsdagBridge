"""Automated GUI verification for Subtask II (local only, excluded from git).

Run from the repo root with the conda env active:
    python tools/screening/verify_task2.py              # real visible window
    python tools/screening/verify_task2.py --offscreen  # fallback if a visible window fails

Drives the real CustomWindow + AdditionalInputs dialog. The standard CustomMessageBox is
subclassed so that exec() records the dialog, saves a screenshot and returns a scripted
answer instead of blocking.
"""
import os
import sys
import tempfile
import threading
from pathlib import Path

if "--offscreen" in sys.argv:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

ROOT = Path(__file__).resolve().parents[2]
SHOTS = Path(os.environ.get("SCREENING_SHOTS_DIR", tempfile.gettempdir())) / "osdagbridge_screening" / "task2_screenshots"
SHOTS.mkdir(parents=True, exist_ok=True)

RESULTS = []  # (name, ok, detail)


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


# hard 60 s limit for the whole run
threading.Timer(60, lambda: (RESULTS.append(("TIMEOUT (60 s)", False, "run aborted")), report(3))).start()

from PySide6.QtCore import Qt, QSize
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit

import osdagbridge.desktop.__main__ as appmod                       # same setup as `python -m osdagbridge.desktop`
from osdagbridge.core.utils.common import *                          # noqa: F401,F403
from osdagbridge.core.bridge_types.plate_girder.defaults import solve_extend_basic_input_dict
from osdagbridge.core.bridge_types.plate_girder.plategirderbridge import PlateGirderBridge
from osdagbridge.desktop.ui.template_page import CustomWindow
from osdagbridge.desktop.ui.dialogs.custom_messagebox import CustomMessageBox as RealBox, MessageBoxType
import osdagbridge.desktop.ui.dialogs.additional_input.additional_inputs as ai_mod

app = QApplication(sys.argv)
app.setStyleSheet(appmod.load_stylesheet())

CALLS = []
ANSWER = {"value": "OK"}
SHOT_RULES = [  # (predicate on recorded dialog, file name)
    (lambda c: c["text"].startswith("Error: The custom value for 'Gust Factor"), "1_gust_factor_error.png"),
    (lambda c: c["text"].startswith("Error: The custom value for 'Crash Barrier Width"), "2_crash_barrier_error.png"),
    (lambda c: c["text"].startswith("You have unsaved changes"), "3_unsaved_changes_warning.png"),
    (lambda c: c["title"] == "Saved", "4_success_after_fix.png"),
]
SHOT_DONE = set()


class RecordingBox(RealBox):
    """The real standard dialog, but exec() records, screenshots and answers without a modal loop."""

    def __init__(self, title="Message", text="Message", informativeText="", buttons=["OK"],
                 dialogType=MessageBoxType.Information):
        super().__init__(title=title, text=text, informativeText=informativeText,
                         buttons=buttons, dialogType=dialogType)
        self._rec = {"title": title, "text": text, "buttons": list(buttons), "type": dialogType}

    def exec(self):
        CALLS.append(self._rec)
        for pred, fname in SHOT_RULES:
            if fname not in SHOT_DONE and pred(self._rec):
                self.resize(self.sizeHint().expandedTo(QSize(460, 170)))
                self.grab().save(str(SHOTS / fname))
                SHOT_DONE.add(fname)
        self.deleteLater()
        return ANSWER["value"]


ai_mod.CustomMessageBox = RecordingBox


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))


def pump(ms=50):
    QTest.qWait(ms)


def last():
    return CALLS[-1] if CALLS else {"title": "", "text": "", "buttons": [], "type": None}


MSG_UNSAVED = "You have unsaved changes. Closing this window will discard them. Do you want to proceed?"
ERR = "Error: The custom value for '{}' cannot be empty."

# ── real window ──────────────────────────────────────────────────────────────
window = CustomWindow("OsdagBridge", PlateGirderBridge)
window.showMaximized()
pump(800)  # let construction-time QTimer.singleShot(0) refreshes run, as in the real app
check("app window launched", window.isVisible() or os.environ.get("QT_QPA_PLATFORM") == "offscreen")

for key, text in ((KEY_SPAN, "30"), (KEY_CARRIAGEWAY_WIDTH, "10.5")):
    window.input_dock.input_widget.findChild(QLineEdit, key).setText(text)
pump()
check("Span 30 / Carriageway 10.5 reached input_dict",
      str(window.input_dict.get(KEY_SPAN)) == "30" and str(window.input_dict.get(KEY_CARRIAGEWAY_WIDTH)) == "10.5",
      f"{window.input_dict.get(KEY_SPAN)}, {window.input_dict.get(KEY_CARRIAGEWAY_WIDTH)}")
solve_extend_basic_input_dict(window.input_dict)  # what common_design_func does before opening the dialog

dlg = window._additional_inputs_dialog


def open_dialog():
    window._show_additional_inputs()   # exactly what the "Additional Inputs" button path ends with
    pump()


def x_button():
    dlg.title_bar.btn_close.click()
    pump()


def field(cls, key):
    return dlg.findChild(cls, key)


# 1. open/close with no edits, twice
for i in (1, 2):
    CALLS.clear(); open_dialog()
    check(f"open #{i}: dialog visible, not modified", dlg.isVisible() and dlg.is_modified is False)
    x_button()
    check(f"close #{i} without edits: no warning, closed", (not dlg.isVisible()) and not CALLS, f"calls={CALLS}")

# 2/3. edit -> X -> exact warning; Cancel keeps dialog + edit
open_dialog()
thick = field(QLineEdit, KEY_TS_DECK_THICKNESS)
orig = thick.text()
thick.setText("333")
CALLS.clear(); ANSWER["value"] = "Cancel"
x_button()
check("edit + X: warning text exact", len(CALLS) == 1 and last()["text"] == MSG_UNSAVED, last()["text"])
check("warning is Warning type with Discard/Cancel",
      last()["type"] == MessageBoxType.Warning and last()["buttons"] == ["Discard", "Cancel"], str(last()))
check("Cancel keeps dialog open, edit and flag", dlg.isVisible() and thick.text() == "333" and dlg.is_modified)

# 4. Discard closes after exactly one prompt; edit gone on reopen
CALLS.clear(); ANSWER["value"] = "Discard"
x_button()
check("Discard closes after exactly one prompt", (not dlg.isVisible()) and len(CALLS) == 1, f"calls={len(CALLS)}")
open_dialog()
check("edit is gone on reopen, not modified", thick.text() == orig and dlg.is_modified is False, thick.text())

# 5. Esc with an edit -> warning; Esc without -> silent
thick.setText("444")
CALLS.clear(); ANSWER["value"] = "Cancel"
QTest.keyClick(dlg, Qt.Key_Escape); pump()
check("Esc with edit: warning shown, dialog stays", len(CALLS) == 1 and last()["text"] == MSG_UNSAVED and dlg.isVisible())
CALLS.clear(); ANSWER["value"] = "Discard"
QTest.keyClick(dlg, Qt.Key_Escape); pump()
check("Esc + Discard closes after one prompt", (not dlg.isVisible()) and len(CALLS) == 1)
open_dialog(); CALLS.clear()
QTest.keyClick(dlg, Qt.Key_Escape); pump()
check("Esc without edit: silent close", (not dlg.isVisible()) and not CALLS)

# 6. Save then close -> no prompt
open_dialog()
thick.setText("350")
ANSWER["value"] = "OK"; CALLS.clear()
dlg.save_button.click(); pump()
check("Save shows success message", last()["title"] == "Saved", last()["title"])
CALLS.clear(); x_button()
check("Save then close: no prompt", (not dlg.isVisible()) and not CALLS)

# 7. Gust Factor Custom + empty
open_dialog()
mode = field(QComboBox, KEY_WL_GUST_FACTOR + ".mode")
val = field(QLineEdit, KEY_WL_GUST_FACTOR + ".value")
dlg.tabs.setCurrentIndex(0)                      # start somewhere else
mode.setCurrentText("Custom"); val.setText(""); pump()
CALLS.clear(); dlg.save_button.click(); pump()
check("Gust Factor empty: exact error text", last()["text"] == ERR.format("Gust Factor, G"), last()["text"])
check("error uses Critical type, Save blocked (no Saved box)",
      last()["type"] == MessageBoxType.Critical and all(c["title"] != "Saved" for c in CALLS))
check("Loading tab shown, field visible",
      dlg.tabs.tabText(dlg.tabs.currentIndex()).strip() == "Loading" and val.isVisible(),
      dlg.tabs.tabText(dlg.tabs.currentIndex()))
check("field focused", val.hasFocus() or dlg.focusWidget() is val)
val.setText("1.5")
val.editingFinished.emit()   # a real user leaves the box (Enter / clicking Save); mode+value boxes commit on this signal
CALLS.clear(); dlg.save_button.click(); pump()
check("value typed: Save succeeds", last()["title"] == "Saved", last()["text"])
check("saved Custom value reached the shared input_dict",
      # the existing validator may clamp the typed number (e.g. 1.5 -> 2.0); dict must match the box
      float(window.input_dict.get(KEY_WL_GUST_FACTOR + ".value") or "nan") == float(val.text() or "nan"),
      f"dict={window.input_dict.get(KEY_WL_GUST_FACTOR + '.value')} box={val.text()}")

# 8. Crash barrier Custom + Width empty
open_dialog()
cb = field(QComboBox, KEY_CB_TYPE)
cb.setCurrentText("Custom"); pump()
cbw = field(QLineEdit, KEY_CB_WIDTH)
cbw.setText("")
dlg.tabs.setCurrentIndex(dlg.tabs.count() - 1)
CALLS.clear(); dlg.save_button.click(); pump()
check("Crash Barrier Custom, empty Width: error with section prefix",
      last()["text"] == ERR.format("Crash Barrier Width"), last()["text"])
check("Typical Section tab shown for it", dlg.tabs.currentIndex() == 0 and cbw.isVisible())

# 10. failed Save keeps is_modified (dialog still holds the CB edit from above)
check("failed Save keeps is_modified True", dlg.is_modified is True)
CALLS.clear(); ANSWER["value"] = "Discard"; x_button()

# 9. Median tab disabled -> empty Custom there does not block Save
open_dialog()
mt = field(QComboBox, KEY_MD_TYPE)
mw = field(QLineEdit, KEY_MD_WIDTH)
check("Median tab is disabled by the app (Include Median = No)", dlg._in_disabled_tab(mw))
mt.setCurrentText("Custom"); mw.setText("")
ANSWER["value"] = "OK"; CALLS.clear(); dlg.save_button.click(); pump()
check("empty Custom on disabled Median tab does not block Save", last()["title"] == "Saved", last()["text"])
dlg.tabs.setCurrentIndex(0)
pump(200)
dlg.grab().save(str(SHOTS / "5_median_tab_disabled.png"))
SHOT_DONE.add("5_median_tab_disabled.png")

check("all 5 screenshots written",
      all((SHOTS / f).exists() for f in (
          "1_gust_factor_error.png", "2_crash_barrier_error.png", "3_unsaved_changes_warning.png",
          "4_success_after_fix.png", "5_median_tab_disabled.png")),
      str(sorted(p.name for p in SHOTS.glob("*.png"))))

report(0 if all(ok for _, ok, _ in RESULTS) else 1)
