"""
audiokeys — PySide 6
--------------------------------------

"""

from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Optional

import numpy as np
from q_materialise import inject_style
from appdirs import user_data_dir

# ``sounddevice`` is used to enumerate audio capture devices and open
# input streams.  If the module itself cannot be imported (e.g. it is
# not installed), we set ``sd`` to ``None`` and handle the failure
# gracefully in device enumeration and worker startup.  Do **not** catch
# arbitrary exceptions here so that platform‑specific import errors
# (e.g. missing PortAudio libraries) propagate, allowing users to
# diagnose installation problems.  See `_populate_devices` for
# per‑call error handling during enumeration.
try:
    import sounddevice as sd  # type: ignore
except ImportError:
    sd = None

# ─── Qt ────────────────────────────────────────────────────────────────────────
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import QPoint, QSettings, QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QToolTip

"""
Main Qt GUI for the AudioKeys application.

This module constructs the user interface for mapping recorded sounds to
key presses, selecting an audio capture device and viewing real‑time
feedback from the audio processing thread.  The GUI is designed to run
both when AudioKeys is installed as a package (e.g. via
``pip install audiokeys``) and when the source files are executed
directly from a checkout.  To accommodate both scenarios it attempts to
import other modules from the ``audiokeys`` package first and falls back
to relative imports on failure.

The menu bar exposes ``File`` (with an Exit action), ``Settings``
(opening a dialog to tweak audio parameters) and ``Help`` (providing
links to documentation and an About dialog).  User‑adjustable audio
parameters are persisted via ``QSettings``, meaning values survive
between launches without editing the ``constants.py`` file.
"""

# Attempt to import from the installed package.  If AudioKeys is not
# installed and the modules are available locally, fall back to relative
# imports.  This allows ``python gui.py`` to run without requiring
# ``pip install -e .``.
try:
    from audiokeys import constants  # type: ignore
    from audiokeys.sound_worker import SoundWorker  # type: ignore
    from audiokeys.sample_matcher import record_until_silence  # type: ignore
    from audiokeys.utils import generate_sample_id, make_svg_toolbutton, resource_path  # type: ignore
    from audiokeys.noise_gate import calculate_noise_floor, trim_silence  # type: ignore
except Exception:
    # Local fallback imports – only works when run from the project root
    import constants  # type: ignore
    from sound_worker import SoundWorker  # type: ignore
    from sample_matcher import record_until_silence  # type: ignore
    from utils import generate_sample_id, resource_path  # type: ignore
    from noise_gate import calculate_noise_floor, trim_silence  # type: ignore

# ─── Note ──────────────────────────────────────────────────────────────────
# The audio capture and key mapping features are designed to work cross‑platform.
# On Linux we attempt to use python‑uinput for low‑level key events; on
# other platforms we fall back to pynput.  Any unused or Linux‑specific
# stream routing functions have been removed to simplify the code.

# Unused stream helpers (list_playback_streams and ensure_monitor_for_stream)
# were removed from this version.  If future work requires enumerating
# applications playing sound or creating monitor sinks, those should be
# implemented in a separate module and imported conditionally.

list_playback_streams = None  # placeholder for removed functionality

# -----------------------------------------------------------------------------
# NOTE_NAMES and DEFAULT_NOTE_MAP are imported from constants.py.  Other
# configuration such as sample rate, hop size and noise gating parameters are
# defined in that module and used by AudioWorker.  Keeping the constants in a
# separate module avoids duplication and makes it easy to tune the system from
# one place.


class KeyMappingWindow(QtWidgets.QDialog):
    """Separate window showing all key mappings in a scrollable list."""

    def __init__(self, main_window: MainWindow):
        super().__init__(main_window)
        self.main_window = main_window
        self.setWindowTitle("Key Mappings")
        self.setModal(True)

        layout = QtWidgets.QVBoxLayout(self)

        top_row = QtWidgets.QHBoxLayout()
        add_btn = QtWidgets.QPushButton("Add Key Mapping")
        add_btn.clicked.connect(self._on_add)
        top_row.addWidget(add_btn)
        top_row.addStretch()
        layout.addLayout(top_row)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.inner = QtWidgets.QWidget()
        self.inner_layout = QtWidgets.QVBoxLayout(self.inner)
        self.inner_layout.setSpacing(6)
        self.inner_layout.setContentsMargins(4, 4, 4, 4)
        self.scroll.setWidget(self.inner)
        layout.addWidget(self.scroll, 1)

        btn_box = QtWidgets.QHBoxLayout()
        close_btn = QtWidgets.QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_box.addStretch()
        btn_box.addWidget(close_btn)
        layout.addLayout(btn_box)

        self.refresh()

        self.setMinimumWidth(700)
        self.setMinimumHeight(800)  # constrain height

    def refresh(self):
        # Clear existing rows
        while self.inner_layout.count():
            item = self.inner_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)

        # Rebuild from the authoritative main_window.note_map
        for sample_id, key_name in self.main_window.note_map.items():
            row = self.main_window._make_mapping_row_widget(sample_id, key_name)
            self.inner_layout.addWidget(row)
        self.inner_layout.addStretch()

    def _on_add(self):
        self.main_window._add_mapping()
        self.refresh()


