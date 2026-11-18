"""Automated GUI verification for Subtask III: transverse-member plots (local only, excluded from git).

    python tools/screening/verify_task3.py              # real visible window, real design
    python tools/screening/verify_task3.py --offscreen  # fallback

Time limits: 60 s before the design starts, the design wait has its own limit (a design of
the Span 30 / Carriageway 10.5 bridge takes several minutes on this machine), then a hard
120 s for everything that follows. The design runs in worker processes (Windows "spawn"),
so all work lives in main() under the __main__ guard.
"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

if "--offscreen" in sys.argv:
    os.environ["QT_QPA_PLATFORM"] = "offscreen"

ROOT = Path(__file__).resolve().parents[2]
SHOTS = Path(os.environ.get("SCREENING_SHOTS_DIR", tempfile.gettempdir())) / "osdagbridge_screening" / "task3_screenshots"
DESIGN_WAIT = 900          # s, upper bound for the design itself
BASELINE_REF = "d74f56d"   # upstream/dev commit the screening work started from
RESULTS = []
_timer = [None]


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


def arm(seconds, label):
    """(Re)start the hard watchdog."""
    if _timer[0] is not None:
        _timer[0].cancel()
    t = threading.Timer(seconds, lambda: (RESULTS.append((f"TIMEOUT ({seconds} s, {label})", False, "run aborted")), report(3)))
    t.daemon = True
    t.start()
    _timer[0] = t


def check(name, cond, detail=""):
    RESULTS.append((name, bool(cond), detail))


def main():
    arm(60, "before design")
    SHOTS.mkdir(parents=True, exist_ok=True)

    import hashlib
    import numpy as np
    from PySide6.QtCore import QSize
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QComboBox, QLineEdit

    import osdagbridge.desktop.__main__ as appmod
    from osdagbridge.core.utils.common import (
        KEY_SPAN, KEY_CARRIAGEWAY_WIDTH, KEY_PROJECT_LOCATION, KEY_TS_NO_OF_GIRDERS,
        KEY_ANALYSIS_MEMBER, KEY_ANALYSIS_LOAD_COMBINATION, VALUES_TRANSVERSE_PLOT_MEMBERS,
    )
    from osdagbridge.core.bridge_types.plate_girder.plategirderbridge import PlateGirderBridge
    from osdagbridge.core.bridge_types.plate_girder import results_data as rdm
    from osdagbridge.core.bridge_types.plate_girder.plot_generator import (
        build_figure_transverse, build_figure_sfd, FORCE_MAP, DISP_MAP)
    from osdagbridge.desktop.ui.template_page import CustomWindow
    import osdagbridge.desktop.ui.template_page as tp
    import osdagbridge.desktop.ui.mpl_plot_widget as mw
    from osdagbridge.desktop.ui.utils.custom_widgets import CustomRadioButton
    from osdagbridge.desktop.ui.dialogs.custom_messagebox import CustomMessageBox as RealBox

    app = QApplication(sys.argv)
    app.setStyleSheet(appmod.load_stylesheet())
    DIALOGS = []

    class Rec(RealBox):
        def exec(self):
            DIALOGS.append(self.textLabel.text())
            self.deleteLater()
            return "OK"

    tp.CustomMessageBox = Rec

    def pump(ms=60):
        QTest.qWait(ms)

    window = CustomWindow("OsdagBridge", PlateGirderBridge)
    window.showMaximized()
    pump(800)
    pw, od = window.plots_widget, window.output_dock
    member_combo = od.output_widget.findChild(QComboBox, KEY_ANALYSIS_MEMBER)
    lc_combo = od.output_widget.findChild(QComboBox, KEY_ANALYSIS_LOAD_COMBINATION)
    TRANSVERSE = rdm.TRANSVERSE_LABEL_TO_TYPE

    # ── A. before any design ─────────────────────────────────────────────────
    check("before design: dropdown has no transverse entries yet",
          [member_combo.itemText(i) for i in range(member_combo.count())] == ["All"])
    try:
        pw.update_plot()
        ok = True
    except Exception as exc:                      # noqa: BLE001
        ok = False
    check("plot before design: update_plot is a graceful no-op", ok)
    check("results_data fn on None / {} / unknown input returns empty, no crash",
          not rdm.get_transverse_member_results(None, "x")[rdm.TRANSVERSE_END_DIAPHRAGM]
          and not rdm.get_transverse_member_results({}, "x")[rdm.TRANSVERSE_CROSS_BRACING])
    fig, summ = build_figure_transverse({}, rdm.TRANSVERSE_END_DIAPHRAGM, "Fy", {}, {})
    check("builder with no data returns a message figure", fig.axes and not summ)

    # ── B. real design: Span 30 / Carriageway 10.5 ───────────────────────────
    for key, text in ((KEY_SPAN, "30"), (KEY_CARRIAGEWAY_WIDTH, "10.5")):
        window.input_dock.input_widget.findChild(QLineEdit, key).setText(text)
    pump(300)
    window.input_dict[KEY_PROJECT_LOCATION] = {
        "method": "location_name", "data": {"state": "Maharashtra", "district": "Mumbai"},
        "weather_data": {"wind_speed": 44.0, "z_value": 0.16, "zone": "III", "max_temp": 43.0, "min_temp": 5.0},
        "display_text": "Mumbai, Maharashtra", "show_display": False}
    arm(DESIGN_WAIT + 60, "design")
    t0 = time.time()
    window.common_design_func("Design")
    while getattr(window, "_design_running", False) and time.time() - t0 < DESIGN_WAIT:
        QTest.qWait(300)
    design_s = time.time() - t0
    finished = not getattr(window, "_design_running", True)
    check(f"design finished ({design_s:.0f} s)", finished and bool(window.backend.result_data), f"dialogs={DIALOGS[-1:]}")
    if not finished or not window.backend.result_data:
        report(1)
    arm(120, "checks after design")
    pump(2500)       # _on_design_done: dropdowns, plots_widget.setup/link
    rd = window.backend.result_data
    n_girders = int(window.input_dict[KEY_TS_NO_OF_GIRDERS])

    # ── C. dropdown ──────────────────────────────────────────────────────────
    items = [member_combo.itemText(i) for i in range(member_combo.count())]
    expected = ["All"] + [f"G{i}" for i in range(1, n_girders + 1)] + VALUES_TRANSVERSE_PLOT_MEMBERS
    check("dropdown: All, girders, then End Diaphragm and Cross Bracing", items == expected, str(items))
    check("exactly two transverse entries (no diagonals/chords)",
          [i for i in items if i not in ("All",) and not i.startswith("G")] == ["End Diaphragm", "Cross Bracing"])

    # ── D. data: separation + origin ─────────────────────────────────────────
    lcs = [lc_combo.itemText(i) for i in range(lc_combo.count())]
    real = [lc for lc in lcs if lc and not lc.startswith("Envelope")]
    picks = []
    for cand in (real[0], next((l for l in real if "class" in l.lower()), real[1]), real[-1]):   # dead, live, combination
        if cand not in picks:
            picks.append(cand)
    check(f"load cases under test: {picks}", len(picks) >= 2)

    calls = []
    orig = mw.get_transverse_member_results

    def spy(data, lc):
        res = orig(data, lc)
        calls.append((lc, res))
        return res
    mw.get_transverse_member_results = spy

    members_xyz = rd["nodes"]
    for lc in picks:
        res = orig(rd, lc)
        lon = set(res[rdm.LONGITUDINAL_TAGS])
        ed, cb = set(res[rdm.TRANSVERSE_END_DIAPHRAGM]), set(res[rdm.TRANSVERSE_CROSS_BRACING])
        check(f"[{lc}] end diaphragm and cross bracing data present", bool(ed) and bool(cb), f"ED={len(ed)} CB={len(cb)}")
        check(f"[{lc}] transverse tags do not overlap girder tags (or each other)",
              not (lon & ed) and not (lon & cb) and not (ed & cb))

        def z_span(tag):
            ni, nj = rd["members"][str(tag)]
            return abs(members_xyz[str(ni)][2] - members_xyz[str(nj)][2])
        check(f"[{lc}] transverse elements run across the width, girder elements along it",
              all(z_span(t) > 1e-6 for t in ed | cb) and all(z_span(t) < 1e-3 for t in lon))

    # ── E. widget path: render each entry for each load case ─────────────────
    radios = {rb.text(): rb for rb in od.output_widget.findChildren(CustomRadioButton)}
    labels = {"Fy": "V<sub>y</sub>", "Mz": "M<sub>z</sub>", "Dy": "D<sub>y</sub>"}

    def select(member, lc, force_key):
        widgets = [member_combo, lc_combo] + list(radios.values())
        for w in widgets:
            w.blockSignals(True)
        member_combo.setCurrentText(member)
        lc_combo.setCurrentText(lc)
        radios[labels[force_key]].setChecked(True)
        for w in widgets:
            w.blockSignals(False)
        pw.update_plot()
        pump(40)

    def fig_signature(fig):
        parts = []
        for line in fig.axes[0].lines:
            parts.append(np.round(np.concatenate([np.asarray(a, dtype=float).ravel() for a in line.get_data_3d()]), 6))
        return hashlib.md5(np.concatenate(parts).tobytes()).hexdigest() if parts else ""

    # girder plot before visiting the transverse entries
    select("All", picks[0], "Fy")
    girder_sig_before = fig_signature(pw._fig)
    check("girder plot (All, Vy) renders", bool(girder_sig_before) and bool(pw._summary_data))

    shots = {}
    for entry in VALUES_TRANSVERSE_PLOT_MEMBERS:
        mtype = TRANSVERSE[entry]
        for lc in picks:
            for key in (("Fy", "Mz", "Dy") if lc == picks[0] else ("Fy",)):
                calls.clear()
                select(entry, lc, key)
                fig = pw._fig
                data_ok = bool(calls) and calls[-1][0] == lc and bool(calls[-1][1][mtype])
                n_lines = len(fig.axes[0].lines) if fig.axes else 0
                summ_ok = list(pw._summary_data) == [entry]
                check(f"[{entry} | {lc} | {key}] data via results_data fn, plot has lines + summary",
                      data_ok and n_lines > 0 and summ_ok, f"calls={len(calls)} lines={n_lines} summary={list(pw._summary_data)}")
                if lc == picks[0]:
                    shots[(entry, key)] = window.grab()

    # ── F. all force/displacement components render with data (direct builder, first load case) ──
    res0 = orig(rd, picks[0])
    nodes, members = window.backend.get_nodes_members()
    bad = []
    for mtype in (rdm.TRANSVERSE_END_DIAPHRAGM, rdm.TRANSVERSE_CROSS_BRACING):
        for key in list(FORCE_MAP) + list(DISP_MAP):
            fig, summ = build_figure_transverse(res0, mtype, key, nodes, members, edge_dist=window.backend.get_edge_dist())
            if not (fig.axes and fig.axes[0].lines and summ):
                bad.append((mtype, key))
    check("all 6 forces + 3 displacements render with data for both types", not bad, str(bad))

    # ── G. girder plots unchanged ────────────────────────────────────────────
    select("All", picks[0], "Fy")
    check("girder plot data identical before and after visiting the transverse entries",
          fig_signature(pw._fig) == girder_sig_before)
    ds = window.backend.get_results_dataset()
    direct, _ = build_figure_sfd(ds.sel(Loadcase=picks[0]), "Fy", nodes, members, edge_dist=window.backend.get_edge_dist(),
                                 eng_scale=pw._eng_scale, selected_girder="All")
    check("girder plot via the widget equals build_figure_sfd called directly", fig_signature(direct) == girder_sig_before)
    # Run the baseline post_process (git BASELINE_REF) and the current one on identical raw data:
    # every pre-existing key and its value must be unchanged; "end_diaphragms" is the only addition.
    import subprocess
    import types
    gm = window.backend.grillage_model
    src = subprocess.check_output(
        ["git", "show", f"{BASELINE_REF}:src/osdagbridge/core/bridge_types/plate_girder/results_data_post_processing.py"],
        cwd=str(ROOT), text=True)
    old_pp = types.ModuleType("old_post_processing")
    exec(compile(src, "old_post_processing", "exec"), old_pp.__dict__)

    def raw():
        return rdm._build_full_data(gm.model, gm.edge_dist or 0.0,
                                    dataset=getattr(gm, "_deduplicated_results", None), lazy=True)
    new_out, old_out = rdm.post_process(raw()), old_pp.post_process(raw())
    check("post_process: key set = baseline keys + end_diaphragms only",
          set(new_out) - set(old_out) == {"end_diaphragms"} and set(old_out) <= set(new_out),
          f"added={set(new_out) - set(old_out)} removed={set(old_out) - set(new_out)}")
    def same(k):
        a, b = new_out[k], old_out[k]
        # these two lists are built from sets (list(FORCE_KEEP)): only their content is meaningful
        return sorted(a) == sorted(b) if k in ("force_components", "disp_components") else a == b
    changed = [k for k in old_out if k not in ("forces", "displacements") and not same(k)]
    check("post_process: values of all baseline keys identical (nodes, members, girders, crossbracings, ...)",
          not changed, str(changed))
    check("post_process: forces and displacements identical for the load cases under test",
          all(new_out["forces"][lc] == old_out["forces"][lc] and new_out["displacements"][lc] == old_out["displacements"][lc]
              for lc in picks))

    # ── H. edge cases ────────────────────────────────────────────────────────
    none_res = orig(rd, "No Such Load Case")
    check("load case without results: empty members, no crash",
          not none_res[rdm.TRANSVERSE_END_DIAPHRAGM] and not none_res[rdm.TRANSVERSE_CROSS_BRACING])
    fig, summ = build_figure_transverse(none_res, rdm.TRANSVERSE_CROSS_BRACING, "Fy", nodes, members)
    check("…and the plot shows a message instead", not summ and any("No Cross Bracing" in t.get_text() for t in fig.axes[0].texts))
    x0 = rd["crossbracings"][0]["start"]["coords"][0]
    one_line = dict(rd, crossbracings=[c for c in rd["crossbracings"] if abs(c["start"]["coords"][0] - x0) < 1e-6])
    r1 = orig(one_line, picks[0])
    fig, summ = build_figure_transverse(r1, rdm.TRANSVERSE_CROSS_BRACING, "Fy", nodes, members)
    check(f"single bracing line ({len(r1[rdm.TRANSVERSE_CROSS_BRACING])} members) plots", bool(summ) and len(fig.axes[0].lines) > 0)
    one_member = dict(rd, crossbracings=rd["crossbracings"][:1])
    r2 = orig(one_member, picks[0])
    fig, summ = build_figure_transverse(r2, rdm.TRANSVERSE_CROSS_BRACING, "Mz", nodes, members)
    check("single bracing member plots", len(r2[rdm.TRANSVERSE_CROSS_BRACING]) == 1 and bool(summ))

    for env in [lc for lc in lcs if lc.startswith("Envelope")][:1]:
        try:
            select("Cross Bracing", env, "Fy"); ok = bool(pw._fig.axes)
        except Exception as exc:                  # noqa: BLE001
            ok = False
        check(f"envelope load case '{env}': plot (data or message), no crash", ok)

    # ── I. physical sanity of the component mapping ──────────────────────────
    res = orig(rd, picks[0])
    cbm = res[rdm.TRANSVERSE_CROSS_BRACING]
    sums = {c: sum(abs(m["forces"].get(c, 0.0)) for m in cbm.values()) for c in ("Vx_i", "Vy_i", "Vz_i", "Mx_i", "My_i", "Mz_i")}
    print("MAPPING-INFO cross-bracing sum|comp| (N):", {k: round(v) for k, v in sums.items()})

    # ── J. screenshots ───────────────────────────────────────────────────────
    window.output_dock_toggle()
    window.plots_view_toggle()
    pump(500)
    select("End Diaphragm", picks[0], "Fy"); pump(400)
    window.grab().save(str(SHOTS / "2a_end_diaphragm_shear.png"))
    select("End Diaphragm", picks[0], "Mz"); pump(400)
    window.grab().save(str(SHOTS / "2b_end_diaphragm_bending.png"))
    select("Cross Bracing", picks[0], "Fy"); pump(400)
    window.grab().save(str(SHOTS / "3a_cross_bracing_shear.png"))
    select("Cross Bracing", picks[0], "Mz"); pump(400)
    window.grab().save(str(SHOTS / "3b_cross_bracing_bending.png"))
    select("Cross Bracing", picks[0], "Dy"); pump(400)
    window.grab().save(str(SHOTS / "4_cross_bracing_displacement.png"))
    member_combo.showPopup(); pump(400)
    member_combo.view().window().grab().save(str(SHOTS / "1_dropdown_entries.png"))
    member_combo.hidePopup()
    names = ("1_dropdown_entries", "2a_end_diaphragm_shear", "2b_end_diaphragm_bending",
             "3a_cross_bracing_shear", "3b_cross_bracing_bending", "4_cross_bracing_displacement")
    check("6 screenshots written", all((SHOTS / f"{n}.png").exists() for n in names))

    report(0 if all(ok for _, ok, _ in RESULTS) else 1)


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    try:
        main()
    except Exception as exc:                      # noqa: BLE001 - still print the table
        import traceback
        traceback.print_exc()
        RESULTS.append(("script error", False, repr(exc)[:200]))
        report(2)
