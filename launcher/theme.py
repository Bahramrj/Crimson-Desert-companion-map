"""Colours and the style sheet of the Windows app, for light and dark."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication


ACCENT = {False: "#2563eb", True: "#4c8dff"}       # light, dark


COLORS = {"green": "#22c55e", "amber": "#f59e0b", "red": "#ef4444", "grey": "#6b7280"}


def is_dark():
    """Windows (or Qt) runs in dark mode."""
    hints = QGuiApplication.styleHints()
    if hasattr(hints, "colorScheme"):
        return hints.colorScheme() == Qt.ColorScheme.Dark
    return QGuiApplication.palette().window().color().lightness() < 128


def style_sheet(dark=False):
    """The window's style. Two tones for depth (the window behind, cards in front), one accent colour,
    Windows' own fonts, 4 px spacing steps, rounded cards and controls, a visible keyboard focus.
    Light and dark are separate sets of colours; text colours come from the system palette."""
    c = {"accent": ACCENT[bool(dark)], "accent_hover": "#6ea2ff" if dark else "#1d4ed8",
         "on_accent": "#0b1220" if dark else "#ffffff",
         "accent_soft": "rgba(76, 141, 255, 0.18)" if dark else "rgba(37, 99, 235, 0.10)",
         "window": "#1f1f1f" if dark else "#f3f4f6", "rail": "#191919" if dark else "#e9ebef",
         "card": "#2a2a2a" if dark else "#ffffff", "field": "#333333" if dark else "#ffffff",
         "text": "#f2f2f2" if dark else "#111827", "muted": "#a8adb7" if dark else "#5b6472",
         "ok_bg": "rgba(34, 197, 94, 0.16)" if dark else "#dcfce7", "ok": "#86efac" if dark else "#166534",
         "warn_bg": "rgba(245, 158, 11, 0.16)" if dark else "#fef3c7", "warn": "#fcd34d" if dark else "#92400e",
         "hover": "rgba(255, 255, 255, 0.07)" if dark else "rgba(15, 23, 42, 0.06)",
         "pressed": "rgba(255, 255, 255, 0.12)" if dark else "rgba(15, 23, 42, 0.10)",
         "border": "rgba(255, 255, 255, 0.10)" if dark else "rgba(15, 23, 42, 0.12)",
         "strong": "rgba(255, 255, 255, 0.22)" if dark else "rgba(15, 23, 42, 0.28)"}
    return """
* { font-family: "Segoe UI Variable Text", "Segoe UI"; font-size: 10pt; color: %(text)s; }
#root, #pageBody, QScrollArea#page, QScrollArea#page > QWidget > QWidget { background: %(window)s; }
QToolTip { padding: 5px 8px; border: 1px solid %(border)s; background: %(card)s; color: %(text)s; }

/* navigation rail */
#rail { background: %(rail)s; border-right: 1px solid %(border)s; }
#brand { font-family: "Segoe UI Variable Display", "Segoe UI"; font-size: 14pt; font-weight: 700; padding: 0 12px; }
#brandSub { color: %(muted)s; font-size: 9pt; padding: 0 12px; }
QPushButton#nav { min-height: 40px; border: none; border-radius: 8px; background: transparent; text-align: left; }
QPushButton#nav:hover { background: %(hover)s; }
QPushButton#nav:checked { background: %(accent_soft)s; }
QPushButton#nav:focus { border: 2px solid %(accent)s; }
#navIcon { font-family: "Segoe Fluent Icons", "Segoe MDL2 Assets"; font-size: 12pt; background: transparent; }
#navText { font-weight: 600; background: transparent; }
#navIcon[on="true"], #navText[on="true"] { color: %(accent)s; }

