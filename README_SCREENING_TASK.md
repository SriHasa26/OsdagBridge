# OsdagBridge – FOSSEE Winter Internship 2026 screening task

This branch (`submission`) combines the three screening subtasks on top of upstream `dev` (`d74f56d`):

| # | Subtask | Where |
|---|---|---|
| I | Double-click a parameter label on the 2D CAD to edit it | 2D CAD canvases, main window |
| II | Additional Inputs: block Save on an empty "Custom" value; warn before discarding unsaved changes | Additional Inputs dialog |
| III | Plot internal forces / displacements of End Diaphragm and Cross Bracing | Plots view, Output dock |

Each subtask was developed on its own branch (`task1-cad-editing`, `task2-dialog-validation`,
`task3-transverse-plots`) and merged with `--no-ff`; the three merges had no conflicts.

## Setup and run

```bash
conda env create -f environment.yml        # env "osdagbridge-env"
conda activate osdagbridge-env
cd src
python -m osdagbridge.desktop
```

## Subtask I – interactive 2D CAD editing

**Built.** Double-clicking a dimension label on either 2D canvas opens a small number box on it
(prefilled and selected). Enter or clicking elsewhere commits, Esc cancels. The value is validated with the same
validators the input dock / dialog use; a bad value shows the standard Error dialog and the old value stays.
Valid values update `input_dict`, the Input Dock field and the dialog's working copy, re-derive dependent values and
redraw both views.

| Label | View | Editable | Derived on edit |
|---|---|---|---|
| Carriageway Width | cross-section | yes | layout re-solved (girder count kept) |
| Deck Thickness | cross-section | yes | – |
| Span Length | top view | yes | Bracing Spacing = span / (n + 1) |
| Girder Spacing | both | yes | Overhang (girder count kept) |
| Overhang, Overall Bridge Width, Bracing Spacing | – | read-only (tooltip) | – |

**Key files.** `desktop/ui/docks/cad_inline_edit.py` (new: label registry, editor overlay),
`cad_cross_section.py`, `cad_top_view.py` (record label rectangles), `cad_dual_view.py` (`force` redraw),
`template_page.py` (`_on_cad_parameter_edited`), `core/.../plate_girder/defaults.py` (`apply_cad_parameter_edit`).

**Try it.** Enter Span 30 and Carriageway Width 10.5 in the input dock, then double-click "Carriageway Width = 10.50 m"
on the cross-section, type `12`, press Enter: the dock field, both drawings and the derived labels update. Try `1`
(error dialog, old value kept), Esc (cancel) and a double-click on "Overhang" (tooltip, no editor).

## Subtask II – Additional Inputs validation

**Built.** *Save* now checks every enabled tab. For each "Custom" choice whose value box is empty it switches to that
tab, focuses the box and shows the standard Error dialog
`Error: The custom value for '<name>' cannot be empty.` (names come from the schema label, with the tab name added when
a label like "Width" is shared). Covers mode+value fields (wind, seismic, footpath pressure, ...) and the Custom
choice of crash barrier / median / railing / wearing course. `is_modified` is set only by real user edits; closing
with the title-bar X or Esc asks once with the standard Warning dialog (Discard / Cancel).

**Key file.** `desktop/ui/dialogs/additional_input/additional_inputs.py`.

**Try it.** Additional Inputs → Loading → Wind → set *Gust Factor* to Custom, leave the box empty, press Save.
Then change any value and press the window's ✕ or Esc.

## Subtask III – transverse-member plots

**Built.** The Output dock's analysis *Member* dropdown lists, after the girders, **End Diaphragm** and
**Cross Bracing**. Selecting one plots, for the chosen load case, its axial force, shear, torsion, bending moment or
displacements (Dx/Dy/Dz) in the Plots view with the same style as the girder plots. Data comes from one new function,
`results_data.get_transverse_member_results(result_data, loadcase)`, which keeps transverse element tags separate from
the longitudinal (girder) tags: end diaphragm = ospgrillage `start_edge` + `end_edge`, cross bracing = `transverse_slab`
(both only between two girders). Girder plots are unchanged.

**Key files.** `core/.../plate_girder/results_data.py`, `results_data_post_processing.py` (`end_diaphragms`),
`plot_generator.py` (`build_figure_transverse`), `desktop/ui/mpl_plot_widget.py`, `desktop/ui/docks/output_dock.py`,
`core/utils/common.py` (`VALUES_TRANSVERSE_PLOT_MEMBERS`).

