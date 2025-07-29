"""
AudioWorker — threaded audio capture with adaptive noise gating.

This module defines two classes: ``AdaptiveNoiseGate`` and
``AudioWorker``.  ``AdaptiveNoiseGate`` estimates the ambient noise
floor at the start of a listening session and classifies incoming
frames as silence or signal.  ``AudioWorker`` wraps the lower‑level
sounddevice input stream and aubio pitch detector inside a Qt
``QThread``, emitting signals when notes are detected and released.

The implementation refines the basic noise handling from the original
version by adding a high‑pass filter (to remove low‑frequency rumble)
and adaptive thresholding.  During the first few seconds of
recording the worker gathers RMS measurements of the incoming audio
and computes a median value to establish the noise floor.  This
baseline, multiplied by a safety margin, defines the threshold above
which notes are considered.  The combination of high‑pass filtering
and adaptive gating significantly reduces false triggers in noisy
environments.
"""

from __future__ import annotations

import gc
import threading
from collections import deque
from typing import MutableMapping, Optional, Tuple

import aubio
import numpy as np
import sounddevice as sd
from PySide6 import QtCore
from scipy.signal import butter, sosfilt, sosfilt_zi

"""
Audio processing thread for the AudioKeys application.

This module defines two classes: ``AdaptiveNoiseGate`` and
``AudioWorker``.  Both are reused by the GUI layer to capture
microphone or loopback audio, filter it, apply adaptive noise
gating and perform pitch detection using ``aubio``.  The note
events produced by ``AudioWorker`` are dispatched via the
``KeySender`` class.

Imports from the ``audiokeys`` package are performed conditionally to
support running the module directly (e.g. during development) as well
as when installed as a package.  When the package imports fail, the
module falls back to importing sibling modules from the same
directory.  See ``gui.py`` for similar logic.
"""

# Conditional imports: try the installed package first, fallback to
# relative imports for development.  pylint: disable=wrong-import-order
try:
    from audiokeys.constants import A4_MIDI  # type: ignore
    from audiokeys.constants import (
        A4_FREQ,
        AUBIO_CONFIDENCE_THRESHOLD,
        BUFFER_SIZE,
        HOP_SIZE,
        HP_FILTER_CUTOFF,
        MIDI_SEMITONE_TOLERANCE,
        NOISE_GATE_CALIBRATION_TIME,
        NOISE_GATE_MARGIN,
        NOTE_NAMES,
        SAMPLE_RATE,
    )
    from audiokeys.key_sender import KeySender  # type: ignore
except Exception:
    from constants import A4_MIDI  # type: ignore
    from constants import (
        A4_FREQ,
        AUBIO_CONFIDENCE_THRESHOLD,
        BUFFER_SIZE,
        HOP_SIZE,
        HP_FILTER_CUTOFF,
        MIDI_SEMITONE_TOLERANCE,
        NOISE_GATE_CALIBRATION_TIME,
        NOISE_GATE_MARGIN,
        NOTE_NAMES,
        SAMPLE_RATE,
    )
    from key_sender import KeySender  # type: ignore


