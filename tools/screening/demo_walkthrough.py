"""Silent demo video of the three subtasks, recorded automatically.

    python tools/screening/demo_walkthrough.py [--out demo.mp4] [--ffmpeg PATH] [--keep-frames] [--quick]

Drives the REAL application with readable pauses and on-screen captions. Each frame is composed from the
application's own windows only (main window + dialogs, popups and the caption drawn on top of it), so no other
application or notification can appear in the video and the window may be covered while it records. Frames go to a
temp folder and are encoded to H.264 with ffmpeg. The ~5 minute design wait is recorded at a very low frame rate
and played back fast. Takes about 10 minutes.

ffmpeg is taken from --ffmpeg, $FFMPEG_EXE, the imageio-ffmpeg package or PATH (in that order).
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(tempfile.gettempdir()) / "osdagbridge_screening"
FRAME_WIDTH = 1600


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def find_ffmpeg():
    for cand in (arg("--ffmpeg"), os.environ.get("FFMPEG_EXE")):
        if cand and Path(cand).exists():
            return cand
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return shutil.which("ffmpeg")


def main():
    from collections import deque

    from PySide6.QtCore import QObject, QPoint, Qt, QTimer
    from PySide6.QtGui import QFont, QPainter
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QComboBox, QLabel, QLineEdit, QScrollArea

    import osdagbridge.desktop.__main__ as appmod
    from osdagbridge.core.utils.common import (
        KEY_SPAN, KEY_CARRIAGEWAY_WIDTH, KEY_PROJECT_LOCATION, KEY_TS_DECK_THICKNESS, KEY_TS_GIRDER_SPACING,
        KEY_TS_DECK_OVERHANG, KEY_WL_GUST_FACTOR, KEY_ANALYSIS_MEMBER, KEY_ANALYSIS_LOAD_COMBINATION)
    from osdagbridge.core.bridge_types.plate_girder.defaults import solve_extend_basic_input_dict
    from osdagbridge.core.bridge_types.plate_girder.plategirderbridge import PlateGirderBridge
    from osdagbridge.desktop.ui.template_page import CustomWindow
    from osdagbridge.desktop.ui.utils.custom_widgets import CustomRadioButton
    from osdagbridge.desktop.ui.dialogs.custom_messagebox import CustomMessageBox

    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        sys.exit("ffmpeg not found: pass --ffmpeg PATH or install imageio-ffmpeg")
    out_mp4 = Path(arg("--out", WORK / "demo.mp4"))
    frames_dir = WORK / "demo_frames"
    shutil.rmtree(frames_dir, ignore_errors=True)
    frames_dir.mkdir(parents=True, exist_ok=True)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)

    app = QApplication(sys.argv)
    app.setStyleSheet(appmod.load_stylesheet())
    screen = app.primaryScreen()

    # ── screen recorder (frames + timestamps; the design wait is flagged "fast") ──────────────
    class Recorder(QObject):
        def __init__(self):
            super().__init__()
            self.frames, self.fast = [], False
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.grab)

        def start(self):
            self.timer.start(100)

        def set_fast(self, fast):
            self.fast = fast
            self.timer.setInterval(4000 if fast else 100)

        def grab(self):
            """Render the main window and every visible top-level widget of THIS application on top of it.

            Nothing outside the application (other windows, notifications) can end up in the video, and
            it works while the window is covered by something else.
            """
            main = holder.get("window")
            if main is None:
                return
            canvas = main.grab()
            painter = QPainter(canvas)
            origin = main.mapToGlobal(QPoint(0, 0))

            def z_order(w):
                if w is caption:
                    return 3
                if isinstance(w, CustomMessageBox) or w.metaObject().className() == "QTipLabel":
                    return 2
                return 1
            tops = [w for w in QApplication.topLevelWidgets() if w.isVisible() and w is not main and w.width() > 1]
            for w in sorted(tops, key=z_order):
                painter.drawPixmap(w.mapToGlobal(QPoint(0, 0)) - origin, w.grab())
            painter.end()
            path = frames_dir / f"f{len(self.frames):06d}.jpg"
            canvas.save(str(path), "JPG", 75)      # full size here, ffmpeg scales
            self.frames.append((path, time.time(), self.fast))

    holder = {}
    rec = Recorder()

    # ── caption overlay (a small always-on-top label; it ends up in the screen grabs) ─────────
    caption = QLabel()
    caption.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                           | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput)
    caption.setAttribute(Qt.WA_ShowWithoutActivating)
    caption.setFont(QFont("Segoe UI", 17, QFont.DemiBold))
    caption.setStyleSheet("background: rgba(25,30,40,235); color: white; padding: 10px 26px; border-radius: 8px;")
    caption.setAlignment(Qt.AlignCenter)

    def cap(text):
        caption.setText(text)
        caption.adjustSize()
        geo = screen.availableGeometry()
        caption.move(geo.center().x() - caption.width() // 2, geo.bottom() - caption.height() - 24)
        caption.show()
        caption.raise_()
        QTest.qWait(50)

    def hold(seconds):
        end = time.time() + seconds
        while time.time() < end:
            QTest.qWait(200)

    # ── auto-click the REAL dialogs after a readable pause ────────────────────────────────────
    class AutoDialog(QObject):
        def __init__(self, hold_s=2.8):
            super().__init__()
            self.answers, self.hold_s, self.seen, self.t0 = deque(), hold_s, None, 0.0
            self.timer = QTimer(self)
            self.timer.timeout.connect(self.poll)
            self.timer.start(100)

        def next(self, button):
            self.answers.append(button)

        def poll(self):
            w = QApplication.activeModalWidget()
            if not isinstance(w, CustomMessageBox):
                self.seen = None
                return
            if w is not self.seen:
                self.seen, self.t0 = w, time.time()
            elif time.time() - self.t0 >= self.hold_s:
                answer = self.answers.popleft() if self.answers else next(iter(w.buttonMap))
                self.seen = None
                w.buttonMap[answer].click()

    auto = AutoDialog()

    # ── real window ───────────────────────────────────────────────────────────────────────────
    window = CustomWindow("OsdagBridge", PlateGirderBridge)
    window.showMaximized()
    holder["window"] = window
    hold(1.5)
    rec.start()
    cap("OsdagBridge – FOSSEE screening task: demo")
    hold(2.5)

    dock = window.input_dock.input_widget
    cap("Basic inputs: Span 30 m, Carriageway Width 10.5 m")
    for key, text in ((KEY_SPAN, "30"), (KEY_CARRIAGEWAY_WIDTH, "10.5")):
        field = dock.findChild(QLineEdit, key)
        field.setFocus(); field.selectAll()
        QTest.keyClicks(field, text, delay=150)
        QTest.keyClick(field, Qt.Key_Return)
        hold(0.6)
    window.input_dict[KEY_PROJECT_LOCATION] = {
        "method": "location_name", "data": {"state": "Maharashtra", "district": "Mumbai"},
        "weather_data": {"wind_speed": 44.0, "z_value": 0.16, "zone": "III", "max_temp": 43.0, "min_temp": 5.0},
        "display_text": "Mumbai, Maharashtra", "show_display": False}
    solve_extend_basic_input_dict(window.input_dict)
    window.update_cad_from_inputs()
    hold(2)

    # ════════════════════════ Task II: Additional Inputs dialog ════════════════════════════════
    dlg = window._additional_inputs_dialog
    cap("Task II – Additional Inputs: validation of empty 'Custom' values")
    window._show_additional_inputs()
    hold(2.5)

    mode = dlg.findChild(QComboBox, KEY_WL_GUST_FACTOR + ".mode")
    val = dlg.findChild(QLineEdit, KEY_WL_GUST_FACTOR + ".value")
    cap("Loading > Wind: set 'Gust Factor' to Custom and leave the value empty")
    dlg._reveal_field(mode)
    hold(1.5)
    mode.setCurrentText("Custom"); val.setText("")
    hold(2.5)
    cap("Press Save: blocked, the field is shown and focused")
    auto.next("OK")
    dlg.save_button.click()          # real error dialog stays 2.8 s, then is closed by AutoDialog
    hold(1.5)
    cap("Type a value: Save now succeeds")
    val.setFocus(); val.selectAll()
    QTest.keyClicks(val, "2.5", delay=180)
    QTest.keyClick(val, Qt.Key_Return)
    hold(1.5)
    auto.next("OK")
    dlg.save_button.click()
    hold(1.5)

    cap("Unsaved changes: edit Deck Thickness, then close with the X button")
    thick = dlg.findChild(QLineEdit, KEY_TS_DECK_THICKNESS)
    dlg._reveal_field(thick)
    thick.selectAll()
    QTest.keyClicks(thick, "260", delay=180)
    hold(2)
    auto.next("Cancel")
    dlg.title_bar.btn_close.click()  # warning: Discard / Cancel
    hold(1.5)
    cap("Cancel keeps the dialog and the edit")
    hold(2.5)
    cap("Close again and choose Discard")
    auto.next("Discard")
    dlg.title_bar.btn_close.click()
    hold(2.5)

    # ════════════════════════ Task I: 2D CAD editing ═══════════════════════════════════════════
    cross = window.cad_comp_widget.cross_section_widget
    top = window.cad_comp_widget.top_view_widget

    def label_pos(canvas, key):
        for rect, k in canvas._label_rects:
            if k == key:
                return rect.center().toPoint()
        return None

    def reveal(canvas, pos):
        parent = canvas
        while parent is not None and not isinstance(parent, QScrollArea):
            parent = parent.parentWidget()
        if parent is not None:
            parent.ensureVisible(pos.x(), pos.y(), 160, 60)
            hold(0.3)

    def edit_label(canvas, key, text):
        pos = label_pos(canvas, key)
        reveal(canvas, pos)
        QTest.mouseDClick(canvas, Qt.LeftButton, Qt.NoModifier, pos)
        hold(1.2)
        QTest.keyClicks(canvas._label_editor, text, delay=200)
        hold(0.8)
        QTest.keyClick(canvas._label_editor, Qt.Key_Return)
        hold(3.0)

    cap("Task I – double-click a dimension label on the 2D CAD to edit it")
    hold(2.5)
    cap("Carriageway Width: 10.5 m -> 12 m (layout re-derived)")
    edit_label(cross, KEY_CARRIAGEWAY_WIDTH, "12")
    cap("Girder Spacing: 2.58 m -> 2.2 m (overhang follows)")
    edit_label(cross, KEY_TS_GIRDER_SPACING, "2.2")
    cap("Span Length (top view): 30 m -> 40 m")
    edit_label(top, KEY_SPAN, "40")
    cap("Overhang is derived: double-click does nothing")
    pos = label_pos(cross, KEY_TS_DECK_OVERHANG)
    reveal(cross, pos)
    QTest.mouseDClick(cross, Qt.LeftButton, Qt.NoModifier, pos)
    hold(2.5)
    cap("Invalid value (Carriageway Width = 1 m): error, old value kept")
    pos = label_pos(cross, KEY_CARRIAGEWAY_WIDTH)
    reveal(cross, pos)
    QTest.mouseDClick(cross, Qt.LeftButton, Qt.NoModifier, pos)
    hold(1.2)
    QTest.keyClicks(cross._label_editor, "1", delay=200)
    auto.next("OK")
    QTest.keyClick(cross._label_editor, Qt.Key_Return)
    hold(3.5)
    cap("The CAD, the input dock and the dictionaries stay in sync")
    hold(2.5)

    # ════════════════════════ Task III: transverse-member plots ════════════════════════════════
    def task3():
        cap("Task III – run the design (takes about 5 minutes; sped up here)")
        hold(2.5)
        window.common_design_func("Design")
        rec.set_fast(True)
        t0 = time.time()
        while getattr(window, "_design_running", False) and time.time() - t0 < 900:
            elapsed = int(time.time() - t0)
            cap(f"Design running…  {elapsed // 60}:{elapsed % 60:02d} elapsed (video sped up)")
            hold(2)
        rec.set_fast(False)
        hold(3)
        cap("Design finished: open the Plots view and the Output dock")
        window.output_dock_toggle()
        window.plots_view_toggle()
        hold(2.5)

        pw, od = window.plots_widget, window.output_dock
        member_combo = od.output_widget.findChild(QComboBox, KEY_ANALYSIS_MEMBER)
        lc_combo = od.output_widget.findChild(QComboBox, KEY_ANALYSIS_LOAD_COMBINATION)
        radios = {rb.text(): rb for rb in od.output_widget.findChildren(CustomRadioButton)}
        lcs = [lc_combo.itemText(i) for i in range(lc_combo.count())]
        lc_dead = lcs[0]
        lc_live = next((lc for lc in lcs if "class" in lc.lower()), lcs[1])
        sym = {"Vy": "V<sub>y</sub>", "Mz": "M<sub>z</sub>", "Dy": "D<sub>y</sub>"}
        nice = {"Vy": "shear Vy", "Mz": "bending moment Mz", "Dy": "vertical displacement Dy"}

        def show(member, lc, key, seconds=4.5):
            cap(f"{member} – {nice[key]} – load case '{lc}'")
            widgets = [member_combo, lc_combo] + list(radios.values())
            for w in widgets:
                w.blockSignals(True)
            member_combo.setCurrentText(member); lc_combo.setCurrentText(lc); radios[sym[key]].setChecked(True)
            for w in widgets:
                w.blockSignals(False)
            pw.update_plot()
            hold(seconds)

        cap("The Member dropdown now lists End Diaphragm and Cross Bracing after the girders")
        member_combo.showPopup()
        hold(3)
        member_combo.hidePopup()
        for member in ("End Diaphragm", "Cross Bracing"):
            show(member, lc_dead, "Vy")
            show(member, lc_dead, "Mz")
            show(member, lc_live, "Mz")
            show(member, lc_live, "Dy")
        cap("Thank you")
        hold(3)


    if "--quick" not in sys.argv:       # --quick: skip the 5-minute design (to test the recording)
        task3()
    else:
        cap("(quick mode: design and plots skipped)")
        hold(2)

    rec.timer.stop()
    caption.hide()

    # ── encode ────────────────────────────────────────────────────────────────────────────────
    frames = rec.frames
    lines = []
    for i, (path, t, fast) in enumerate(frames):
        nxt = frames[i + 1][1] if i + 1 < len(frames) else t + 0.1
        dur = 0.1 if fast else min(max(nxt - t, 0.04), 0.5)
        lines += [f"file '{path.as_posix()}'", f"duration {dur:.3f}"]
    lines.append(f"file '{frames[-1][0].as_posix()}'")
    listing = frames_dir / "frames.txt"
    listing.write_text("\n".join(lines), encoding="utf-8")
    (frames_dir / "frames.json").write_text(json.dumps([(str(p), t, f) for p, t, f in frames]))
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(listing),
           "-vf", f"fps=10,scale={FRAME_WIDTH}:-2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
           "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_mp4)]
    print("encoding", len(frames), "frames ->", out_mp4, flush=True)
    subprocess.check_call(cmd)
    if "--keep-frames" not in sys.argv:
        shutil.rmtree(frames_dir, ignore_errors=True)
    print("DEMO DONE", out_mp4, flush=True)
    os._exit(0)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