**Try it.** Enter Span 30 / Carriageway 10.5 and a project location, press *Design* (takes about 4–5 minutes), open the
Plots view, choose *Cross Bracing* in the Member dropdown, pick a load case and e.g. V<sub>y</sub> or M<sub>z</sub>.

## Verification scripts

`tools/screening/` holds one script per subtask. They drive the real application window (QTest mouse/keyboard events,
the standard dialog is intercepted so nothing blocks), print a PASS/FAIL table and write screenshots to
`$SCREENING_SHOTS_DIR` (default: the system temp folder, under `osdagbridge_screening/`).

```bash
conda activate osdagbridge-env
python tools/screening/verify_task1.py    # CAD inline editing + interaction with Additional Inputs   (~1 min)
python tools/screening/verify_task2.py    # Additional Inputs validation and close guard              (~1 min)
python tools/screening/verify_task3.py    # transverse plots; runs a real design                    (~5-6 min)
# add --offscreen if a visible window cannot be opened
```
Each run is limited by a watchdog (60 s; `verify_task3` waits up to 15 minutes for the design, then 120 s for
the checks). `verify_task3` compares `post_process` with the version from commit `d74f56d` (needs the git history).
Results on this branch: `verify_task1` 62/62, `verify_task2` 28/28, `verify_task3` 40/40 checks pass.

`tools/screening/demo_walkthrough.py` records a silent walkthrough video of the three subtasks. It drives the real window
with on-screen captions, grabs the usable screen at about 10 fps (only while a window of the application is active) and
encodes it with ffmpeg (`--ffmpeg PATH`, `$FFMPEG_EXE`, `imageio-ffmpeg` or `PATH`). It takes about 10 minutes because of the
design run; leave the mouse and keyboard alone while it runs. `--quick` skips the design and the plots.

## Assumptions and design decisions

| # | Question | Decision |
|---|---|---|
| D1 | `KEY_ADD_...` naming | No such family exists; reuse the existing section prefixes (`KEY_TS_`, `KEY_MP_`, ...) |
| D2 | "Basic" vs "additional" dictionary | One shared `input_dict`; CAD edits also update the dialog's working copy and the Input Dock field |
| D3 | Which canvas | Both: carriageway/thickness on the cross-section, span on the top view, girder spacing on both |
| D4 | Derived values | Girder count stays fixed; spacing → overhang; span → bracing spacing; carriageway → full re-solve |
| D5 | Parameter name in the error | Schema label without HTML, colon and unit |
| D6 | Which "Custom" fields | Mode+value pairs and the Custom choice of crash barrier / median / railing / wearing course; disabled widgets and tabs skipped |
| D7 | `is_modified` / close | Only real user edits count; X and Esc share one confirm helper |
| D8 | Routing through `results_data.py` | Only the new transverse plots use it; girder plots untouched |
| D9 | End diaphragm | `start_edge` + `end_edge` members between two girders |
| D10 | Cross bracing | `transverse_slab` members between two girders, minus end diaphragms |
| D11 | Dropdown labels | One `VALUES_` constant, two entries after the girders |
| D12 | Ambiguous names (`Width`) | Section name prefixed when the cleaned label is shared by several fields |
| D13 | CAD editing details | Critical "Input Error" dialog, validators run on a copy, no editing while inputs are locked, forced redraw past the changed-only cache |
| D14 | Transverse plotting | Global-axis forces mapped to member quantities (`TRANSVERSE_FORCE_MAP`); j-end flipped for shears and moments |
| D15 | CAD edit vs. open dialog | The sync is not a dialog edit: it updates `working_input_dict` but never sets `is_modified` |

## Known limitations

- **Dialog re-derives girder spacing (D13).** Opening Additional Inputs re-derives the girder spacing from the girder
  count (the type handlers transiently change the crash-barrier width). This already happens for a spacing saved from
  the dialog itself. A CAD-edited spacing stays correct on the canvas and in `input_dict`, but is replaced by the
  count-derived value if the user opens the dialog and presses Save.
- **Cross-bracing count follows the grillage mesh.** The *Cross Bracing* entry plots the analysis members (one line per
  transverse grid line), not the physical bracing spacing from Additional Inputs (cf. upstream issue #93).
- **Straight-line member diagrams.** Each transverse member is drawn from its two end values only.
- **Axial force and torsion are ~0.** In a flat grillage the axial force and torsion of transverse members vanish, so
  those diagrams are flat.
- **Design time.** A design of the test bridge takes about 4–5 minutes.
- Editing a carriageway width on the CAD re-seeds the additional-input defaults, exactly like typing it in the dock.
- The *Bracing Spacing* label is only drawn by the canvas when at least two bracing lines exist.