class AdaptiveNoiseGate:
    """Adaptive noise gating based on a measured background noise floor.

    This gate samples the incoming audio for a brief calibration period
    to estimate the ambient noise level.  During calibration each audio
    block's root‑mean‑square (RMS) value is recorded.  After the
    specified number of frames have been gathered the median RMS
    becomes the ``noise_floor`` against which subsequent blocks are
    compared.  Any block whose RMS falls below ``noise_floor * margin``
    is considered silent.

    Optionally, a pre‑computed noise floor may be supplied via
    ``preset_noise_floor``.  When provided the gate skips its own
    calibration and uses the preset value immediately.  This can be
    useful when the user has manually calibrated their environment and
    wishes to reuse that value across sessions.

    Args:
        duration: Number of seconds over which to sample ambient noise
            for automatic calibration.  A value of zero or a preset
            noise floor disables calibration.
        margin: Safety multiplier applied to the measured noise floor.
            Larger values make the gate more conservative (less
            sensitive) while smaller values increase sensitivity.
        sample_rate: Audio sampling rate in hertz used to derive
            calibration frame count.
        hop_size: Number of samples per processing hop; determines
            calibration frame length.
        preset_noise_floor: Pre‑computed RMS noise floor to use instead
            of measuring from input.  If provided, calibration is
            skipped and this value becomes ``noise_floor`` immediately.

    Attributes:
        calibration_frames: Total number of blocks to use for noise
            floor estimation.
        margin: Multiplier applied to ``noise_floor`` when testing
            silence.
        noise_floor: Estimated or preset RMS level of background noise
            beneath which blocks are considered silent.  ``None`` until
            calibration completes or preset is supplied.
    """

    def __init__(
        self,
        duration: float = NOISE_GATE_CALIBRATION_TIME,
        margin: float = NOISE_GATE_MARGIN,
        sample_rate: int = SAMPLE_RATE,
        hop_size: int = HOP_SIZE,
        preset_noise_floor: Optional[float] = None,
    ) -> None:
        """Initialise a new AdaptiveNoiseGate.

        Args:
            duration: Seconds of audio to sample during calibration.  If
                set to zero and ``preset_noise_floor`` is not provided
                calibration will still use at least one frame.
            margin: Multiplicative factor applied to the measured noise
                floor when testing for silence.
            sample_rate: Sampling frequency in hertz.
            hop_size: Number of samples per processing block.
            preset_noise_floor: Optional pre‑computed noise floor to
                assign immediately, bypassing calibration.
        """
        # Convert calibration duration (seconds) into a number of frames.
        frames = int((duration * sample_rate) / hop_size)
        self.calibration_frames: int = max(frames, 1)
        self.margin: float = margin
        self.rms_values: list[float] = []
        self.noise_floor: Optional[float] = None
        # If the caller provided a preset noise floor we skip calibration
        if preset_noise_floor is not None:
            # Avoid storing ridiculously small values (e.g. near zero)
            self.noise_floor = max(float(preset_noise_floor), 1e-12)

    def update(self, samples: np.ndarray) -> float:
        """Record the RMS of an audio block and update the noise floor.

        The gate collects RMS measurements of incoming audio until
        ``calibration_frames`` values have been gathered, at which point
        the median is stored as ``noise_floor``.  If a preset noise floor
        was provided at construction, calibration is skipped and calls
        simply compute and return the current block's RMS.

        Args:
            samples: A one‑dimensional array of audio samples.  This
                should already be down‑mixed to mono if the input was
                multi‑channel.

        Returns:
            float: The RMS level of the provided samples.
        """
        rms = float(np.sqrt(np.mean(samples**2)))
        # Only update the noise floor during calibration
        if self.noise_floor is None:
            self.rms_values.append(rms)
            if len(self.rms_values) >= self.calibration_frames:
                # Compute a robust estimate of the noise floor using the median
                median_rms = float(np.median(self.rms_values))
                self.noise_floor = max(median_rms, 1e-12)
        return rms

    def is_silent(self, samples: np.ndarray) -> bool:
        """Test whether an audio block falls below the silence threshold.

        This check returns ``False`` during the calibration phase so as
        not to prematurely treat calibration data as silence.  Once a
        noise floor has been established (either via calibration or a
        preset), the block is considered silent if its RMS level is
        strictly less than ``noise_floor * margin``.

        Args:
            samples: A one‑dimensional array of audio samples (mono).

        Returns:
            bool: ``True`` if the block is below the silence threshold,
            ``False`` otherwise.
        """
        # If calibration has not completed we cannot reliably decide
        if self.noise_floor is None:
            return False
        rms = float(np.sqrt(np.mean(samples**2)))
        return rms < (self.noise_floor * self.margin)


