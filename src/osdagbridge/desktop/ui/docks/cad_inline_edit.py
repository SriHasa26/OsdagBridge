"""
Double-click-to-edit support for the dimension labels painted on the 2D CAD canvases.

The labels are drawn with QPainter, so they are not widgets. While painting, a canvas
records the bounding rectangle of every labelled dimension (register_label_rect). This
mixin turns a double-click on such a rectangle into a small QLineEdit overlay.

The canvas never touches input_dict: it only emits ``parameter_edited(key, text)``.
CustomWindow validates the text, updates the input dictionaries and redraws.
"""
from PySide6.QtCore import Qt, QLocale, QRect, QRectF, QTimer, Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import QLineEdit, QToolTip

from osdagbridge.core.utils.common import (
    KEY_SPAN, KEY_CARRIAGEWAY_WIDTH, KEY_TS_DECK_THICKNESS, KEY_TS_GIRDER_SPACING,
    KEY_TS_DECK_OVERHANG, KEY_TS_OVERALL_WIDTH, KEY_MP_CB_SPACING,
)

# Dimension label -> (canvas params key, factor from canvas mm to the unit shown, editable).
# Switch a label between editable and derived (read-only) here only.
CAD_LABELS = {
    KEY_CARRIAGEWAY_WIDTH: ("carriageway_width",     1e-3, True),    # m
    KEY_TS_DECK_THICKNESS: ("deck_thickness",        1.0,  True),    # mm
    KEY_SPAN:              ("span_length",           1e-3, True),    # m
    KEY_TS_GIRDER_SPACING: ("girder_spacing",        1e-3, True),    # m
    KEY_TS_DECK_OVERHANG:  ("deck_overhang",         1e-3, False),   # derived
    KEY_TS_OVERALL_WIDTH:  (None,                    1.0,  False),   # derived (drawn width)
    KEY_MP_CB_SPACING:     ("cross_bracing_spacing", 1e-3, False),   # derived: span / (n + 1)
}

DERIVED_TOOLTIP = "Derived value - not editable"
LOCKED_TOOLTIP = "Inputs are locked - unlock to edit"

# The editor shows at most this many decimals; smaller differences count as "unchanged".
_DECIMALS = 3
_UNCHANGED_TOLERANCE = 0.5 * 10 ** -_DECIMALS


class _LabelEditor(QLineEdit):
    """Line edit that reports Enter / focus-out as committed and Esc as cancelled.

    editingFinished is not used: with a validator it is silently skipped for
    intermediate text such as "" or "-", which would leave the box open forever.
    """
    committed = Signal()
    cancelled = Signal()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.committed.emit()
        elif event.key() == Qt.Key_Escape:
            self.cancelled.emit()
        else:
            super().keyPressEvent(event)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.committed.emit()


class InlineEditMixin:
    """Add to a QWidget canvas that has ``self.params`` and ``parameter_edited = Signal(str, str)``."""

    def init_inline_edit(self):
        self.inline_edit_enabled = False   # only the main-window canvases switch this on
        self.inline_edit_guard = None      # optional callable -> bool (False = locked)
        self._label_rects = []             # [(QRectF, KEY_*)] rebuilt on every paintEvent
        self._label_editor = None
        self._label_editor_key = None

    # ── recorded while painting ────────────────────────────────────────────────

    def reset_label_rects(self):
        self._label_rects = []

    def register_label_rect(self, rect, key):
        self._label_rects.append((QRectF(rect), key))

    # ── mouse handling ─────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        self._commit_label_editor()   # a click elsewhere on the canvas ends the edit
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if not self.inline_edit_enabled:
            return super().mouseDoubleClickEvent(event)

        pos = event.position()
        for rect, key in reversed(self._label_rects):
            if not rect.contains(pos):
                continue
            if not CAD_LABELS[key][2]:
                QToolTip.showText(event.globalPosition().toPoint(), DERIVED_TOOLTIP, self)
            elif self.inline_edit_guard is not None and not self.inline_edit_guard():
                QToolTip.showText(event.globalPosition().toPoint(), LOCKED_TOOLTIP, self)
            else:
                self._open_label_editor(key, rect)
            return
        super().mouseDoubleClickEvent(event)

    # ── editor overlay ─────────────────────────────────────────────────────────

    def _open_label_editor(self, key, rect):
        self._close_label_editor()
        param_key, factor, _ = CAD_LABELS[key]
        current = self.params[param_key] * factor

        editor = _LabelEditor(self)
        validator = QDoubleValidator(editor)
        validator.setNotation(QDoubleValidator.StandardNotation)
        validator.setDecimals(_DECIMALS)
        validator.setLocale(QLocale.c())   # always "." as the decimal separator
        editor.setValidator(validator)
        editor.setText(f"{round(current, _DECIMALS):g}")

        width = max(int(rect.width()), 80)
        left = max(0, min(int(rect.left()), self.width() - width))
        editor.setGeometry(QRect(left, int(rect.top()) - 2, width, int(rect.height()) + 4))
        editor.committed.connect(self._commit_label_editor)
        editor.cancelled.connect(self._close_label_editor)

        self._label_editor, self._label_editor_key = editor, key
        editor.show()
        editor.setFocus()
        editor.selectAll()

    def _close_label_editor(self):
        editor, self._label_editor, self._label_editor_key = self._label_editor, None, None
        if editor is not None:
            editor.hide()
            editor.deleteLater()

    def _commit_label_editor(self):
        editor, key = self._label_editor, self._label_editor_key
        if editor is None:
            return
        text = editor.text().strip()
        self._close_label_editor()   # first: the hide() below triggers focus-out again
        if not text:
            return                   # nothing typed: keep the old value

        param_key, factor, _ = CAD_LABELS[key]
        try:
            if abs(float(text) - self.params[param_key] * factor) < _UNCHANGED_TOLERANCE:
                return               # same value as shown (e.g. Enter right after opening)
        except ValueError:
            pass                     # not a number: the owner's validator reports it
        # Emit after this event handler has returned: the owner may open a modal dialog.
        QTimer.singleShot(0, lambda: self.parameter_edited.emit(key, text))