/* pages and cards */
#pageTitle { font-family: "Segoe UI Variable Display", "Segoe UI"; font-size: 20pt; font-weight: 600; }
#panel, #guide, #card { background: %(card)s; border: 1px solid %(border)s; border-radius: 10px; }
#guide { border: 1px solid %(accent)s; }
#panel QLabel, #guide QLabel, #card QLabel, #stat QLabel { background: transparent; }
#panelTitle { font-size: 11pt; font-weight: 600; }
#cardTitle { color: %(muted)s; font-size: 9pt; font-weight: 600; }
#cardValue { font-size: 11pt; font-weight: 600; }
#stat { border: none; border-top: 1px solid %(border)s; border-radius: 0; background: transparent; }
#deviceList { line-height: 150%%; }

#heading { font-size: 13pt; font-weight: 600; }
#bigUrl { font-size: 19pt; font-weight: 700; padding: 6px 0; color: %(accent)s; }
#qr { background: white; border: 1px solid %(border)s; border-radius: 12px; }
QLabel#muted { color: %(muted)s; font-size: 9pt; }
QLabel#ok, #panel QLabel#ok { color: %(ok)s; background: %(ok_bg)s; border-radius: 8px; padding: 8px 12px; font-weight: 600; }
QLabel#warn, #panel QLabel#warn { color: %(warn)s; background: %(warn_bg)s; border-radius: 8px; padding: 8px 12px; }

/* buttons: one filled primary per card, the rest quiet */
QPushButton { padding: 6px 16px; min-height: 22px; border: 1px solid %(strong)s; border-radius: 6px; background: %(field)s; }
QPushButton:hover { background: %(hover)s; }
QPushButton:pressed, QPushButton:checked { background: %(pressed)s; }
QPushButton:focus { border: 2px solid %(accent)s; padding: 5px 15px; }
QPushButton:disabled { color: %(muted)s; border-color: %(border)s; }
QPushButton#primary { background: %(accent)s; color: %(on_accent)s; border: 1px solid %(accent)s; font-weight: 600; }
QPushButton#primary:hover { background: %(accent_hover)s; border-color: %(accent_hover)s; }
QPushButton#primary:focus { border: 2px solid %(text)s; }
QPushButton#primary:disabled { background: %(pressed)s; color: %(muted)s; border-color: %(border)s; }
QPushButton#link { border: none; background: transparent; color: %(accent)s; padding: 6px 4px; }
QPushButton#link:hover { text-decoration: underline; }

/* fields */
QComboBox, QLineEdit { min-height: 22px; padding: 5px 10px; border: 1px solid %(strong)s; border-radius: 6px; background: %(field)s;
    selection-background-color: %(accent)s; }
QComboBox:focus, QLineEdit:focus { border: 2px solid %(accent)s; padding: 4px 9px; }
QSpinBox { min-height: 28px; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox QAbstractItemView { background: %(card)s; border: 1px solid %(border)s; selection-background-color: %(accent_soft)s;
    selection-color: %(text)s; outline: none; }
QCheckBox { spacing: 8px; min-height: 26px; background: transparent; }

/* table, log, progress */
QTableWidget { background: %(card)s; alternate-background-color: %(hover)s; border: 1px solid %(border)s; border-radius: 8px;
    selection-background-color: %(accent_soft)s; selection-color: %(text)s; }
QTableWidget::item { padding: 6px 8px; border: none; }
QHeaderView::section { padding: 8px; border: none; border-bottom: 1px solid %(border)s; background: %(card)s; color: %(muted)s;
    font-size: 9pt; font-weight: 600; }
QPlainTextEdit#log { background: %(field)s; border: 1px solid %(border)s; border-radius: 8px; padding: 6px; }
QProgressBar { border: none; border-radius: 4px; background: %(pressed)s; min-height: 8px; max-height: 8px; }
QProgressBar::chunk { background: %(accent)s; border-radius: 4px; }
QScrollBar:vertical { width: 10px; background: transparent; margin: 2px; }
QScrollBar::handle:vertical { background: %(strong)s; border-radius: 4px; min-height: 28px; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
QDialog { background: %(window)s; }
""" % c


STYLE = style_sheet(False)