class AudioWorker(QtCore.QThread):
    """Background thread for audio capture, filtering and pitch detection.

    A worker encapsulates a PortAudio input stream along with
    high‑pass filtering, adaptive noise gating and pitch detection.
    Processed audio blocks generate Qt signals for note presses,
    releases and continuous feedback (RMS amplitude and current pitch).

    The pitch detector can operate in multiple modes.  When
    ``detection_method`` is anything other than ``"fft"`` the worker
    uses the :mod:`aubio` library to estimate the fundamental frequency.
    Otherwise a simple FFT peak finder is used to locate the dominant
    spectral frequency.  See ``detection_method`` parameter for
    supported values.

    Args:
        device_index: Index of the PortAudio input device to capture
            audio from.  The selection is provided by the GUI layer.
        note_map: Mapping from note names (e.g. ``"C#"``) to key names.
            The :class:`KeySender` uses this mapping to press and
            release keyboard keys when notes are detected.
        channels: Number of audio channels to capture.  When capturing
            loopback audio on Windows two channels may be required.
        extra_settings: Optional backend‑specific settings passed to
            ``sounddevice.InputStream`` (e.g. ``WasapiSettings`` for
            WASAPI loopback).  ``None`` for default.
        parent: Optional Qt parent object for the thread.
        hp_cutoff: High‑pass filter cutoff frequency in hertz.  Values
            below this are attenuated to remove rumble and mains hum.
        noise_gate_duration: Seconds to sample for automatic noise
            floor estimation.  See :class:`AdaptiveNoiseGate`.
        noise_gate_margin: Multiplier applied to the noise floor when
            determining silence.  Larger values reduce sensitivity.
        midi_tolerance: Tolerance in semitones before a change in
            pitch is interpreted as a new note.  Smaller values
            increase sensitivity but may cause rapid note changes.
        detection_method: Identifier of the pitch detection algorithm.
            ``"aubio"`` (default) selects Aubio's default detector.
            ``"fft"`` selects a simple FFT peak finder.  Other
            Aubio methods (e.g. ``"yin"``, ``"yinfft"``) may also be
            specified and are passed directly to :func:`aubio.pitch`.
        preset_noise_floor: Optional pre‑computed RMS noise floor to
            assign directly to the internal :class:`AdaptiveNoiseGate`.

    Signals:
        noteDetected(str, float): Emitted when a new note is detected.
            Arguments are the note name and fundamental frequency.
        noteReleased(str): Emitted when a previously active note is
            released.
        amplitudeChanged(float): Emitted with the RMS amplitude of
            each processed block.
        pitchChanged(float, str): Emitted continuously with the
            estimated frequency and its nearest note name.
    """

    # Emitted when a note is detected.  Provides the note name and its
    # fundamental frequency in hertz.
    noteDetected = QtCore.Signal(str, float)  # note, frequency
    # Emitted when a previously active note is released.
    noteReleased = QtCore.Signal(str)
    # Continuous feedback: emitted with the current RMS amplitude of each
    # processed block, scaled to [0, 1] by the caller if needed.
    amplitudeChanged = QtCore.Signal(float)
    # Continuous feedback: emitted with the current estimated frequency
    # and corresponding note name on every processed block (when not silent).
    pitchChanged = QtCore.Signal(float, str)

    def __init__(
        self,
        device_index: int,
        note_map: MutableMapping[str, str],
        channels: int = 1,
        extra_settings=None,
        parent: Optional[QtCore.QObject] = None,
        sample_rate: int = SAMPLE_RATE,
        buffer_size: int = BUFFER_SIZE,
        hop_size: int = HOP_SIZE,
        hp_cutoff: float = HP_FILTER_CUTOFF,
        noise_gate_duration: float = NOISE_GATE_CALIBRATION_TIME,
        noise_gate_margin: float = NOISE_GATE_MARGIN,
        midi_tolerance: float = MIDI_SEMITONE_TOLERANCE,
        confidence_threshold: float = AUBIO_CONFIDENCE_THRESHOLD,
        detection_method: str = "aubio",
        preset_noise_floor: Optional[float] = None,
        send_enabled: bool = True,
    ) -> None:
        """Initialise an AudioWorker thread.

        See class docstring for a complete description of the parameters.
        """
        super().__init__(parent)
        self.device_index = device_index
        self.note_map = note_map
        self.channels = channels
        self.extra_settings = extra_settings
        self.sample_rate = sample_rate
        self.buffer_size = buffer_size
        self.hop_size = hop_size
        self._stop_event = threading.Event()
        self.stream: Optional[sd.InputStream] = None

        # Pitch detection setup.  We attempt to create an Aubio pitch
        # detector when detection_method is not 'fft'.  Unknown methods are
        # passed through to aubio and may raise an exception.  If the
        # method is 'fft' we disable aubio and fall back to internal
        # FFT pitch estimation.
        self.detection_method = (
            detection_method.lower().strip() if detection_method else "aubio"
        )
        self.pitch_o = None  # type: Optional[aubio.pitch]
        if self.detection_method != "fft":
            try:
                self.pitch_o = aubio.pitch(
                    method=self.detection_method or "default",
                    buf_size=self.buffer_size,
                    hop_size=self.hop_size,
                    samplerate=self.sample_rate,
                )
                self.pitch_o.set_unit("Hz")
                # A negative silence threshold for aubio means it will not gate
                # our signal; we implement our own gating below
                self.pitch_o.set_silence(-40)
            except Exception:
                # Fallback to default aubio detector on failure
                try:
                    self.pitch_o = aubio.pitch(
                        method="default",
                        buf_size=self.buffer_size,
                        hop_size=self.hop_size,
                        samplerate=self.sample_rate,
                    )
                    self.pitch_o.set_unit("Hz")
                    self.pitch_o.set_silence(-40)
                    self.detection_method = "aubio"
                except Exception:
                    # Unable to configure aubio; revert to FFT detection
                    self.pitch_o = None
                    self.detection_method = "fft"

        # Note sending backend.  The KeySender is initialised with
        # ``send_enabled`` so that test modes can disable key events.
        self.sender = KeySender(self.note_map, send_enabled=send_enabled)

        # Last active note and midi value; used for hysteresis
        self.last_note: Optional[str] = None
        self.last_midi: Optional[float] = None
        self.midi_tolerance: float = midi_tolerance
        self.confidence_threshold: float = confidence_threshold

        # Adaptive noise gate with optional preset
        self.noise_gate = AdaptiveNoiseGate(
            duration=noise_gate_duration,
            margin=noise_gate_margin,
            sample_rate=self.sample_rate,
            hop_size=self.hop_size,
            preset_noise_floor=preset_noise_floor,
        )

        # High‑pass filter design.  Use second‑order sections (SOS) for numerical
        # stability.  The cutoff frequency is normalised against the Nyquist
        # frequency and clamped to a reasonable range.
        nyquist = self.sample_rate / 2.0
        normalised_cutoff = max(min(hp_cutoff / nyquist, 0.99), 0.001)
        self.hp_sos = butter(2, normalised_cutoff, btype="highpass", output="sos")
        # Initialise filter state for streaming processing.  Each SOS has two
        # internal state variables (for a biquad), so the shape is
        # (n_sections, 2).
        self.hp_zi = sosfilt_zi(self.hp_sos)  # type: ignore
        # Maintain a small history of recent pitch estimates for smoothing
        self._freq_history: deque[float] = deque(maxlen=5)

    def _fft_pitch(self, samples: np.ndarray) -> float:
        """Estimate pitch frequency using a simple FFT peak detection.

        The input samples are windowed with a Hann window to reduce
        spectral leakage before performing a real FFT.  The magnitude
        spectrum is scanned for the highest peak within a plausible
        musical frequency range (50 Hz to 2000 Hz).  Frequencies
        outside this range are ignored.  If no suitable peak is
        found, zero is returned to indicate failure.

        Args:
            samples: One‑dimensional array of filtered audio samples.

        Returns:
            float: Estimated fundamental frequency in hertz, or 0.0 if
            no peak is found.
        """
        # Apply a Hann window to reduce edge discontinuities
        window = np.hanning(len(samples))
        s = samples * window
        # Compute the one‑sided FFT and corresponding frequency bins
        spectrum = np.abs(np.fft.rfft(s))
        freqs = np.fft.rfftfreq(len(s), d=1.0 / self.sample_rate)
        # Focus on a realistic range for instrument pitches
        mask = (freqs >= 50.0) & (freqs <= 2000.0)
        if not np.any(mask):
            return 0.0
        # Find index of the maximum magnitude within the masked region
        idx = int(np.argmax(spectrum[mask]))
        freq = float(freqs[mask][idx])
        return freq

    # -----------------------------------------------------------------
    def _callback(
        self, indata: np.ndarray, frames: int, _time: Tuple[int, int], status
    ) -> None:
        """Process a single block of audio in the PortAudio callback.

        This callback is invoked by PortAudio in a separate thread for
        each block of incoming audio.  The function performs the
        following steps:

          * Down‑mix multichannel input to mono.
          * Apply a high‑pass filter to attenuate low‑frequency noise.
          * Update the adaptive noise gate and emit the current RMS via
            :pydata:`amplitudeChanged`.
          * If the block is classified as silent, release any active
            note and return.
          * Estimate the fundamental frequency using either the
            configured Aubio detector or a simple FFT peak finder.
          * Convert the frequency to a MIDI number and determine the
            nearest note.  Emit :pydata:`pitchChanged` continuously
            for visual feedback and send key press/release events via
            the :class:`KeySender` when the note changes beyond the
            specified tolerance.  Recent pitch estimates are averaged to
            smooth out small fluctuations before note decisions are made.

        All exceptions are caught and suppressed to prevent PortAudio
        from shutting down the stream.

        Args:
            indata: The raw audio data provided by PortAudio.  This is
                an array of shape ``(frames, channels)`` or ``(frames,)``
                depending on the number of channels configured.
            frames: Number of frames provided in this callback.  This
                matches the hop size used when opening the stream.
            _time: Tuple of timing information provided by PortAudio.
                Unused in this implementation but retained for API
                compatibility.
            status: A :class:`sounddevice.CallbackFlags` bitmask
                indicating underflow, overflow or other non‑fatal
                conditions.  Warnings are printed to ``stdout`` when
                this value is non‑zero.
        """
        # Avoid performing GUI operations here; only emit signals
        if status:
            # Print XRUN or other errors
            print(f"⚠️  {status}", flush=True)
        try:
            # Down‑mix to mono if necessary
            if indata.ndim == 2 and indata.shape[1] > 1:
                samples = indata.mean(axis=1).astype(np.float32)
            else:
                samples = indata.reshape(-1).astype(np.float32)

            # Apply high‑pass filter to remove low‑frequency noise
            # Use streaming filter with internal state to avoid transient
            samples, self.hp_zi = sosfilt(self.hp_sos, samples, zi=self.hp_zi)

            # Update the noise gate calibration and obtain current rms
            current_rms = self.noise_gate.update(samples)
            # Emit the amplitude (RMS) for the current block.  Clients
            # typically scale this value into a visible range (e.g. 0–1 or 0–100).
            self.amplitudeChanged.emit(current_rms)

            # If gate has not finished calibrating, or the block is below threshold,
            # release any active note and skip pitch detection.
            if self.noise_gate.noise_floor is None or self.noise_gate.is_silent(
                samples
            ):
                if self.last_note is not None:
                    # Release the currently active note
                    self.sender.release(self.last_note)
                    self.noteReleased.emit(self.last_note)
                    self.last_note = None
                    self.last_midi = None
                self._freq_history.clear()
                return

            # Estimate pitch (Hz).
            # For non‑FFT methods we use aubio first and then fall back to
            # the internal FFT peak finder if no frequency is returned.
            freq: float = 0.0
            if self.detection_method != "fft":
                # Guard against pitch_o being None in fallback
                try:
                    if self.pitch_o is not None:
                        freq = float(self.pitch_o(samples)[0])
                        confidence = float(self.pitch_o.get_confidence())
                        if confidence < self.confidence_threshold:
                            freq = 0.0
                except Exception:
                    freq = 0.0
                # If aubio failed to detect a pitch (returns 0),
                # attempt an FFT peak estimate as a fallback.  This
                # improves reliability on systems where aubio may not
                # function correctly or when the chosen aubio method
                # struggles with the incoming signal.
                if freq <= 0.0:
                    freq = self._fft_pitch(samples)
            else:
                # FFT only mode
                freq = self._fft_pitch(samples)

            # If no reliable pitch was found, treat as silence
            if freq <= 0.0:
                if self.last_note is not None:
                    self.sender.release(self.last_note)
                    self.noteReleased.emit(self.last_note)
                    self.last_note = None
                    self.last_midi = None
                self._freq_history.clear()
                return

            # Smooth the frequency by averaging over recent frames
            self._freq_history.append(freq)
            smoothed_freq = float(np.mean(self._freq_history))

            # Convert to MIDI number using the smoothed frequency
            midi = 12.0 * np.log2(smoothed_freq / A4_FREQ) + A4_MIDI

            # Continuous feedback: emit the current frequency and its nearest note
            note_index_for_signal = int(round(midi)) % 12
            note_name_for_signal = NOTE_NAMES[note_index_for_signal]
            self.pitchChanged.emit(smoothed_freq, note_name_for_signal)

            # If the difference from the last MIDI is below tolerance, treat as unchanged
            if (
                self.last_note is not None
                and self.last_midi is not None
                and abs(midi - self.last_midi) < self.midi_tolerance
            ):
                # Gently update last_midi to follow drift
                self.last_midi = midi
                return

            # Otherwise we have a new note.  Release previous note
            if self.last_note is not None:
                self.sender.release(self.last_note)
                self.noteReleased.emit(self.last_note)

            # Round to nearest note name
            note_index = int(round(midi)) % 12
            note_name = NOTE_NAMES[note_index]

            # Send the key press for the new note
            self.sender.press(note_name)
            self.noteDetected.emit(note_name, smoothed_freq)
            self.last_note = note_name
            self.last_midi = midi

        except Exception:
            # Swallow any exceptions to avoid crashing the callback
            pass

    # -----------------------------------------------------------------
    def run(self) -> None:
        """Entry point for the worker thread.

        This method opens a :class:`sounddevice.InputStream` using the
        configured device, channel count and any additional backend
        settings.  The stream invokes :meth:`_callback` for each block
        of audio.  The thread remains alive until :meth:`stop` is
        called, at which point the stream is stopped and closed.
        """
        try:
            self.stream = sd.InputStream(
                device=self.device_index,
                channels=self.channels,
                samplerate=self.sample_rate,
                blocksize=self.hop_size,
                dtype="float32",
                callback=self._callback,
                extra_settings=self.extra_settings,
            )
            self.stream.start()

            # Keep the thread alive until stop() is called
            while not self._stop_event.is_set():
                sd.sleep(100)

            # Once stop_event is set, explicitly tear down the stream
            if self.stream is not None:
                self.stream.stop()
                self.stream.close()

        except Exception as e:
            # Propagate any errors to the GUI via the noteReleased signal
            self.noteReleased.emit(f"ERROR: {e}")

    def stop(self) -> None:
        """Stop the worker thread and release any active note.

        This method is safe to call from any thread, including the
        GUI thread.  It signals the run loop to exit, stops and
        closes the PortAudio stream, releases any currently pressed
        key and tears down internal resources.  The call blocks until
        the worker thread has terminated (up to a short timeout).
        """
        # Release last note if necessary
        if self.last_note is not None:
            self.sender.release(self.last_note)
            self.noteReleased.emit(self.last_note)
            self.last_note = None
            self.last_midi = None

        # Explicitly dispose of the key sender
        del self.sender
        gc.collect()

        # Immediately tear down the PortAudio stream
        if self.stream is not None:
            try:
                self.stream.abort()
            except Exception:
                pass
            try:
                self.stream.close()
            except Exception:
                pass

        # Signal the run loop to exit
        self._stop_event.set()
        # Wait for the thread to finish
        self.wait(2000)

    # -----------------------------------------------------------------
    def set_send_enabled(self, enabled: bool) -> None:
        """
        Enable or disable key presses generated by this worker's sender.

        This method can be invoked from the GUI to toggle between
        regular and test listening modes.  When disabled the
        underlying ``KeySender`` will not emit any key events, but
        enabled : bool
            If ``True``, key events are sent as normal.  If ``False``,
            ``press`` and ``release`` become no‑ops.
        """
        if hasattr(self, "sender"):
            try:
                self.sender.set_send_enabled(enabled)
            except Exception:
                # Ignore errors if sender does not support toggling
                pass


__all__ = ["AdaptiveNoiseGate", "AudioWorker"]
