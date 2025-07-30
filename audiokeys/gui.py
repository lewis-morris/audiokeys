"""
audiokeys — PySide 6
--------------------------------------

"""

from __future__ import annotations

import sys
from typing import Optional

import numpy as np
from q_materialise import inject_style

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
from PySide6.QtCore import QPoint, QSettings
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QToolTip

"""
Main Qt GUI for the AudioKeys application.

This module constructs the user interface for mapping musical notes to key
presses, selecting an audio capture device and viewing real‑time feedback
from the audio processing thread.  The GUI is designed to run both when
AudioKeys is installed as a package (e.g. via ``pip install audiokeys``)
and when the source files are executed directly from a checkout.  To
accommodate both scenarios it attempts to import other modules from the
``audiokeys`` package first and falls back to relative imports on
failure.

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
    from audiokeys import note_calibration  # type: ignore
    from audiokeys.sound_worker import SoundWorker  # type: ignore
    from audiokeys.sample_matcher import record_until_silence  # type: ignore
    from audiokeys.utils import resource_path  # type: ignore
except Exception:
    # Local fallback imports – only works when run from the project root
    import constants  # type: ignore
    import note_calibration  # type: ignore
    from sound_worker import SoundWorker  # type: ignore
    from sample_matcher import record_until_silence  # type: ignore
    from utils import resource_path  # type: ignore

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


# ─── Key and audio workers are now defined in separate modules ─────────────
# The ``KeySender`` class has been moved to ``key_sender.py`` and the
# ``AudioWorker`` class (which manages audio capture, filtering and note
# detection) has been moved to ``audio_worker.py``.  Importing the worker
# at the top of this file provides the same interface as before without
# coupling the GUI to the low‑level audio and input logic.
# ─── Main Window ──────────────────────────────────────────────────────────────
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()

        # 1️⃣ create your QSettings (organisation, application)
        self.settings = QSettings("arched.dev", "audiokeys")
        self.setWindowTitle("Piano Keyboard")
        # 2️⃣ load from settings, falling back to DEFAULT_NOTE_MAP
        self.note_map: dict[str, str] = {}
        for note in constants.NOTE_NAMES:
            # the stored value is the single‐char, or use the default
            self.note_map[note] = self.settings.value(
                note, constants.DEFAULT_NOTE_MAP[note]
            )

        # recorded samples for each note
        self.samples: dict[str, np.ndarray] = {}

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

        # Build the user interface
        self._build_ui()

        # Build menu bar with file, settings and help entries
        self._create_menu()

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

        root_layout.addWidget(self._make_heading("Key Mapping"))

        # 1️⃣ Note mapping grid
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)

        notes_per_row = 3
        for idx, note in enumerate(constants.NOTE_NAMES):
            row = idx // notes_per_row
            col = (idx % notes_per_row) * 5

            # Static note label (e.g. "C", "C#", etc.)
            lbl = QtWidgets.QLabel(note)
            lbl.setFixedWidth(24)

            # Display current key mapping
            key_lbl = QtWidgets.QLineEdit()
            key_lbl.setReadOnly(True)
            key_lbl.setText(self.note_map.get(note, ""))
            key_lbl.setFixedWidth(120)
            self.key_labels[note] = key_lbl

            # Button to open key selector
            btn = QtWidgets.QPushButton()
            btn.setIcon(QIcon(self.style().standardIcon(QtWidgets.QStyle.SP_ArrowDown)))
            btn.clicked.connect(lambda checked=False, n=note: self._choose_key(n))

            rec_btn = QtWidgets.QPushButton("Record")
            rec_btn.clicked.connect(
                lambda checked=False, n=note: self._record_sample(n)
            )
            del_btn = QtWidgets.QPushButton("Delete")
            del_btn.clicked.connect(
                lambda checked=False, n=note: self._delete_sample(n)
            )

            grid.addWidget(lbl, row, col)
            grid.addWidget(key_lbl, row, col + 1)
            grid.addWidget(btn, row, col + 2)
            grid.addWidget(rec_btn, row, col + 3)
            grid.addWidget(del_btn, row, col + 4)

        root_layout.addLayout(grid)

        audio_heading_layout = QtWidgets.QHBoxLayout()
        audio_heading = self._make_heading("Audio Input Device")

        # ── ⓘ info button --------------------------------------------
        info_btn = QtWidgets.QToolButton()
        info_btn.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.SP_MessageBoxInformation)
        )
        info_btn.setAutoRaise(True)
        info_btn.setToolTip(
            "<b>Capture modes</b><br><br>"
            "<u>Microphone / Line‑in</u><br>Capture audio from any physical input device connected to your machine.<br><br>"
            "<u>System Output</u><br>Capture all audio output (all running apps).<br><br>"
        )

        # show on hover (built‑in) *and* on click:
        info_btn.clicked.connect(
            lambda: QToolTip.showText(
                info_btn.mapToGlobal(QPoint(0, info_btn.height())),
                info_btn.toolTip(),
                info_btn,
            )
        )

        audio_heading_layout.addWidget(audio_heading)
        audio_heading_layout.addWidget(info_btn)

        root_layout.addLayout(audio_heading_layout)

        source_layout = QtWidgets.QHBoxLayout()

        # ── Capture‑source radio buttons ───────────────────────
        self.capture_mic = QtWidgets.QRadioButton("Microphone / Line‑in")
        self.capture_out = QtWidgets.QRadioButton("System Output")
        self.capture_mic.setChecked(True)

        for rb in (self.capture_mic, self.capture_out):
            rb.toggled.connect(self._on_source_changed)
            source_layout.addWidget(rb)

        root_layout.addLayout(source_layout)

        # 2️⃣ Device selector
        dev_layout = QtWidgets.QHBoxLayout()
        self.device_combo = QtWidgets.QComboBox()
        self._populate_devices()
        dev_layout.addWidget(self.device_combo, 1)
        root_layout.addLayout(dev_layout)

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
        test_info_btn = QtWidgets.QToolButton()
        test_info_btn.setIcon(
            self.style().standardIcon(QtWidgets.QStyle.SP_MessageBoxInformation)
        )
        test_info_btn.setAutoRaise(True)
        test_info_btn.setToolTip(
            "<b>Test Listening</b><br><br>"
            "When enabled, detected notes and pitches will be displayed\n"
            "in the log but no keyboard keys will be pressed.  Use this\n"
            "mode to experiment with detection settings without triggering\n"
            "any applications."
        )
        test_info_btn.clicked.connect(
            lambda: QToolTip.showText(
                test_info_btn.mapToGlobal(QPoint(0, test_info_btn.height())),
                test_info_btn.toolTip(),
                test_info_btn,
            )
        )
        ctrl_layout.addWidget(test_info_btn)
        ctrl_layout.addStretch()
        root_layout.addLayout(ctrl_layout)

        self.setCentralWidget(central)
        self.resize(700, 800)
        self.setFixedSize(700, 800)

    # -----------------------------------------------------------------
    def _populate_devices(self) -> None:
        """
        Mic / Line‑in  → list standard input devices.
        System Output  →
          • Linux: list 'monitor' / 'loopback' input devices.
          • Windows: list WASAPI OUTPUT devices (opened with loopback=True).
        Keeps the last‑used device for the active mode when possible.
        """
        is_windows = sys.platform.startswith("win")
        want_loopback = self.capture_out.isChecked()

        def is_monitor(name: str) -> bool:
            n = name.lower()
            return ("monitor" in n) or ("loopback" in n)

        # Helper: format the visible label
        def label_for(idx: int, name: str, hostapi_name: str) -> str:
            # Make WASAPI obvious in loopback mode on Windows
            if is_windows and want_loopback:
                return f"{idx}: WASAPI · {name}"
            return f"{idx}: {name}"

        self.device_combo.blockSignals(True)
        self.device_combo.clear()

        # Short‑circuit if the sounddevice module is unavailable
        if sd is None:
            self.device_combo.addItem("sounddevice module not available", -1)
            self.device_combo.blockSignals(False)
            return

        try:
            devices = sd.query_devices()
            hostapis = sd.query_hostapis()
        except Exception as e:
            # Graceful fallback if PortAudio is unhappy
            self.device_combo.addItem(f"Audio enumeration failed: {e}", -1)
            self.device_combo.blockSignals(False)
            return

        for idx, dev in enumerate(devices):
            name = dev["name"]
            hostapi_idx = dev.get("hostapi", 0)
            hostapi_name = hostapis[hostapi_idx]["name"]

            if not want_loopback:
                # Mic / line‑in: real input devices, not monitors
                if dev.get("max_input_channels", 0) >= 1 and not is_monitor(name):
                    self.device_combo.addItem(label_for(idx, name, hostapi_name), idx)
            else:
                if is_windows:
                    # Loopback on Windows needs an OUTPUT device on WASAPI
                    if ("wasapi" in hostapi_name.lower()) and dev.get(
                        "max_output_channels", 0
                    ) >= 1:
                        self.device_combo.addItem(
                            label_for(idx, name, hostapi_name), idx
                        )
                else:
                    # Linux: monitors are exposed as input devices
                    if is_monitor(name) and dev.get("max_input_channels", 0) >= 1:
                        self.device_combo.addItem(
                            label_for(idx, name, hostapi_name), idx
                        )

        self.device_combo.blockSignals(False)

        # Choose a sensible default / restore last used
        key = "device_out" if want_loopback else "device_in"
        preferred = self.settings.value(key, None)

        # Fall back to PortAudio defaults if nothing stored
        if preferred is None:
            try:
                # (input, output)
                default_in, default_out = sd.default.device
            except Exception:
                default_in = default_out = None

            preferred = default_out if (want_loopback and is_windows) else default_in

        # Apply preferred if present in the list
        try:
            if preferred is not None:
                row = self.device_combo.findData(int(preferred))
                if row >= 0:
                    self.device_combo.setCurrentIndex(row)
                    return
        except Exception:
            pass

        # Otherwise pick first available item
        if self.device_combo.count():
            self.device_combo.setCurrentIndex(0)

        # If no devices were found when capturing system output on
        # Linux, present a placeholder entry so the combo box is not
        # blank.  This informs the user that no monitor/loopback
        # devices are available and suggests that a loopback device
        # needs to be created via the system’s audio settings.
        if want_loopback and self.device_combo.count() == 0:
            self.device_combo.addItem("No system output devices found", -1)

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
        want_loopback = self.capture_out.isChecked()
        idx = self.device_combo.currentData()
        if idx is None:
            QtWidgets.QMessageBox.warning(self, "No device", "Select an audio device.")
            return

        self.settings.setValue("device_out" if want_loopback else "device_in", idx)

        # If sounddevice failed to import earlier we cannot start listening
        if sd is None:
            QtWidgets.QMessageBox.warning(
                self,
                "Audio support missing",
                "The sounddevice module could not be loaded.\n"
                "Please install the 'sounddevice' package to enable audio capture.",
            )
            return

        # Configure channels and WASAPI loopback if needed
        extra = None
        channels = 1

        if want_loopback and sys.platform.startswith("win"):
            # WASAPI loopback requires extra_settings; many devices prefer 2 channels
            channels = 2
            extra = sd.WasapiSettings(loopback=True)

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
        midi_tol = float(
            self.settings.value("midi_tolerance", constants.MIDI_SEMITONE_TOLERANCE)
        )
        conf_thresh = float(
            self.settings.value(
                "confidence_threshold", constants.AUBIO_CONFIDENCE_THRESHOLD
            )
        )
        sample_rate = int(self.settings.value("sample_rate", constants.SAMPLE_RATE))
        buffer_size = int(self.settings.value("buffer_size", constants.BUFFER_SIZE))
        hop_size = int(self.settings.value("hop_size", constants.HOP_SIZE))
        detection_method = str(self.settings.value("detection_method", "aubio"))
        # Retrieve any previously calibrated noise floor for this device
        noise_floor_key = f"noise_floor_{idx}"
        noise_floor_val = self.settings.value(noise_floor_key, None)
        preset_noise_floor = None
        try:
            if noise_floor_val is not None:
                preset_noise_floor = float(noise_floor_val)
        except Exception:
            preset_noise_floor = None

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
            match_threshold=0.8,
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
    # Key selection
    def _choose_key(self, note: str) -> None:
        """
        Open a modal dialog allowing the user to choose a key mapping for
        the specified note.  On acceptance the mapping and UI label are
        updated and persisted via QSettings.
        """
        # Stop any running worker to avoid key presses while selecting a mapping
        if self.worker and self.worker.isRunning():
            self._stop_listening()
        current_key = self.note_map.get(note, "")
        dlg = KeySelectDialog(self, note, current_key)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            selected = dlg.get_selected_key()
            self.note_map[note] = selected
            # update label and persist
            if note in self.key_labels:
                self.key_labels[note].setText(selected)
            self.settings.setValue(note, selected)

    def _record_sample(self, note: str) -> None:
        if note in self.samples:
            if (
                QtWidgets.QMessageBox.question(
                    self,
                    "Override sample",
                    f"Replace existing sample for {note}?",
                )
                != QtWidgets.QMessageBox.Yes
            ):
                return
        idx = self.device_combo.currentData()
        if idx is None:
            QtWidgets.QMessageBox.warning(self, "No device", "Select an audio device.")
            return
        sample = record_until_silence(int(idx))
        self.samples[note] = sample

    def _delete_sample(self, note: str) -> None:
        if note in self.samples:
            del self.samples[note]

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

        When ``checked`` is True the application enters test mode: notes
        and frequencies are still detected and shown in the log and
        tuner display, but no keyboard keys are pressed.  The state is
        persisted via ``QSettings``.  If a worker is running its
        sender is toggled live.

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

        notes_action = settings_menu.addAction("Calibrate Notes…")
        notes_action.triggered.connect(self._open_note_calibration)

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
    def _open_note_calibration(self) -> None:
        """Open the note calibration dialog."""
        dlg = NoteCalibrationDialog(self)
        dlg.exec()

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
            "<p>Map musical notes to keyboard keys in real time.</p>"
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

    inject_style(app, style="tangerine_morning")

    icon_file = resource_path("assets/icon.ico")
    icon = QIcon(icon_file)

    app.setWindowIcon(icon)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


# ─── Dialogs ────────────────────────────────────────────────────────────────
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
    """
    Dialog allowing the user to adjust audio processing parameters.  Values
    are persisted via QSettings and used when starting the AudioWorker.
    Explanatory tooltips help users understand the impact of each parameter.
    """

    def __init__(self, parent: MainWindow) -> None:
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("Audio Parameters")
        # Use same icon as parent
        if parent.windowIcon():
            self.setWindowIcon(parent.windowIcon())

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        settings = parent.settings

        def make_field(
            spinbox: QtWidgets.QDoubleSpinBox, description: str
        ) -> QtWidgets.QWidget:
            """
            Wrap a spin box together with a descriptive label in a
            vertically stacked container.  This helper ensures that the
            explanatory text is shown directly beneath the control,
            improving discoverability over tooltips alone.

            Parameters
            ----------
            spinbox : QDoubleSpinBox
                The numeric control for the user to adjust.
            description : str
                A human‑readable explanation of what the control does.

            Returns
            -------
            QWidget
                A widget containing the spin box and its description.
            """
            container = QtWidgets.QWidget()
            v = QtWidgets.QVBoxLayout(container)
            v.setContentsMargins(0, 0, 0, 0)
            v.addWidget(spinbox)
            desc = QtWidgets.QLabel(description)
            desc.setWordWrap(True)
            # Use a smaller, grey font for descriptions
            font = desc.font()
            font.setPointSize(font.pointSize() - 1)
            desc.setFont(font)
            v.addWidget(desc)
            return container

        # The noise gate duration parameter has been removed from the UI.  A
        # calibrated noise floor obviates the need for a separate
        # duration setting, so users no longer need to adjust it.  We
        # still honour existing saved values for backwards
        # compatibility, but no control is exposed here.  The default
        # value from constants.py will be used when starting the
        # AudioWorker.

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
                "Audio sampling rate. Higher values improve accuracy at the cost of CPU usage.",
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

        # Hop size
        default_hop = int(settings.value("hop_size", constants.HOP_SIZE))
        self.hop_size_spin = QtWidgets.QSpinBox()
        self.hop_size_spin.setRange(64, 4096)
        self.hop_size_spin.setSingleStep(64)
        self.hop_size_spin.setValue(default_hop)
        form.addRow(
            "Hop size",
            make_field(
                self.hop_size_spin,
                "Processing hop size in samples; typically a quarter of the buffer size.",
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
                "Multiplier applied to the measured noise floor; values above 1.0 make note detection less sensitive.",
            ),
        )

        # High‑pass filter cutoff
        default_hp_cutoff = float(
            settings.value("hp_cutoff", constants.HP_FILTER_CUTOFF)
        )
        self.hp_cutoff_spin = QtWidgets.QDoubleSpinBox()
        self.hp_cutoff_spin.setRange(20.0, 1000.0)
        self.hp_cutoff_spin.setSingleStep(10.0)
        self.hp_cutoff_spin.setDecimals(1)
        self.hp_cutoff_spin.setValue(default_hp_cutoff)
        form.addRow(
            "High‑pass cutoff",
            make_field(
                self.hp_cutoff_spin,
                "Cutoff frequency (Hz) of the high‑pass filter; frequencies below this are attenuated to remove rumble and hum.",
            ),
        )

        # MIDI tolerance
        default_midi_tol = float(
            settings.value("midi_tolerance", constants.MIDI_SEMITONE_TOLERANCE)
        )
        self.midi_tol_spin = QtWidgets.QDoubleSpinBox()
        self.midi_tol_spin.setRange(0.1, 2.0)
        self.midi_tol_spin.setSingleStep(0.1)
        self.midi_tol_spin.setDecimals(2)
        self.midi_tol_spin.setValue(default_midi_tol)
        form.addRow(
            "Pitch tolerance",
            make_field(
                self.midi_tol_spin,
                "Tolerance (in semitones) for pitch drift before a new note is considered; smaller values increase sensitivity.",
            ),
        )

        # Minimum aubio pitch confidence
        default_conf = float(
            settings.value("confidence_threshold", constants.AUBIO_CONFIDENCE_THRESHOLD)
        )
        self.conf_thresh_spin = QtWidgets.QDoubleSpinBox()
        self.conf_thresh_spin.setRange(0.0, 1.0)
        self.conf_thresh_spin.setSingleStep(0.05)
        self.conf_thresh_spin.setDecimals(2)
        self.conf_thresh_spin.setValue(default_conf)
        form.addRow(
            "Min pitch confidence",
            make_field(
                self.conf_thresh_spin,
                "Discard detected pitches whose aubio confidence is below this value (0–1).",
            ),
        )

        # Detection method
        # Available options map user‑friendly names to internal identifiers used by AudioWorker
        self.detect_combo = QtWidgets.QComboBox()
        # Define a list of (label, method) pairs
        self._det_methods = [
            ("Aubio (default)", "aubio"),
            ("Aubio YIN", "yin"),
            ("Aubio YIN FFT", "yinfft"),
            ("FFT peak detection", "fft"),
        ]
        for label, _ in self._det_methods:
            self.detect_combo.addItem(label)
        # Restore previously selected method from settings or default
        current_method = str(settings.value("detection_method", "aubio"))
        # Find index by matching stored method
        for idx, (_, method) in enumerate(self._det_methods):
            if method == current_method:
                self.detect_combo.setCurrentIndex(idx)
                break
        # Create a container with description text
        det_container = QtWidgets.QWidget()
        det_layout = QtWidgets.QVBoxLayout(det_container)
        det_layout.setContentsMargins(0, 0, 0, 0)
        det_layout.addWidget(self.detect_combo)
        det_desc = QtWidgets.QLabel(
            "Select the pitch detection algorithm. Aubio is robust across instruments; "
            "YIN and YIN FFT are alternative Aubio methods; FFT uses a simple spectral peak finder."
        )
        det_desc.setWordWrap(True)
        font = det_desc.font()
        font.setPointSize(font.pointSize() - 1)
        det_desc.setFont(font)
        det_layout.addWidget(det_desc)
        form.addRow("Detection method", det_container)

        # Calibration button – placed after the form.  When calibration is
        # running we change the label and disable all close controls to
        # prevent the dialog from being closed prematurely.
        self.calibrate_btn = QtWidgets.QPushButton("Calibrate Selected Device…")
        self.calibrate_btn.clicked.connect(self._calibrate_device)
        layout.addWidget(self.calibrate_btn)

        # Dialog button box (OK/Cancel).  We store a reference so it can
        # be disabled during calibration.  Without this reference the
        # buttons would remain enabled and the dialog could be closed
        # while calibration is in progress.
        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal,
            self,
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

        # Track whether a calibration is in progress.  This flag is
        # consulted in closeEvent to ignore user attempts to close the
        # dialog while the calibration is running.
        self._calibrating: bool = False

    def accept(self) -> None:
        # Persist user‑selected values
        settings = self.parent_window.settings
        settings.setValue("noise_gate_margin", self.gate_margin_spin.value())
        settings.setValue("hp_cutoff", self.hp_cutoff_spin.value())
        settings.setValue("midi_tolerance", self.midi_tol_spin.value())
        settings.setValue("confidence_threshold", self.conf_thresh_spin.value())
        settings.setValue("sample_rate", self.sample_rate_spin.value())
        settings.setValue("buffer_size", self.buffer_size_spin.value())
        settings.setValue("hop_size", self.hop_size_spin.value())
        # Persist detection method
        # Map current combo index to internal identifier
        idx = self.detect_combo.currentIndex()
        method = (
            self._det_methods[idx][1] if 0 <= idx < len(self._det_methods) else "aubio"
        )
        settings.setValue("detection_method", method)
        super().accept()

    def _calibrate_device(self) -> None:
        """Perform a ten‑second calibration of the currently selected audio device.

        The calibration measures the ambient noise floor using the
        selected input device and stores the result in the application
        settings keyed by the device index.  A message is displayed
        upon completion.
        """
        # Obtain the current device index from the parent window
        device_idx = self.parent_window.device_combo.currentData()
        if device_idx is None or device_idx == -1:
            QtWidgets.QMessageBox.warning(
                self,
                "No device selected",
                "Please select an audio device in the main window before calibrating.",
            )
            return

        # Determine channel count.  On Windows loopback the worker uses two channels.
        channels = 1
        try:
            import sys as _sys  # local import to avoid polluting module namespace

            if self.parent_window.capture_out.isChecked() and _sys.platform.startswith(
                "win"
            ):
                channels = 2
        except Exception:
            channels = 1

        # Inform the user and perform calibration in a blocking manner.  In a real
        # application this could be moved to a worker thread with progress
        # updates.  For simplicity we block the UI and warn the user to
        # remain silent.  If the user cancels we return immediately.
        confirm = QtWidgets.QMessageBox.information(
            self,
            "Calibrate Background Noise",
            "The application will record background noise for 10 seconds.\n"
            "Please ensure the room is quiet and no notes are played during this time.",
            QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel,
        )
        if confirm != QtWidgets.QMessageBox.Ok:
            return

        # Begin calibration: update UI state and disable closing
        self._calibrating = True
        # Disable buttons and change label to indicate progress
        self.calibrate_btn.setEnabled(False)
        self.calibrate_btn.setText("Calibrating…")
        if hasattr(self, "buttons"):
            self.buttons.setEnabled(False)
        # Process pending UI events so the button label and disabled
        # state update before recording begins.  Without this call the
        # UI may not reflect the state change until after the
        # blocking calibration has finished.
        QtWidgets.QApplication.processEvents()

        try:
            import numpy as _np
            import sounddevice as _sd
            from scipy.signal import butter, sosfilt

            duration = 10.0  # seconds
            sample_rate = int(
                self.parent_window.settings.value("sample_rate", constants.SAMPLE_RATE)
            )
            # Record raw audio.  We avoid extra_settings and rely on the device
            # configuration alone.  dtype float32 to match AudioWorker
            recording = _sd.rec(
                int(duration * sample_rate),
                samplerate=sample_rate,
                channels=channels,
                device=int(device_idx),
                dtype="float32",
            )
            _sd.wait()
            # Down‑mix to mono
            if recording.ndim == 2 and recording.shape[1] > 1:
                mono = recording.mean(axis=1).astype("float32")
            else:
                mono = recording.reshape(-1).astype("float32")
            # Apply a high‑pass filter using the current cutoff from settings
            hp_cutoff = float(
                self.parent_window.settings.value(
                    "hp_cutoff", constants.HP_FILTER_CUTOFF
                )
            )
            nyquist = sample_rate / 2.0
            norm_cut = max(min(hp_cutoff / nyquist, 0.99), 0.001)
            sos = butter(2, norm_cut, btype="highpass", output="sos")
            filtered = sosfilt(sos, mono)
            # Compute RMS values per hop and take the median as noise floor
            hop_size = int(
                self.parent_window.settings.value("hop_size", constants.HOP_SIZE)
            )
            rms_vals: list[float] = []
            for start in range(0, len(filtered), hop_size):
                block = filtered[start : start + hop_size]
                if block.size == 0:
                    continue
                rms = float(_np.sqrt(_np.mean(block**2)))
                rms_vals.append(rms)
            if not rms_vals:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Calibration failed",
                    "Unable to compute RMS values for calibration.",
                )
                return
            noise_floor = float(_np.median(rms_vals))
            # Persist noise floor keyed by device index
            key = f"noise_floor_{device_idx}"
            self.parent_window.settings.setValue(key, noise_floor)
            QtWidgets.QMessageBox.information(
                self,
                "Calibration complete",
                f"Noise floor calibrated at {noise_floor:.6f} RMS for device {device_idx}.\n"
                "This value will be used for future sessions with this device.",
            )
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, "Calibration error", f"An error occurred during calibration:\n{e}"
            )
        finally:
            # Restore UI state regardless of success/failure
            self._calibrating = False
            self.calibrate_btn.setEnabled(True)
            self.calibrate_btn.setText("Calibrate Selected Device…")
            if hasattr(self, "buttons"):
                self.buttons.setEnabled(True)

    # -----------------------------------------------------------------
    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        """
        Prevent closing the settings dialog while a calibration
        recording is running.  If the calibration flag is set the
        event is ignored.  Otherwise the base class implementation
        handles the close normally.
        """
        # If calibration is in progress ignore the close request
        if getattr(self, "_calibrating", False):
            event.ignore()
            return
        super().closeEvent(event)


class NoteCalibrationDialog(QtWidgets.QDialog):
    """Dialog guiding the user through note calibration."""

    def __init__(self, parent: MainWindow) -> None:
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("Calibrate Notes")
        if parent.windowIcon():
            self.setWindowIcon(parent.windowIcon())

        self.status = QtWidgets.QLabel("Click Start to record each note in octave 4.")
        self.start_btn = QtWidgets.QPushButton("Start")
        self.start_btn.clicked.connect(self._start)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.status)
        layout.addWidget(self.start_btn)

    def _start(self) -> None:
        device_idx = self.parent_window.device_combo.currentData()
        if device_idx is None or device_idx == -1:
            QtWidgets.QMessageBox.warning(
                self,
                "No device selected",
                "Please select an audio device in the main window before calibrating.",
            )
            return

        sample_rate = int(
            self.parent_window.settings.value("sample_rate", constants.SAMPLE_RATE)
        )
        hop_size = int(
            self.parent_window.settings.value("hop_size", constants.HOP_SIZE)
        )

        channels = 1
        try:
            import sys as _sys

            if self.parent_window.capture_out.isChecked() and _sys.platform.startswith(
                "win"
            ):
                channels = 2
        except Exception:
            channels = 1

        def record_func(
            note: str,
            duration: float,
            rate: int,
            ch: int,
            dev: Optional[int],
        ) -> np.ndarray:
            self.status.setText(f"Recording {note}…")
            QtWidgets.QApplication.processEvents()
            data = sd.rec(
                int(duration * rate),
                samplerate=rate,
                channels=ch,
                device=dev,
                dtype="float32",
            )
            sd.wait()
            if data.ndim > 1:
                data = data.mean(axis=1)
            return data.reshape(-1)

        self.start_btn.setEnabled(False)
        QtWidgets.QApplication.processEvents()

        try:
            results = note_calibration.calibrate_pitches(
                constants.NOTE_NAMES,
                duration=1.0,
                sample_rate=sample_rate,
                hop_size=hop_size,
                channels=channels,
                octave=4,
                device=int(device_idx),
                record_func=record_func,
                interactive=False,
            )
            tol = note_calibration.calculate_midi_tolerance(results)
            self.parent_window.settings.setValue("midi_tolerance", tol)
            QtWidgets.QMessageBox.information(
                self,
                "Calibration complete",
                f"Recommended pitch tolerance: {tol:.2f} semitones.\n"
                "This value has been saved for future sessions.",
            )
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, "Calibration error", f"An error occurred during calibration:\n{e}"
            )
        finally:
            self.status.clear()
            self.start_btn.setEnabled(True)