# ─── Key and audio workers are defined in separate modules ─────────────
# The ``KeySender`` class lives in ``key_sender.py`` and the audio capture
# logic resides in ``sound_worker.py``.  Importing these modules at the top
# keeps the GUI decoupled from the low‑level audio and input code.
# ─── Main Window ──────────────────────────────────────────────────────────────
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()

        # 1️⃣ create your QSettings (organisation, application)
        self.settings = QSettings("arched.dev", "audiokeys")
        self.setWindowTitle("Piano Keyboard")
        # 2️⃣ mappings and persistent storage
        # ``note_map`` stores sample identifiers → key names
        self.note_map: dict[str, str] = {}
        # recorded samples keyed by identifier; each entry stores a list of
        # reference samples for that sound
        self.samples: dict[str, list[np.ndarray]] = {}
        # file paths for each recorded sample list
        self.sample_files: dict[str, list[str]] = {}
        # application data directory for storing samples
        self.data_dir = Path(user_data_dir("audiokeys", "arched.dev"))
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.worker: Optional[SoundWorker] = None

        # Track test mode (True disables key presses).  Persist value in settings.
        tm_val = self.settings.value("test_mode", False)
        # QSettings may return strings; normalise to bool
        if isinstance(tm_val, str):
            self.test_mode = tm_val.lower() in ("true", "1", "yes", "y")
        else:
            self.test_mode = bool(tm_val)

        # store labels for each note mapping so we can update them easily
        self.key_labels: dict[str, QtWidgets.QLineEdit] = {}
        # widgets representing each mapping for grid layout
        self.mapping_widgets: dict[str, QtWidgets.QWidget] = {}

        # Build the user interface
        self._build_ui()

        # Load any previously recorded samples
        self._load_samples()

        # Build menu bar with file, settings and help entries
        self._create_menu()

    def _save_mappings(self) -> None:
        """Persist sample metadata to ``QSettings``."""
        self.settings.setValue("note_map", json.dumps(self.note_map))
        self.settings.setValue("sample_files", json.dumps(self.sample_files))

    def _load_samples(self) -> None:
        """Load previously recorded samples from disk, pruning missing or invalid ones."""
        map_json = self.settings.value("note_map", "{}")
        files_json = self.settings.value("sample_files", "{}")
        try:
            raw_note_map = json.loads(map_json)
            raw_sample_files = json.loads(files_json)
        except Exception:
            raw_note_map = {}
            raw_sample_files = {}

        cleaned_note_map: dict[str, str] = {}
        cleaned_sample_files: dict[str, list[str]] = {}

        for sample_id, paths in raw_sample_files.items():
            loaded: list[np.ndarray] = []
            valid_paths: list[str] = []
            for path in paths:
                p = Path(path)
                if not p.exists():
                    # file was deleted manually; skip it
                    continue
                try:
                    sample = np.load(p)
                except Exception as e:
                    # log corrupted / unreadable file and skip it
                    self._append_log(f"Failed to load sample {p!s}: {e}")
                    continue
                trimmed = trim_silence(sample)
                if trimmed.size:
                    loaded.append(trimmed)
                    valid_paths.append(str(p))
            if loaded:
                # retain this mapping
                self.samples[sample_id] = loaded
                key = raw_note_map.get(sample_id, "")
                self._add_mapping_row(sample_id, key)
                cleaned_sample_files[sample_id] = valid_paths
                if sample_id in raw_note_map:
                    cleaned_note_map[sample_id] = raw_note_map[sample_id]
            else:
                # no valid samples left; drop mapping and per-note setting
                self.settings.remove(sample_id)

        # Replace with cleaned versions and persist
        self.note_map = cleaned_note_map
        self.sample_files = cleaned_sample_files
        self._save_mappings()

    def _make_heading(self, text: str):
        title = QtWidgets.QLabel(text)
        # make it stand out a bit:
        font = title.font()
        font.setPointSize(font.pointSize() + 2)
        font.setBold(True)
        title.setFont(font)
        return title

    def _on_source_changed(self):
        self._populate_devices()

    # -----------------------------------------------------------------
    def _build_ui(self):
        central = QtWidgets.QWidget()
        root_layout = QtWidgets.QVBoxLayout(central)
        root_layout.setSpacing(16)
        root_layout.setContentsMargins(8, 8, 8, 8)

        mapping_btn = QtWidgets.QPushButton("View / Edit Key Mapping")
        mapping_btn.clicked.connect(self._open_keymapping_window)
        root_layout.addWidget(mapping_btn)

        root_layout.addWidget(self._make_heading("Output Log"))
        # 4️⃣ Log area
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        root_layout.addWidget(self.log, 1)

        # 5️⃣ Sound meter and tuner
        level_heading = self._make_heading("Sound Level")
        root_layout.addWidget(level_heading)
        self.level_bar = QtWidgets.QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setValue(0)
        self.level_bar.setTextVisible(False)
        root_layout.addWidget(self.level_bar)

        # 3️⃣ Control row
        ctrl_layout = QtWidgets.QHBoxLayout()
        self.start_btn = QtWidgets.QPushButton("Start Listening")
        self.start_btn.clicked.connect(self._toggle_start)
        self.listen_lbl = QtWidgets.QLabel("Listening for notes…")
        self.listen_lbl.setVisible(False)
        ctrl_layout.addWidget(self.start_btn)
        ctrl_layout.addWidget(self.listen_lbl)
        # Test listening checkbox and info
        self.test_checkbox = QtWidgets.QCheckBox("Test Listening")
        # Restore persisted state
        self.test_checkbox.setChecked(self.test_mode)
        self.test_checkbox.toggled.connect(self._on_test_mode_toggled)
        ctrl_layout.addWidget(self.test_checkbox)
        test_info_btn = make_svg_toolbutton(resource_path("assets/info.svg"), "Test Listening Info", lambda: QToolTip.showText(
                test_info_btn.mapToGlobal(QPoint(0, test_info_btn.height())),
                test_info_btn.toolTip(),
                test_info_btn,
            ))

        test_info_btn.setAutoRaise(True)
        test_info_btn.setToolTip(
            "<b>Test Listening</b><br><br>"
            "When enabled, detected sounds will be displayed\n"
            "in the log but no keyboard keys will be pressed.  Use this\n"
            "mode to experiment with detection settings without triggering\n"
            "any applications."
        )

        ctrl_layout.addWidget(test_info_btn)
        ctrl_layout.addStretch()
        root_layout.addLayout(ctrl_layout)

        self.setCentralWidget(central)
        self.resize(700, 800)
        self.setFixedSize(700, 800)


    def _open_keymapping_window(self):
        if not getattr(self, "keymapping_window", None):
            self.keymapping_window = KeyMappingWindow(self)
        self.keymapping_window.refresh()
        self.keymapping_window.exec()

    def _populate_device_combo(self) -> None:
        """Legacy combo-box population (input vs loopback) copied from the original implementation."""
        is_windows = sys.platform.startswith("win")
        want_loopback = False
        if hasattr(self, "capture_out"):
            want_loopback = self.capture_out.isChecked()
        else:
            # fallback to stored setting for compatibility
            val = self.settings.value("capture_out", False)
            if isinstance(val, str):
                want_loopback = val.lower() in ("true", "1", "yes", "y")
            else:
                want_loopback = bool(val)

        def is_monitor(name: str) -> bool:
            n = name.lower()
            return ("monitor" in n) or ("loopback" in n)

        def label_for(idx: int, name: str, hostapi_name: str) -> str:
            if is_windows and want_loopback:
                return f"{idx}: WASAPI · {name}"
            return f"{idx}: {name}"

        self.device_combo.blockSignals(True)
        self.device_combo.clear()

        if sd is None:
            self.device_combo.addItem("sounddevice module not available", -1)
            self.device_combo.blockSignals(False)
            return

        try:
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()
        except Exception as e:
            self.device_combo.addItem(f"Audio enumeration failed: {e}", -1)
            self.device_combo.blockSignals(False)
            return

        for idx, dev in enumerate(devices):
            name = dev["name"]
            hostapi_idx = dev.get("hostapi", 0)
            hostapi_name = hostapis[hostapi_idx]["name"]

            if not want_loopback:
                if dev.get("max_input_channels", 0) >= 1 and not is_monitor(name):
                    self.device_combo.addItem(label_for(idx, name, hostapi_name), idx)
            else:
                if is_windows:
                    if ("wasapi" in hostapi_name.lower()) and dev.get(
                        "max_output_channels", 0
                    ) >= 1:
                        self.device_combo.addItem(label_for(idx, name, hostapi_name), idx)
                else:
                    if is_monitor(name) and dev.get("max_input_channels", 0) >= 1:
                        self.device_combo.addItem(label_for(idx, name, hostapi_name), idx)

        key = "device_out" if want_loopback else "device_in"
        preferred = self.settings.value(key, None)
        if preferred is None:
            try:
                default_in, default_out = sd.default.device
            except Exception:
                default_in = default_out = None
            preferred = default_out if (want_loopback and is_windows) else default_in

        try:
            if preferred is not None:
                row = self.device_combo.findData(int(preferred))
                if row >= 0:
                    self.device_combo.setCurrentIndex(row)
                    self.device_combo.blockSignals(False)
                    return
        except Exception:
            pass

        if self.device_combo.count():
            self.device_combo.setCurrentIndex(0)

        if want_loopback and self.device_combo.count() == 0:
            self.device_combo.addItem("No system output devices found", -1)

        self.device_combo.blockSignals(False)


    def _populate_devices(self) -> None:
        """Rebuild the audio input menu."""
        if hasattr(self, "device_menu"):
            self._update_device_menu()

    # -----------------------------------------------------------------
    def _update_map(self, note: str, text: str):
        # Store the full trimmed value so users can enter names like "space",
        # "enter", "f1" etc.  We normalise to lowercase to simplify lookup
        # later on.  If no characters are provided we clear the mapping for
        # that note.
        key_name = text.strip().lower()
        self.note_map[note] = key_name
        # persist this single‑note setting
        self.settings.setValue(note, key_name)

    # -----------------------------------------------------------------
    def _toggle_start(self):
        if self.worker and self.worker.isRunning():
            self._stop_listening()
        else:
            self._start_listening()

    # -----------------------------------------------------------------
    def _start_listening(self) -> None:
        idx = self.current_device_index()
        if idx is None:
            QtWidgets.QMessageBox.warning(self, "No device", "Select an audio device.")
            return

        self.settings.setValue("device_in", idx)

        if sd is None:
            QtWidgets.QMessageBox.warning(
                self,
                "Audio support missing",
                "The sounddevice module could not be loaded.\n"
                "Please install the 'sounddevice' package to enable audio capture.",
            )
            return

        channels = 1  # always standard input, no loopback/system output


        # Stop any existing worker
        if self.worker and self.worker.isRunning():
            self._stop_listening()

        # Load audio parameters from settings, falling back to defaults
        # Use the default noise gate duration from constants.  The
        # adjustable noise gate duration setting has been removed from
        # the UI, so this value is no longer persisted.  A preset
        # noise floor via calibration supersedes this calibration
        # duration.
        gate_dur = constants.NOISE_GATE_CALIBRATION_TIME
        gate_margin = float(
            self.settings.value("noise_gate_margin", constants.NOISE_GATE_MARGIN)
        )
        hp_cutoff = float(self.settings.value("hp_cutoff", constants.HP_FILTER_CUTOFF))
        sample_rate = int(self.settings.value("sample_rate", constants.SAMPLE_RATE))
        buffer_size = int(self.settings.value("buffer_size", constants.BUFFER_SIZE))
        hop_size = int(self.settings.value("hop_size", constants.HOP_SIZE))
        match_method = str(
            self.settings.value("detection_method", constants.MATCH_METHOD)
        )
        noise_floor_key = f"noise_floor_{idx}"
        noise_floor_val = self.settings.value(noise_floor_key, None)
        preset_floor = None
        try:
            if noise_floor_val is not None:
                preset_floor = float(noise_floor_val)
        except Exception:
            preset_floor = None

        match_thresh = float(
            self.settings.value("match_threshold", constants.MATCH_THRESHOLD)
        )

        self.worker = SoundWorker(
            idx,
            self.samples,
            self.note_map,
            channels=channels,
            sample_rate=sample_rate,
            buffer_size=buffer_size,
            hop_size=hop_size,
            hp_cutoff=hp_cutoff,
            noise_gate_duration=gate_dur,
            noise_gate_margin=gate_margin,
            preset_noise_floor=preset_floor,
            match_threshold=match_thresh,
            match_method=match_method,
            send_enabled=not getattr(self, "test_mode", False),
        )
        self.worker.keyDetected.connect(self._on_key_detected)
        self.worker.finished.connect(self._on_worker_done)
        self.worker.amplitudeChanged.connect(self._on_amplitude_changed)
        self.worker.start()

        self.start_btn.setText("Stop Listening")
        self.listen_lbl.setVisible(True)

    def _stop_listening(self):
        if self.worker:
            self.worker.stop()
            self.worker = None

        self.start_btn.setText("Start Listening")
        self.listen_lbl.setVisible(False)
        # Reset meters when stopping
        if hasattr(self, "level_bar"):
            self.level_bar.setValue(0)
        # Clear the output log so that new sessions start
        # fresh.  Without clearing the log, previous
        # detections persist and can cause confusion.
        if hasattr(self, "log"):
            self.log.clear()

    # -----------------------------------------------------------------
    # Worker callbacks
    def _on_key_detected(self, key: str) -> None:
        self._append_log(f"Detected {key}")
        if key in self.key_labels:
            lbl = self.key_labels[key]
            lbl.setStyleSheet("background-color: yellow")
            QtCore.QTimer.singleShot(300, lambda: lbl.setStyleSheet(""))

    def _on_worker_done(self):
        # Safety if worker ends by itself (device closed etc.)ljh
        self.start_btn.setText("Start Listening")
        self.listen_lbl.setVisible(False)
        # Reset meters
        if hasattr(self, "level_bar"):
            self.level_bar.setValue(0)

    # -----------------------------------------------------------------
    def _append_log(self, msg: str):
        # append at the end
        self.log.appendPlainText(msg)
        # ensure the new text is visible
        self.log.ensureCursorVisible()

    # -----------------------------------------------------------------
    # -----------------------------------------------------------------
    # Key selection
    def _add_mapping(self) -> None:
        """Record one or more samples and map them to a keyboard key."""
        idx = self.current_device_index()
        if idx is None:
            QtWidgets.QMessageBox.warning(self, "No device", "Select an audio device.")
            return

        key_dlg = KeySelectDialog(self, "sound", "")
        if key_dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        key_name = key_dlg.get_selected_key()
        if key_name in self.note_map.values():
            QtWidgets.QMessageBox.warning(
                self, "Key in use", f"{key_name} is already mapped."
            )
            return

        samp_dlg = SampleDialog(self, int(idx))
        if samp_dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        base = samp_dlg.get_name().strip()
        if not base:
            QtWidgets.QMessageBox.warning(self, "No name", "Provide a sound name.")
            return
        if base in self.note_map:
            QtWidgets.QMessageBox.warning(
                self, "Name in use", f"Sound name '{base}' is already mapped. Pick a different name."
            )
            return

        sample_id = base  # use exactly what the user provided, no underscore suffixing
        refs: list[np.ndarray] = []
        paths: list[str] = []
        for i, sample in enumerate(samp_dlg.samples):
            refs.append(sample)
            path = self.data_dir / f"{sample_id}_{i}.npy"
            np.save(path, sample)
            paths.append(str(path))
        self.samples[sample_id] = refs
        self.note_map[sample_id] = key_name
        self.sample_files[sample_id] = paths
        self._add_mapping_row(sample_id, key_name)
        self._save_mappings()


    def _make_mapping_row_widget(self, sample_id: str, key_name: str) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(container)
        row.setContentsMargins(4, 4, 4, 4)
        lbl = QtWidgets.QLabel(sample_id)
        lbl.setFixedWidth(150)
        key_lbl = QtWidgets.QLineEdit(key_name)
        key_lbl.setReadOnly(True)
        self.key_labels[sample_id] = key_lbl

        change_btn = make_svg_toolbutton(resource_path("assets/keyboard.svg"), "Change Key", lambda _, s=sample_id: self._change_key(s))
        edit_btn = make_svg_toolbutton(resource_path("assets/edit.svg"), "Edit Samples", lambda _, s=sample_id: self._edit_samples(s))
        del_btn = make_svg_toolbutton(resource_path("assets/delete.svg"), "Delete Mapping", lambda _, s=sample_id: self._delete_mapping(s))

        # change_btn.setIconSize(QSize(16, 16))
        # edit_btn.setIconSize(QSize(16, 16))
        # del_btn.setIconSize(QSize(16, 16))

        row.addWidget(lbl)
        row.addWidget(key_lbl)
        row.addWidget(change_btn)
        row.addWidget(edit_btn)
        row.addWidget(del_btn)
        return container

    def _add_mapping_row(self, sample_id: str, key_name: str) -> None:
        widget = self._make_mapping_row_widget(sample_id, key_name)
        self.mapping_widgets[sample_id] = widget
        # If the key-mapping window is open, refresh its contents so it's in sync.
        if hasattr(self, "keymapping_window") and self.keymapping_window:
            self.keymapping_window.refresh()

    def _edit_samples(self, sample_id: str) -> None:
        """Open ``SampleDialog`` to replace or remove samples for ``sample_id``."""
        idx = self.current_device_index()
        if idx is None:
            QtWidgets.QMessageBox.warning(self, "No device", "Select an audio device.")
            return

        existing = self.samples.get(sample_id, [])
        dlg = SampleDialog(
            self,
            int(idx),
            name=sample_id,
            samples=existing,
            name_readonly=True,
        )
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return

        for path in self.sample_files.get(sample_id, []):
            Path(path).unlink(missing_ok=True)

        self.samples[sample_id] = dlg.samples[:]
        paths: list[str] = []
        for i, sample in enumerate(dlg.samples):
            path = self.data_dir / f"{sample_id}_{i}.npy"
            np.save(path, sample)
            paths.append(str(path))
        self.sample_files[sample_id] = paths
        self._save_mappings()

    def _change_key(self, sample_id: str) -> None:
        if self.worker and self.worker.isRunning():
            self._stop_listening()
        current = self.note_map.get(sample_id, "")
        dlg = KeySelectDialog(self, sample_id, current)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            key = dlg.get_selected_key()
            if key in self.note_map.values() and self.note_map.get(sample_id) != key:
                QtWidgets.QMessageBox.warning(
                    self, "Key in use", f"{key} is already mapped."
                )
                return
            self.note_map[sample_id] = key
            if sample_id in self.key_labels:
                self.key_labels[sample_id].setText(key)
            self._save_mappings()
            if hasattr(self, "keymapping_window") and self.keymapping_window:
                self.keymapping_window.refresh()

    def _delete_mapping(self, sample_id: str) -> None:
        if sample_id in self.samples:
            del self.samples[sample_id]
        if sample_id in self.note_map:
            del self.note_map[sample_id]
        if sample_id in self.key_labels:
            del self.key_labels[sample_id]
        paths = self.sample_files.pop(sample_id, [])
        for path in paths:
            Path(path).unlink(missing_ok=True)
        widget = self.mapping_widgets.pop(sample_id, None)
        if widget is not None:
            widget.setParent(None)
        self._save_mappings()

        if hasattr(self, "keymapping_window") and self.keymapping_window:
            self.keymapping_window.refresh()
    # -----------------------------------------------------------------
    # Amplitude meter callback
    def _on_amplitude_changed(self, rms: float) -> None:
        # Simple linear scaling: convert RMS (typically 0–1) into a 0–100 range
        level = min(int(rms * 300.0), 100)
        self.level_bar.setValue(level)

    # -----------------------------------------------------------------
    # -----------------------------------------------------------------
    def _on_test_mode_toggled(self, checked: bool) -> None:
        """
        Slot invoked when the Test Listening checkbox is toggled.

        When ``checked`` is True the application enters test mode: sounds
        are still detected and shown in the log but no keyboard keys are
        pressed.  The state is persisted via ``QSettings``.  If a worker
        is running its sender is toggled live.

        Parameters
        ----------
        checked : bool
            The new state of the checkbox.
        """
        self.test_mode = bool(checked)
        self.settings.setValue("test_mode", self.test_mode)
        # Update the running worker (if any) to enable/disable key sending
        if self.worker and self.worker.isRunning():
            try:
                self.worker.set_send_enabled(not self.test_mode)
            except Exception:
                pass

    def _create_audio_input_menu(self) -> None:
        audio_menu = self.menuBar().addMenu("Audio Input")
        # Device submenu
        self.device_menu = audio_menu.addMenu("Device")
        self._update_device_menu()


    def _update_device_menu(self) -> None:
        """Rebuild the Device submenu showing all physical input devices."""
        self.device_menu.clear()

        if sd is None:
            act = QtGui.QAction("sounddevice module not available", self)
            act.setEnabled(False)
            self.device_menu.addAction(act)
            return

        try:
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()
        except Exception as e:
            act = QtGui.QAction(f"Audio enumeration failed: {e}", self)
            act.setEnabled(False)
            self.device_menu.addAction(act)
            return

        def is_monitor(name: str) -> bool:
            n = name.lower()
            return ("monitor" in n) or ("loopback" in n)

        device_group = QtGui.QActionGroup(self)
        device_group.setExclusive(True)

        for idx, dev in enumerate(devices):
            if dev.get("max_input_channels", 0) < 1:
                continue
            name = dev["name"]
            if is_monitor(name):
                continue  # skip virtual monitor/loopback devices
            # label is just index and name
            label = f"{idx}: {name}"
            action = QtGui.QAction(label, self, checkable=True)
            action.setData(idx)
            device_group.addAction(action)
            self.device_menu.addAction(action)
            action.triggered.connect(lambda checked, i=idx: self._select_device(i))

        # Restore preferred input device
        preferred = self.settings.value("device_in", None)
        if preferred is None:
            try:
                default_in, _ = sd.default.device
            except Exception:
                default_in = None
            preferred = default_in

        for action in self.device_menu.actions():
            data = action.data()
            if data is None:
                continue
            try:
                if preferred is not None and int(data) == int(preferred):
                    action.setChecked(True)
            except Exception:
                pass

        # Fallback to first if nothing is selected
        if not any(a.isChecked() for a in self.device_menu.actions()) and self.device_menu.actions():
            self.device_menu.actions()[0].setChecked(True)

    def _select_device(self, idx: int) -> None:
        key = "device_in"
        self.settings.setValue(key, idx)

    def current_device_index(self):
        # Return the index of the currently selected device from the menu
        for action in getattr(self, "device_menu", []).actions():
            if action.isChecked():
                return action.data()
        return None

    # -----------------------------------------------------------------
    def _create_menu(self) -> None:
        """
        Populate the top‑level menu bar with File, Settings and Help
        menus.  Each menu contains relevant actions:

        * **File → Exit** closes the application.
        * **Settings → Audio Parameters…** opens the audio parameter
          dialog.
        * **Help → Visit Docs** opens the project documentation in the
          default web browser.
        * **Help → About** shows an About dialog describing the
          application.
        """
        menubar = self.menuBar()

        # File menu with Exit action
        file_menu = menubar.addMenu("File")
        exit_action = file_menu.addAction("Exit")
        exit_action.triggered.connect(self.close)

        # Settings menu containing audio parameters
        settings_menu = menubar.addMenu("Settings")
        audio_action = settings_menu.addAction("Audio Parameters…")
        audio_action.triggered.connect(self._open_settings_dialog)

        self._create_audio_input_menu()

        # Help menu providing docs and about
        help_menu = menubar.addMenu("Help")
        docs_action = help_menu.addAction("Visit Docs")
        docs_action.triggered.connect(self._visit_docs)
        about_action = help_menu.addAction("About")
        about_action.triggered.connect(self._show_about)

    # -----------------------------------------------------------------
    def _open_settings_dialog(self) -> None:
        """
        Open the audio parameter dialog.

        If audio capture is currently running, the worker is
        stopped before displaying the settings dialog.  This
        prevents the background listener from sending key events
        while the user is interacting with the dialog.  When the
        user accepts the dialog the worker is restarted with the
        updated settings.  If the dialog is cancelled the worker
        remains stopped until the user explicitly starts listening
        again via the main window.
        """
        # Stop listening up front to avoid interference from the
        # audio worker while tweaking settings.
        if self.worker and self.worker.isRunning():
            self._stop_listening()

        dlg = SettingsDialog(self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            # The settings dialog persists values via QSettings on accept.
            # Previously the worker would restart automatically here, but
            # this behaviour has been removed so that closing the dialog
            # does not implicitly start listening.  Users can start
            # listening again by pressing the "Start Listening" button.
            pass

    # -----------------------------------------------------------------
    # -----------------------------------------------------------------
    def _visit_docs(self) -> None:
        """
        Open the project documentation URL in the user's default web
        browser.  The URL is stored in a module constant for easy
        maintenance; if you fork the project, update the link here.
        """
        url = QtCore.QUrl("https://github.com/lewis-morris/audiokeys")
        QtGui.QDesktopServices.openUrl(url)

    # -----------------------------------------------------------------
    def _show_about(self) -> None:
        """
        Display an About dialog with basic information about the
        application, including its version and author.  The contents
        here can be customised to reflect project metadata.
        """
        # Compose the about text as a single string.  Newlines are not
        # permitted inside literal strings without escaping, so this is
        # constructed with adjacent string literals.
        about_text = (
            "<h3>AudioKeys</h3>"
            "<p>Map recorded sounds to keyboard keys in real time.</p>"
            "<p>Developed by Lewis Morris (Arched dev).</p>"
            "<p>See the <a href='https://github.com/lewis-morris/audiokeys'>project repository</a> "
            "for documentation and source code.</p>"
        )
        QtWidgets.QMessageBox.about(
            self,
            "About AudioKeys",
            about_text,
        )


# ─── main ─────────────────────────────────────────────────────────────────────
def run_gui():
    QtCore.QCoreApplication.setAttribute(
        QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling
    )
    app = QtWidgets.QApplication(sys.argv)

    inject_style(app, style="crimson_depth")

    icon_file = resource_path("assets/icon.ico")
    icon = QIcon(icon_file)

    app.setWindowIcon(icon)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


# ─── Dialogs ────────────────────────────────────────────────────────────────


class RecordingThread(QtCore.QThread):
    """Background thread that records audio using ``record_until_silence``."""

    recorded = QtCore.Signal(np.ndarray)

    def __init__(self, device_index: int) -> None:
        super().__init__()
        self.device_index = device_index
        self._stop = threading.Event()

    def run(self) -> None:  # noqa: D401 - simple delegator
        sample = record_until_silence(self.device_index, stop_event=self._stop)
        self.recorded.emit(sample)

    def stop(self) -> None:
        """Request the recording thread to stop."""
        self._stop.set()


class SampleDialog(QtWidgets.QDialog):
    """Dialog for naming a sound and recording multiple samples."""

    def __init__(
        self,
        parent: QtWidgets.QWidget,
        device_index: int,
        *,
        name: str = "",
        samples: Optional[list[np.ndarray]] = None,
        name_readonly: bool = False,
    ) -> None:
        super().__init__(parent)
        self.device_index = device_index
        self.samples: list[np.ndarray] = samples[:] if samples else []
        self.setWindowTitle("Record Samples")
        layout = QtWidgets.QVBoxLayout(self)

        name_layout = QtWidgets.QHBoxLayout()
        name_layout.addWidget(QtWidgets.QLabel("Sound name:"))
        self.name_edit = QtWidgets.QLineEdit(name)
        self.name_edit.setReadOnly(name_readonly)
        self.name_edit.setMaxLength(15)

        name_layout.addWidget(self.name_edit)
        layout.addLayout(name_layout)

        self.list_widget = QtWidgets.QListWidget()
        for idx in range(len(self.samples)):
            self.list_widget.addItem(f"Sample {idx + 1}")
        layout.addWidget(self.list_widget)

        btn_layout = QtWidgets.QHBoxLayout()
        self.record_btn = QtWidgets.QPushButton("Record Sample")
        self.record_btn.clicked.connect(self._toggle_recording)
        btn_layout.addWidget(self.record_btn)

        self.play_btn = QtWidgets.QPushButton("Play")
        self.play_btn.clicked.connect(self._play_sample)
        btn_layout.addWidget(self.play_btn)

        self.delete_btn = QtWidgets.QPushButton("Delete")
        self.delete_btn.clicked.connect(self._delete_sample)
        btn_layout.addWidget(self.delete_btn)

        self.test_btn = QtWidgets.QPushButton("Test Detection")
        self.test_btn.setCheckable(True)
        self.test_btn.toggled.connect(self._toggle_test)
        btn_layout.addWidget(self.test_btn)

        layout.addLayout(btn_layout)

        self.level_bar = QtWidgets.QProgressBar()
        self.level_bar.setRange(0, 100)
        layout.addWidget(self.level_bar)

        self.detect_lbl = QtWidgets.QLabel("")
        layout.addWidget(self.detect_lbl)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self._thread: Optional[RecordingThread] = None
        self._test_worker: Optional[SoundWorker] = None

        self.setMinimumWidth(800)
        self.setMinimumHeight(500)

    # ------------------------------------------------------------------
    def _toggle_recording(self) -> None:
        if self._thread and self._thread.isRunning():
            self._thread.stop()
            return
        self.record_btn.setText("Stop")
        self._thread = RecordingThread(self.device_index)
        self._thread.recorded.connect(self._on_recorded)
        self._thread.start()

    def _on_recorded(self, sample: np.ndarray) -> None:
        if self._thread:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
        if sample.size:
            trimmed = trim_silence(sample)
            if trimmed.size:
                self.samples.append(trimmed)
                self.list_widget.addItem(f"Sample {len(self.samples)}")
        self.record_btn.setText("Record Sample")

    def _play_sample(self) -> None:
        if not sd:
            return
        items = self.list_widget.selectedIndexes()
        if not items:
            return
        sample = self.samples[items[0].row()]
        sd.play(sample, 44_100)
        sd.wait()

    def _delete_sample(self) -> None:
        items = self.list_widget.selectedIndexes()
        if not items:
            return
        idx = items[0].row()
        self.samples.pop(idx)
        self.list_widget.takeItem(idx)

    def _toggle_test(self, checked: bool) -> None:
        """Start or stop live matching against the recorded samples."""

        if checked:
            if not self.samples:
                QtWidgets.QMessageBox.warning(
                    self, "No samples", "Record samples before testing."
                )
                self.test_btn.setChecked(False)
                return

            parent = self.parent()
            settings = parent.settings if hasattr(parent, "settings") else None
            sample_rate = (
                int(settings.value("sample_rate", constants.SAMPLE_RATE))
                if settings
                else constants.SAMPLE_RATE
            )
            buffer_size = (
                int(settings.value("buffer_size", constants.BUFFER_SIZE))
                if settings
                else constants.BUFFER_SIZE
            )
            gate_margin = (
                float(settings.value("noise_gate_margin", constants.NOISE_GATE_MARGIN))
                if settings
                else constants.NOISE_GATE_MARGIN
            )
            hp_cutoff = (
                float(settings.value("hp_cutoff", constants.HP_FILTER_CUTOFF))
                if settings
                else constants.HP_FILTER_CUTOFF
            )
            match_thresh = (
                float(settings.value("match_threshold", constants.MATCH_THRESHOLD))
                if settings
                else constants.MATCH_THRESHOLD
            )

            match_method = (
                str(settings.value("detection_method", constants.MATCH_METHOD))
                if settings
                else constants.MATCH_METHOD
            )

            noise_floor_key = f"noise_floor_{self.device_index}"
            preset_floor = None
            if settings:
                nf = settings.value(noise_floor_key, None)
                try:
                    if nf is not None:
                        preset_floor = float(nf)
                except Exception:
                    preset_floor = None

            sample_id = self.name_edit.text() or "sample"
            mapping = {sample_id: self.samples}
            note_map = {sample_id: ""}

            self._test_worker = SoundWorker(
                self.device_index,
                mapping,
                note_map,
                channels=1,
                sample_rate=sample_rate,
                buffer_size=buffer_size,
                hop_size=constants.HOP_SIZE,
                hp_cutoff=hp_cutoff,
                noise_gate_duration=constants.NOISE_GATE_CALIBRATION_TIME,
                noise_gate_margin=gate_margin,
                preset_noise_floor=preset_floor,
                match_threshold=match_thresh,
                match_method=match_method,
                send_enabled=False,
            )
            self._test_worker.keyDetected.connect(self._on_test_detected)
            self._test_worker.amplitudeChanged.connect(self._on_test_amplitude)
            self._test_worker.start()
            self.test_btn.setText("Stop Test")
        else:
            if self._test_worker:
                self._test_worker.stop()
                self._test_worker = None
            self.test_btn.setText("Test Detection")
            self.detect_lbl.clear()
            self.level_bar.setValue(0)

    def _on_test_detected(self, key: str) -> None:
        """Display the detected sample identifier."""

        self.detect_lbl.setText(f"Detected {key}")

    def _on_test_amplitude(self, rms: float) -> None:
        """Update the level bar using the RMS amplitude."""

        level = min(int(rms * 300.0), 100)
        self.level_bar.setValue(level)

    def reject(self) -> None:  # noqa: D401 - close dialog
        if self._thread and self._thread.isRunning():
            self._thread.stop()
            self._thread.wait()
        if self._test_worker and self._test_worker.isRunning():
            self._test_worker.stop()
            self._test_worker.wait(2000)
            self._test_worker = None
        super().reject()

    def accept(self) -> None:
        if not self.samples:
            QtWidgets.QMessageBox.warning(
                self, "No samples", "Record at least one sample."
            )
            return
        if not self.name_edit.text().strip():
            QtWidgets.QMessageBox.warning(self, "No name", "Provide a sound name.")
            return
        if self._test_worker and self._test_worker.isRunning():
            self._test_worker.stop()
            self._test_worker.wait(2000)
            self._test_worker = None
        super().accept()

    def get_name(self) -> str:
        """Return the user-provided sound name."""
        return self.name_edit.text().strip()


class KeySelectDialog(QtWidgets.QDialog):
    """
    Dialog for selecting a key mapping.  Presents a list of possible keys
    (letters, numbers and special names) so the user doesn’t have to type
    free‑form text.  The dialog inherits the parent window’s icon and
    displays the note name in its title.
    """

    def __init__(self, parent: QtWidgets.QWidget, note: str, current_key: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Map key for {note}")
        # Use same icon as parent
        if parent.windowIcon():
            self.setWindowIcon(parent.windowIcon())

        self.selected_key: str = current_key

        layout = QtWidgets.QVBoxLayout(self)
        info_label = QtWidgets.QLabel(f"Choose a key to trigger note <b>{note}</b>:")
        layout.addWidget(info_label)

        # Available keys: letters, digits, special names and function keys
        keys = []
        # Letters a–z
        keys.extend([chr(c) for c in range(ord("a"), ord("z") + 1)])
        # Digits 0–9
        keys.extend([str(d) for d in range(10)])
        # Special names
        specials = [
            "space",
            "enter",
            "return",
            "tab",
            "esc",
            "escape",
            "left",
            "right",
            "up",
            "down",
            "home",
            "end",
            "pageup",
            "pagedown",
            "backspace",
            "delete",
            "capslock",
        ]
        keys.extend(specials)
        # Function keys f1–f12
        keys.extend([f"f{i}" for i in range(1, 13)])
        # Remove duplicates and sort
        unique_keys = sorted(dict.fromkeys(keys))

        self.combo = QtWidgets.QComboBox()
        self.combo.addItems(unique_keys)
        # Preselect current key if present
        if current_key:
            idx = self.combo.findText(current_key, QtCore.Qt.MatchFixedString)
            if idx >= 0:
                self.combo.setCurrentIndex(idx)
        layout.addWidget(self.combo)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        self.selected_key = self.combo.currentText().strip().lower()
        super().accept()

    def get_selected_key(self) -> str:
        return self.selected_key


class SettingsDialog(QtWidgets.QDialog):
    """Dialog allowing adjustment of basic audio parameters."""

    def __init__(self, parent: MainWindow) -> None:
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("Audio Parameters")
        if parent.windowIcon():
            self.setWindowIcon(parent.windowIcon())

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        settings = parent.settings

        def make_field(
            spinbox: QtWidgets.QDoubleSpinBox, description: str
        ) -> QtWidgets.QWidget:
            container = QtWidgets.QWidget()
            v = QtWidgets.QVBoxLayout(container)
            v.setContentsMargins(0, 0, 0, 0)
            v.addWidget(spinbox)
            desc = QtWidgets.QLabel(description)
            desc.setWordWrap(True)
            font = desc.font()
            font.setPointSize(font.pointSize() - 1)
            desc.setFont(font)
            v.addWidget(desc)
            return container

        # Sample rate
        default_sr = int(settings.value("sample_rate", constants.SAMPLE_RATE))
        self.sample_rate_spin = QtWidgets.QSpinBox()
        self.sample_rate_spin.setRange(8000, 96000)
        self.sample_rate_spin.setSingleStep(1000)
        self.sample_rate_spin.setValue(default_sr)
        form.addRow(
            "Sample rate (Hz)",
            make_field(
                self.sample_rate_spin,
                "Audio sampling rate. Higher values improve fidelity at the cost of CPU usage.",
            ),
        )

        # Buffer size
        default_buf = int(settings.value("buffer_size", constants.BUFFER_SIZE))
        self.buffer_size_spin = QtWidgets.QSpinBox()
        self.buffer_size_spin.setRange(256, 8192)
        self.buffer_size_spin.setSingleStep(256)
        self.buffer_size_spin.setValue(default_buf)
        form.addRow(
            "Buffer size",
            make_field(
                self.buffer_size_spin,
                "Number of samples per analysis buffer. Larger buffers reduce CPU usage but increase latency.",
            ),
        )

        # Noise gate margin
        default_gate_margin = float(
            settings.value("noise_gate_margin", constants.NOISE_GATE_MARGIN)
        )
        self.gate_margin_spin = QtWidgets.QDoubleSpinBox()
        self.gate_margin_spin.setRange(1.0, 5.0)
        self.gate_margin_spin.setSingleStep(0.1)
        self.gate_margin_spin.setDecimals(2)
        self.gate_margin_spin.setValue(default_gate_margin)
        form.addRow(
            "Noise gate margin",
            make_field(
                self.gate_margin_spin,
                "Multiplier applied to the measured noise floor; values above 1.0 make detection less sensitive.",
            ),
        )

        # Detection method
        default_method = str(settings.value("detection_method", constants.MATCH_METHOD))
        self.method_combo = QtWidgets.QComboBox()
        self.method_combo.addItems(["waveform", "mfcc", "dtw"])
        if default_method in ("waveform", "mfcc", "dtw"):
            self.method_combo.setCurrentText(default_method)
        form.addRow(
            "Detection method",
            make_field(
                self.method_combo,
                "Algorithm used to compare recorded samples.",
            ),
        )

        # Match threshold
        default_match = float(
            settings.value("match_threshold", constants.MATCH_THRESHOLD)
        )
        self.match_thresh_spin = QtWidgets.QDoubleSpinBox()
        self.match_thresh_spin.setRange(0.0, 1.0)
        self.match_thresh_spin.setSingleStep(0.05)
        self.match_thresh_spin.setDecimals(2)
        self.match_thresh_spin.setValue(default_match)
        form.addRow(
            "Match threshold",
            make_field(
                self.match_thresh_spin,
                "Minimum cosine similarity required for detection; lower values increase sensitivity.",
            ),
        )

        # High-pass filter cutoff
        default_hp_cutoff = float(
            settings.value("hp_cutoff", constants.HP_FILTER_CUTOFF)
        )
        self.hp_cutoff_spin = QtWidgets.QDoubleSpinBox()
        self.hp_cutoff_spin.setRange(20.0, 1000.0)
        self.hp_cutoff_spin.setSingleStep(10.0)
        self.hp_cutoff_spin.setDecimals(1)
        self.hp_cutoff_spin.setValue(default_hp_cutoff)
        form.addRow(
            "High-pass cutoff",
            make_field(
                self.hp_cutoff_spin,
                "Cutoff frequency (Hz) of the high-pass filter; frequencies below this are attenuated to remove rumble and hum.",
            ),
        )

        cal_btn = QtWidgets.QPushButton("Calibrate Noise Floor")
        cal_btn.clicked.connect(self._calibrate_noise_floor)
        layout.addWidget(cal_btn)

        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal,
            self,
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        self.setMinimumWidth(500)


    def accept(self) -> None:
        settings = self.parent_window.settings
        settings.setValue("sample_rate", self.sample_rate_spin.value())
        settings.setValue("buffer_size", self.buffer_size_spin.value())
        settings.setValue("noise_gate_margin", self.gate_margin_spin.value())
        settings.setValue("detection_method", self.method_combo.currentText())
        settings.setValue("match_threshold", self.match_thresh_spin.value())
        settings.setValue("hp_cutoff", self.hp_cutoff_spin.value())
        super().accept()

    def _calibrate_noise_floor(self) -> None:
        """Measure ambient noise and store it for the selected device."""
        idx = self.parent_window.current_device_index()

        if idx is None:
            QtWidgets.QMessageBox.warning(self, "No device", "Select an audio device.")
            return
        if sd is None:
            QtWidgets.QMessageBox.warning(
                self,
                "Audio support missing",
                "The sounddevice module could not be loaded.",
            )
            return
        try:
            sample_rate = int(self.sample_rate_spin.value())
            duration = 2.0
            total = int(sample_rate * duration)
            blocks: list[np.ndarray] = []
            with sd.InputStream(
                device=int(idx),
                channels=1,
                samplerate=sample_rate,
                blocksize=constants.HOP_SIZE,
                dtype="float32",
            ) as stream:
                while sum(b.size for b in blocks) < total:
                    data, _ = stream.read(constants.HOP_SIZE)
                    blocks.append(data.reshape(-1))
            samples = np.concatenate(blocks)[:total]
            floor = calculate_noise_floor(samples)
            self.parent_window.settings.setValue(f"noise_floor_{idx}", floor)
            QtWidgets.QMessageBox.information(
                self,
                "Calibration complete",
                "Noise floor stored.",
            )
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Calibration failed", str(e))
