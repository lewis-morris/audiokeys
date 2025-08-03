"""Audio worker for matching recorded sound samples."""

from __future__ import annotations

import gc
import threading
from collections import deque
from typing import Mapping, MutableMapping, Optional
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
    SAMPLE_RATE,
)
from .sample_matcher import match_sample
from .noise_gate import AdaptiveNoiseGate


class SoundWorker(QtCore.QThread):
    """Capture audio and match blocks against stored samples."""

    keyDetected = QtCore.Signal(str)
    amplitudeChanged = QtCore.Signal(float)

    def __init__(
        self,
        device_index: int,
        samples: MutableMapping[str, np.ndarray],
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
        match_threshold: float = 0.8,
        send_enabled: bool = True,
        min_press_interval: float = 0.25,
    ) -> None:
        super().__init__(parent)
        self.device_index = device_index
        self.samples = samples
        self.note_map = note_map
        self.channels = channels
        self.sample_rate = sample_rate
        self.buffer_size = buffer_size
        self.hop_size = hop_size
        self.match_threshold = match_threshold
        self.min_press_interval = min_press_interval
        self._last_emit = 0.0
        self._stop_event = threading.Event()
        self.stream: Optional[sd.InputStream] = None
        self.buffer: deque[np.ndarray] = deque()
        self.noise_gate = AdaptiveNoiseGate(
            duration=noise_gate_duration,
            margin=noise_gate_margin,
            sample_rate=sample_rate,
            hop_size=hop_size,
        )
        self.sender = KeySender(self.note_map, send_enabled=send_enabled)
        self.hp_sos = butter(2, hp_cutoff, "hp", fs=sample_rate, output="sos")
        self.hp_zi = sosfilt_zi(self.hp_sos)

    # --------------------------------------------------------------
    def _process_segment(self) -> None:
        if not self.buffer:
            return
        segment = np.concatenate(list(self.buffer))
        self.buffer.clear()
        key = match_sample(segment, self.samples, threshold=self.match_threshold)
        if key is not None:
            now = time.time()
            if now - self._last_emit >= self.min_press_interval:
                self.sender.press(key)
                self.keyDetected.emit(key)
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
                    self._process_segment()
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
                sd.sleep(100)
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
