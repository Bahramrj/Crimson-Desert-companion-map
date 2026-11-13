"""The Maps page: import from the game files (with time left and Cancel), images and marker files, the map list."""

import logging
import dataclasses
import threading
import time

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QProgressBar, QPushButton, QTableWidget, QTableWidgetItem,
)
from gamedata import Archive, ArchiveError, find_install, markers, resolve_install, worldmap
from gamedata.strings import LANGUAGES
from launcher.widgets import (
    IMAGE_FILTER, ImportCancelled, ImportDialog, MARKER_FILTER, REALM_LABEL, _ImportSignals, panel, time_left,
)
from mapstore import MapError, NotFound, SOURCES
from mapstore.marker_import import read_marker_file
from mapstore.store import summary
from pathlib import Path

log = logging.getLogger("cdlivemap.launcher")


class MapsPage:
    """Part of MainWindow (launcher/window.py): its methods use the window's own state."""

    def _maps_tab(self):
        tab, layout = self._page("Maps", "Maps and markers are kept on this PC only.")

        game, box = panel("From your game files", "The exact map of the game, its markers and icons. Run it again after a game update.")
        self.m_game = QLabel()
        self.m_game.setWordWrap(True)
        box.addWidget(self.m_game)
        options = QHBoxLayout()
        options.setSpacing(10)
        self.m_lang = QComboBox()
        for code, name in LANGUAGES.items():
            self.m_lang.addItem(name, code)
        self.m_lang.setCurrentIndex(max(0, self.m_lang.findData(self.config.game_lang)))
        self.m_lang.setToolTip("Language of the names the game gives to places and resources. "
                               "Import again after changing it; categories and shop labels stay English.")
        self.m_lang.setAccessibleName("Language of the game's names")
        self.m_lang.currentIndexChanged.connect(lambda _: self._save_quality())
        self.m_quality = QComboBox()
        self.m_quality.addItem("Default quality (25 600 px)", "default")
        self.m_quality.addItem("High resolution (Pywel 51 200 px, ~2.5x disk)", "high")
        self.m_quality.setCurrentIndex(max(0, self.m_quality.findData(self.config.map_quality)))
        self.m_quality.setToolTip("High resolution keeps roads and coasts sharp when zoomed in close. "
                                  "Re-import to switch; the previous game map is replaced.")
        self.m_quality.setAccessibleName("Map quality")
        self.m_quality.currentIndexChanged.connect(lambda _: self._save_quality())
        self.m_game_dir = QPushButton("Game folder…", clicked=lambda: self.choose_game_dir())
        self.m_game_dir.setToolTip("Pick the Crimson Desert folder if it is not in a Steam library this PC knows about.")
        self.m_game_auto = QPushButton("Find via Steam", clicked=lambda: self.set_game_dir(""))
        self.m_game_auto.setToolTip("Forget the chosen folder and look for the game in the Steam libraries again.")
        self.m_game_import = QPushButton("Import from game files", clicked=lambda: self.import_game())
        self.m_game_import.setObjectName("primary")
        for combo in (self.m_lang, self.m_quality):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(16)
        self.m_game_dir.setObjectName("link")
        self.m_game_auto.setObjectName("link")
        options.addWidget(self.m_game_import)
        options.addWidget(self.m_lang)
        options.addWidget(self.m_quality, 1)
        box.addLayout(options)
        folder = QHBoxLayout()
        folder.addWidget(self.m_game_dir)
        folder.addWidget(self.m_game_auto)
        folder.addStretch()
        box.addLayout(folder)
        # an import in progress: how far, how long still, and a way out
        progress = QHBoxLayout()
        self.m_progress = QProgressBar(visible=False)
        self.m_progress.setTextVisible(False)
        self.m_eta = QLabel(visible=False)
        self.m_eta.setObjectName("muted")
        self.m_cancel = QPushButton("Cancel", visible=False, clicked=lambda: self.cancel_import())
        progress.addWidget(self.m_progress, 1)
        progress.addWidget(self.m_eta)
        progress.addWidget(self.m_cancel)
        box.addLayout(progress)
        layout.addWidget(game)

        maps, box = panel("Maps on this PC", "Your own image works too: import it, then calibrate it on the device (Settings → Map).")
        self.m_table = QTableWidget(0, 6)
        self.m_table.setHorizontalHeaderLabels(["Name", "Realm", "Source", "Size", "Placement", "Shown"])
        self.m_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.m_table.verticalHeader().setVisible(False)
        self.m_table.setShowGrid(False)
        self.m_table.setAlternatingRowColors(True)
        self.m_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.m_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.m_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.m_table.setMinimumHeight(170)
        self.m_table.setAccessibleName("Maps on this PC")
        box.addWidget(self.m_table, 1)
        row = QHBoxLayout()
        self.m_import = QPushButton("Import image…", clicked=self.choose_import)
        row.addWidget(self.m_import)
        row.addWidget(QPushButton("Import markers…", clicked=self.choose_marker_import))
        row.addStretch()
        row.addWidget(QPushButton("Show this map", clicked=self.activate_selected_map))
        row.addWidget(QPushButton("Delete", clicked=lambda: self.delete_selected_map()))
        box.addLayout(row)
        folder = QPushButton("Open the maps folder", clicked=lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.backend.maps.root))))
        folder.setObjectName("link")
        box.addWidget(folder, 0, Qt.AlignmentFlag.AlignLeft)
        self.m_note = QLabel()
        self.m_note.setWordWrap(True)
        box.addWidget(self.m_note)
        layout.addWidget(maps, 1)
        return tab

    def refresh_maps(self):
        if self.tabs.currentWidget() is not self.maps_tab:
            return
        maps, active = self.backend.maps.list(), self.backend.maps.active()
        text, can_import = self._game_status(maps)
        self.m_game.setText(text)
        self.m_game_auto.setVisible(bool(self.config.game_dir))
        if not (self._import and self._import.is_alive()):
            self.m_game_import.setEnabled(can_import)
        self.m_table.setRowCount(len(maps))
        for row, m in enumerate(maps):
            if m.get("fixed"):
                placement = "exact (game data)"
            elif len(m["calibration"]) >= 2:
                placement = f"{len(m['calibration'])} points · error {summary(m)['errorM']:.1f} m"
            else:
                placement = f"not calibrated ({len(m['calibration'])} of 2+ points)"
            cells = (m["name"], REALM_LABEL[m["realm"]], SOURCES[m['source']].capitalize(),
                     f"{m['image'][0]} × {m['image'][1]}", placement, "yes" if active.get(m["realm"]) == m["id"] else "")
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, m["id"])
                if m["licence"]:
                    item.setToolTip(f"Source / licence note: {m['licence']}")
                self.m_table.setItem(row, col, item)
        if not maps:
            self.m_note.setText("No map imported yet: devices show a coordinate grid with the live arrow.")

    def _selected_map(self):
        row = self.m_table.currentRow()
        item = self.m_table.item(row, 0) if row >= 0 else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def choose_import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import map image", "", IMAGE_FILTER)
        if not path:
            return
        dialog = ImportDialog(self, path)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.import_map(path, **dialog.values())

    def import_map(self, path, realm, name="", source="C", licence="", wait=False):
        """Tile an image on a worker thread; the table refreshes when it is done."""
        self._import_game = False
        return self._start_import(f"Importing {path} …", lambda progress: [self.backend.maps.import_image(
            path, realm, name=name or None, source=source, licence=licence, progress=progress)], wait)

    def _save_quality(self):
        self.config = dataclasses.replace(self.config, map_quality=self.m_quality.currentData(), game_lang=self.m_lang.currentData())
        self.config.save(self.config_path)

    def import_game(self, wait=False):
        """Render Pywel and the Abyss from the game's own map layers (read-only), replacing the last game import."""
        game = self._game_dir()
        if game is None:
            self.m_note.setText("Crimson Desert install not found.")
            return None

        quality = self.m_quality.currentData()
        lang = self.m_lang.currentData()

        def job(progress):
            archive = Archive(game)
            sets, failures = markers.import_markers(archive, self.backend.markers, lang)
            for f in failures:
                log.warning("Marker import: %s", f)
            log.info("Imported marker sets: %s", ", ".join(f"{s['id']} ({s['count']})" for s in sets))
            self.backend.notify_markers()
            results = []
            for i, realm in enumerate(("pywel", "abyss")):
                summary, failures = worldmap.import_basemap(
                    archive, self.backend.maps, realm, worldmap.scale_for(quality, realm),
                    progress=lambda d, t, i=i: progress(i * 1000 + 1000 * d // t, 2000))
                if failures:
                    log.warning("%s: %d map tiles could not be read", realm, len(failures))
                results.append(summary)
            return results
        self._import_game = True
        return self._start_import("Rendering the world map from your game files (about a minute) …", job, wait)

    def _start_import(self, note, job, wait):
        if self._import and self._import.is_alive():
            self.m_note.setText("An import is already running.")
            return None
        signals = _ImportSignals(self)
        signals.progress.connect(self._import_progress)
        signals.finished.connect(self._import_finished)
        self.m_progress.setValue(0)
        self.m_progress.setVisible(True)
        self.m_eta.setText("")
        self.m_eta.setVisible(True)
        self.m_cancel.setText("Cancel")
        self.m_cancel.setEnabled(True)
        self.m_cancel.setVisible(True)
        self.m_import.setEnabled(False)
        self.m_game_import.setEnabled(False)
        self.m_note.setText(note)
        self._import_started = time.monotonic()
        cancel = self._cancel = threading.Event()

        def progress(done, total):               # called from the import's threads
            if cancel.is_set():
                raise ImportCancelled()
            signals.progress.emit(done, total)

        def work():
            try:
                signals.finished.emit(job(progress), "")
            except ImportCancelled:
                log.info("Map import cancelled")
                signals.finished.emit([], "cancelled")
            except Exception as e:   # MapError, ArchiveError, OSError, and whatever Pillow raises for a bad image
                log.warning("Map import failed: %s", e)
                signals.finished.emit([], str(e) or type(e).__name__)

        self._import = threading.Thread(target=work, name="map-import", daemon=True)
        self._import.start()
        if wait:
            self._import.join()
            QGuiApplication.processEvents()
        return self._import

    def cancel_import(self):
        """Stop the running import at its next tile; what it had written so far is removed."""
        if self._import and self._import.is_alive():
            self._cancel.set()
            self.m_cancel.setEnabled(False)
            self.m_cancel.setText("Cancelling …")

    def _import_progress(self, done, total):
        self.m_progress.setMaximum(total)
        self.m_progress.setValue(done)
        elapsed = time.monotonic() - self._import_started
        if done and elapsed > 2 and not self._cancel.is_set():       # an estimate from the pace so far
            self.m_eta.setText(time_left(elapsed * (total - done) / done) if done < total else "finishing …")

    def _import_finished(self, results, error):
        self.m_progress.setVisible(False)
        self.m_eta.setVisible(False)
        self.m_cancel.setVisible(False)
        self.refresh_sync()
        self._refresh_guide()
        self.m_import.setEnabled(True)
        self.m_game_import.setEnabled(self._game_dir() is not None)
        if error == "cancelled":
            self.m_note.setText("Import cancelled. The maps are unchanged"
                                + (" (the markers were already updated)." if self._import_game else "."))
            return
        if error:
            self.m_note.setText(f"Import failed: {error}")
            self._notify(f"The import failed: {error}")
            return
        self._notify("The map is ready on your devices.")
        for result in results:
            log.info("Imported map %s (%dx%d)", result["id"], *result["image"])
            self.backend.notify_maps(result["id"], "imported")
        if len(results) == 1 and not results[0]["fixed"]:
            r = results[0]
            self.m_note.setText(f"Imported “{r['name']}”, now shown for {REALM_LABEL[r['realm']]}. "
                                "Calibrate it on your device: Settings → Map → Add point.")
        else:
            self.m_note.setText("Imported " + ", ".join(f"“{r['name']}”" for r in results)
                                + ": placed exactly from the game data, no calibration needed.")
        self.refresh_maps()

    def _game_dir(self):
        if self._game is None:
            self._game = (find_install(self.config.game_dir or None),)
        return self._game[0]

    def choose_game_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Crimson Desert folder", self.config.game_dir or "")
        if not path:
            return False
        game = resolve_install(path)
        if game is None:
            QMessageBox.warning(self, "Game folder", f"{path} is not a Crimson Desert install.\n\n"
                                "Pick the folder that holds the game's numbered data folders and “meta”, "
                                "for example …\\steamapps\\common\\Crimson Desert.")
            return False
        return self.set_game_dir(str(game))

    def set_game_dir(self, path):
        """Use this install folder for imports ("" = find it via Steam); saved in config.json."""
        self.config = dataclasses.replace(self.config, game_dir=path)
        self.config.save(self.config_path)
        self._game = None
        log.info("Game folder: %s", path or "find via Steam")
        self.refresh_maps()
        self.refresh_sync()
        return True

    def sync_status(self):
        """(text, kind) for the main page: the game's version against the map files made from it.
        kind "ok" (green) when they match, "warn" with an update link when not; None without an install."""
        if self._import and self._import.is_alive():
            return "Updating map files from the game …", "muted"
        game = self._game_dir()
        if game is None:
            return None
        try:
            version = Archive(game).version()
        except (ArchiveError, OSError):
            return None
        made = sorted({m.get("gameVersion") or "?" for m in self.backend.maps.list() if m["source"] == "A" and m.get("fixed")})
        link = '<a href="update">Update map files</a>'
        if not made:
            return f"Game version {version} · no map files made from the game yet. {link}", "warn"
        if made != [version]:
            return f"Game version {version} · map files {', '.join(made)}. {link}", "warn"
        return f"Map and game version synced ({version})", "ok"

    def refresh_sync(self):
        status = self.sync_status()
        self.sync_note.setVisible(status is not None)
        if status:
            text, kind = status
            self.sync_note.setText(text)
            if self.sync_note.objectName() != kind:
                self.sync_note.setObjectName(kind)
                self.sync_note.style().unpolish(self.sync_note)   # re-apply the style for the new name
                self.sync_note.style().polish(self.sync_note)

    def update_map_files(self):
        """The main page's "Update map files" link: the Maps tab's game import."""
        self.tabs.setCurrentWidget(self.maps_tab)
        started = self.import_game()
        self.refresh_sync()
        return started

    def _game_status(self, maps):
        game = self._game_dir()
        if game is None:
            if self.config.game_dir:
                return (f"No Crimson Desert install at {self.config.game_dir}. Pick another game folder, "
                        "or find it via Steam."), False
            return ("Crimson Desert install not found in the Steam libraries. Use “Game folder…” to pick it; "
                    "map images can still be imported."), False
        try:
            version = Archive(game).version()
        except (ArchiveError, OSError) as e:
            return f"Crimson Desert install unreadable: {e}", False
        self.m_game.setToolTip(f"Game folder: {game}")
        imported = {m["gameVersion"] for m in maps if m["source"] == "A" and m.get("fixed")}
        if not imported:
            return (f"Crimson Desert {version} found at {game}. Import its world map for an exact, "
                    "calibration-free map."), True
        if imported != {version}:
            return (f"<b>Game updated</b> to {version} (maps are from {', '.join(sorted(v or '?' for v in imported))}): "
                    "re-import from game files."), True
        return f"Crimson Desert {version}: game map up to date.", True

    def choose_marker_import(self):
        path, _ = QFileDialog.getOpenFileName(self, "Import markers", "", MARKER_FILTER)
        if not path:
            return
        dialog = ImportDialog(self, path, title="Import markers")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.import_markers(path, **dialog.values())

    def import_markers(self, path, realm, name="", source="C", licence=""):
        """A marker set from CSV / GeoJSON / JSON (game x/z); quick, so it runs here."""
        try:
            data = read_marker_file(path, name or Path(path).stem, source, licence, realm)
            s = self.backend.markers.save(data)
        except (MapError, OSError, ValueError) as e:
            self.m_note.setText(f"Marker import failed: {e}")
            return None
        log.info("Imported marker set %s (%d markers)", s["id"], s["count"])
        self.backend.notify_markers()
        self.m_note.setText(f"Imported {s['count']} markers as “{s['name']}”; they show on connected devices now.")
        return s

    def activate_selected_map(self):
        map_id = self._selected_map()
        if not map_id:
            return
        try:
            self.backend.maps.set_active(self.backend.maps.get(map_id)["realm"], map_id)
        except (MapError, NotFound) as e:
            self.m_note.setText(str(e))
            return
        self.backend.notify_maps(map_id, "active")
        self.refresh_maps()

    def delete_selected_map(self, confirm=True):
        map_id = self._selected_map()
        if not map_id:
            return
        if confirm and QMessageBox.question(self, "Maps", f"Delete map {map_id} and its tiles?") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.backend.maps.delete(map_id)
        except (NotFound, OSError) as e:
            self.m_note.setText(f"Delete failed: {e}")
            return
        log.info("Deleted map %s", map_id)
        self.backend.notify_maps(map_id, "deleted")
        self.refresh_maps()
