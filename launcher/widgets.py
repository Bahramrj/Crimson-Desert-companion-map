"""Small parts of the Windows app's window: status tiles, the rail's buttons, cards, the import dialog."""

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QVBoxLayout,
)
from launcher.theme import COLORS
from server.app import WEB_DIR


RESTART_FIELDS = ("port", "rate_hz", "https", "https_port", "mdns")


REALM_LABEL = {"pywel": "Pywel", "abyss": "Abyss"}


IMAGE_FILTER = "Images (*.png *.jpg *.jpeg *.webp *.tif *.tiff *.bmp)"


MARKER_FILTER = "Marker files (*.csv *.geojson *.json)"


class ImportCancelled(Exception):
    """Raised inside an import's progress callback when the user pressed Cancel."""


def time_left(seconds):
    return f"about {max(5, round(seconds / 5) * 5):.0f} s left" if seconds < 90 else f"about {round(seconds / 60):.0f} min left"


def app_icon():
    path = WEB_DIR / "dist" / "icon-512.png"
    return QIcon(str(path)) if path.exists() else QIcon()


class StatusCard(QFrame):
    """A small tile: what it is, and its current value with a coloured dot."""

    def __init__(self, title):
        super().__init__()
        self.setObjectName("card")
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        self.value = QLabel("–")
        self.value.setObjectName("cardValue")
        self.value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.value.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(2)
        layout.addWidget(self.title)
        layout.addWidget(self.value)

    def set(self, text, color=None):
        dot = f'<span style="color:{COLORS[color]}">●</span> ' if color else ""
        self.value.setText(f"{dot}{text}")
        self.setAccessibleName(f"{self.title.text()}: {text}")


class NavButton(QPushButton):
    """An entry of the navigation rail: an icon from Windows' own icon font and a label."""

    def __init__(self, glyph, label):
        super().__init__()
        self.setObjectName("nav")
        self.setCheckable(True)
        self.setAutoExclusive(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(label)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 0, 12, 0)
        row.setSpacing(12)
        icon = QLabel(glyph)
        icon.setObjectName("navIcon")
        text = QLabel(label)
        text.setObjectName("navText")
        self.setFixedHeight(40)
        self._parts = (icon, text)
        for part in self._parts:
            part.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(icon)
        row.addWidget(text, 1)
        self.toggled.connect(self._tint)

    def _tint(self, on):
        """A style sheet cannot colour a child by its parent's state: the labels carry the state themselves."""
        for part in self._parts:
            part.setProperty("on", on)
            part.style().unpolish(part)
            part.style().polish(part)


def panel(title=None, hint=None):
    """A card on a page: (frame, its layout). `title` heads it, `hint` is a muted line under the title."""
    frame = QFrame()
    frame.setObjectName("panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 16, 18, 16)
    layout.setSpacing(10)
    if title:
        head = QLabel(title)
        head.setObjectName("panelTitle")
        layout.addWidget(head)
    if hint:
        note = QLabel(hint)
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
    return frame, layout


class _ImportSignals(QObject):
    progress = Signal(int, int)
    finished = Signal(object, str)


class ImportDialog(QDialog):
    """Name, realm, source and licence note for an imported image (every map records its source)."""

    def __init__(self, parent, path, title="Import map image"):
        super().__init__(parent)
        self.setWindowTitle(title)
        form = QFormLayout(self)
        form.addRow("File", QLabel(path))
        self.name = QLineEdit(placeholderText="e.g. Pywel full map", maxLength=60)
        self.realm = QComboBox()
        for key, label in REALM_LABEL.items():
            self.realm.addItem(label, key)
        self.source = QComboBox()
        self.source.addItem("Own screenshot / capture", "C")
        self.source.addItem("Downloaded (needs a licence note)", "B")
        self.licence = QLineEdit(placeholderText="where it came from and what its licence allows", maxLength=300)
        form.addRow("Name", self.name)
        form.addRow("Realm", self.realm)
        form.addRow("Source", self.source)
        form.addRow("Licence note", self.licence)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _accept(self):
        if self.source.currentData() == "B" and not self.licence.text().strip():
            QMessageBox.warning(self, "Import map image", "Downloaded maps need a licence note.")
            return
        self.accept()

    def values(self):
        return {"realm": self.realm.currentData(), "name": self.name.text().strip(),
                "source": self.source.currentData(), "licence": self.licence.text().strip()}
