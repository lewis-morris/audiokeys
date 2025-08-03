"""Audio worker for matching recorded sound samples."""

from __future__ import annotations

import gc
import threading
from collections import deque
from typing import Mapping, MutableMapping, Optional, Sequence
import time

import numpy as np
import sounddevice as sd
from PySide6 import QtCore
from scipy.signal import butter, sosfilt, sosfilt_zi

from .key_sender import KeySender
from .constants import (
    BUFFER_SIZE,
    HOP_SIZE,
    HP_FILTER_CUTOFF,
    NOISE_GATE_CALIBRATION_TIME,
    NOISE_GATE_MARGIN,
    MATCH_THRESHOLD,
    SAMPLE_RATE,
)
from .sample_matcher import DetectionMethod, match_sample
from .noise_gate import AdaptiveNoiseGate


class SoundWorker(QtCore.QThread):
    """Capture audio and match blocks against stored samples."""

    # Emit detected key and similarity score
    keyDetected = QtCore.Signal(str, float)
    amplitudeChanged = QtCore.Signal(float)

    def __init__(
        self,
        device_index: int,
        samples: MutableMapping[str, Sequence[np.ndarray]],
        note_map: Mapping[str, str],
        *,
        channels: int = 1,
        parent: Optional[QtCore.QObject] = None,
        sample_rate: int = SAMPLE_RATE,
        buffer_size: int = BUFFER_SIZE,
        hop_size: int = HOP_SIZE,
        hp_cutoff: float = HP_FILTER_CUTOFF,
        noise_gate_duration: float = NOISE_GATE_CALIBRATION_TIME,
        noise_gate_margin: float = NOISE_GATE_MARGIN,
        preset_noise_floor: Optional[float] = None,
        match_threshold: float = MATCH_THRESHOLD,
        match_method: DetectionMethod = "waveform",
        send_enabled: bool = True,
        min_press_interval: float = 0.25,
    ) -> None:
        """Initialise the worker thread.

        Args:
            device_index: Index of the input device to capture audio from.
            samples: Recorded reference samples grouped by identifier.
            note_map: Mapping from sample identifier to keyboard key.
            channels: Number of audio channels.
            parent: Optional Qt parent.
            sample_rate: Sampling frequency of the audio stream.
            buffer_size: Number of samples per processing buffer.
            hop_size: Hop size for overlapping windows.
            hp_cutoff: High-pass filter cutoff frequency.
            noise_gate_duration: Duration used to calibrate the noise gate.
            noise_gate_margin: Margin applied to the noise floor.
            preset_noise_floor: Pre-calibrated noise floor if available.
            match_threshold: Minimum similarity score for detection.
            match_method: Technique for comparing audio segments.
            send_enabled: Whether key presses should be emitted.
            min_press_interval: Minimum time between successive key events.
        """
        super().__init__(parent)
        self.device_index = device_index
        self.samples = samples
        self.note_map = note_map
        self.channels = channels
        self.sample_rate = sample_rate
        self.buffer_size = buffer_size
        self.hop_size = hop_size
        self.match_threshold = match_threshold
        self.match_method = match_method
        self.min_press_interval = min_press_interval
        self._last_emit = 0.0
        self._stop_event = threading.Event()
        self.stream: Optional[sd.InputStream] = None
        self.buffer: deque[np.ndarray] = deque()
        # Queue of captured segments awaiting matching.  Heavy matching
        # operations are processed outside the audio callback to avoid GUI
        # hangs, especially when using MFCC or DTW methods.
        self.segments: deque[np.ndarray] = deque()
        self.noise_gate = AdaptiveNoiseGate(
            duration=noise_gate_duration,
            margin=noise_gate_margin,
            sample_rate=sample_rate,
            hop_size=hop_size,
            preset_noise_floor=preset_noise_floor,
        )
        self.sender = KeySender(self.note_map, send_enabled=send_enabled)
        self.hp_sos = butter(2, hp_cutoff, "hp", fs=sample_rate, output="sos")
        self.hp_zi = sosfilt_zi(self.hp_sos)

    # --------------------------------------------------------------
    def _process_segment(self, segment: np.ndarray) -> None:
        """Match a captured ``segment`` against reference samples."""

        key, score = match_sample(
            segment,
            self.samples,
            threshold=self.match_threshold,
            method=self.match_method,
            sample_rate=self.sample_rate,
        )
        if key is not None:
            now = time.time()
            if now - self._last_emit >= self.min_press_interval:
                self.sender.press(key)
                self.keyDetected.emit(key, score)
                self.sender.release(key)
                self._last_emit = now

    # --------------------------------------------------------------
    def _callback(self, indata, frames, _time, status) -> None:  # noqa: D401
        if status:
            print(f"⚠️  {status}")
        try:
            if indata.ndim == 2 and indata.shape[1] > 1:
                samples = indata.mean(axis=1).astype(np.float32)
            else:
                samples = indata.reshape(-1).astype(np.float32)

            samples, self.hp_zi = sosfilt(self.hp_sos, samples, zi=self.hp_zi)
            current_rms = self.noise_gate.update(samples)
            self.amplitudeChanged.emit(current_rms)

            if self.noise_gate.noise_floor is None:
                return

            if self.noise_gate.is_silent(samples):
                if self.buffer:
                    segment = np.concatenate(list(self.buffer))
                    self.segments.append(segment)
                    self.buffer.clear()
                return

            self.buffer.append(samples)
        except Exception:
            pass

    # --------------------------------------------------------------
    def run(self) -> None:  # noqa: D401
        try:
            self.stream = sd.InputStream(
                device=self.device_index,
                channels=self.channels,
                samplerate=self.sample_rate,
                blocksize=self.hop_size,
                dtype="float32",
                callback=self._callback,
            )
            self.stream.start()
            while not self._stop_event.is_set():
                if self.segments:
                    segment = self.segments.popleft()
                    self._process_segment(segment)
                sd.sleep(50)
            if self.stream is not None:
                self.stream.stop()
                self.stream.close()
        except Exception as e:
            print(f"Worker error: {e}")

    def stop(self) -> None:
        if self.stream is not None:
            try:
                self.stream.abort()
            except Exception:
                pass
            try:
                self.stream.close()
            except Exception:
                pass
        self._stop_event.set()
        del self.sender
        gc.collect()
        self.wait(2000)

    def set_send_enabled(self, enabled: bool) -> None:
        if hasattr(self, "sender"):
            self.sender.set_send_enabled(enabled)


__all__ = ["SoundWorker"]
