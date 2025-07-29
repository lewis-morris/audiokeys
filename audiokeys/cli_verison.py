#!/usr/bin/env python3
import numpy as np
import sounddevice as sd
import aubio
import uinput

# ─── CONFIG ────────────────────────────────────────────────────────────────────

SAMPLE_RATE = 44100            # Hz
BUFFER_SIZE = 2048             # samples per frame
HOP_SIZE = BUFFER_SIZE // 4    # hop between frames

A4_FREQ = 440.0                # tuning reference
A4_MIDI = 69

# Map note names to uinput key events
NOTE_TO_UINPUT = {
    "C":  uinput.KEY_A,
    "C#": uinput.KEY_W,
    "D":  uinput.KEY_S,
    "D#": uinput.KEY_D,
    "E":  uinput.KEY_F,
    "F":  uinput.KEY_J,
    "F#": uinput.KEY_K,
    "G":  uinput.KEY_L,
    "G#": uinput.KEY_I,
    "A":  uinput.KEY_O,
    "A#": uinput.KEY_P,
    "B":  uinput.KEY_U
}

# ─── HELPERS ───────────────────────────────────────────────────────────────────

NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F',
              'F#', 'G', 'G#', 'A', 'A#', 'B']

def freq_to_note_name(freq: float) -> str | None:
    """Convert Hz to the nearest 12‑TET note name."""
    if freq <= 0:
        return None
    midi = 12 * np.log2(freq / A4_FREQ) + A4_MIDI
    midi_rounded = int(round(midi))
    return NOTE_NAMES[midi_rounded % 12]

# ─── SET UP PROCESSORS ─────────────────────────────────────────────────────────

# Pitch detector
pitch_o = aubio.pitch(
    method="default",
    buf_size=BUFFER_SIZE,
    hop_size=HOP_SIZE,
    samplerate=SAMPLE_RATE
)
pitch_o.set_unit("Hz")
pitch_o.set_silence(-40)

# Virtual keyboard via uinput
ui = uinput.Device(list(NOTE_TO_UINPUT.values()))

last_note: str | None = None

# ─── CALLBACK ──────────────────────────────────────────────────────────────────

last_note = None

def audio_callback(indata, frames, time, status):
    global last_note
    if status:
        print(f"⚠️  Input status: {status}", flush=True)

    # 1) detect pitch
    samples = indata[:, 0].astype(np.float32)
    freq = pitch_o(samples)[0]
    note = freq_to_note_name(freq)

    # 2) if we’ve lost the note (silence or very quiet) → send key‑up for last_note
    if note is None:
        if last_note is not None:
            ev = NOTE_TO_UINPUT[last_note]
            ui.emit(ev, 0)          # key up
            print(f"Released {last_note}", flush=True)
            last_note = None
        return

    # 3) if it’s the same note still held down → do nothing
    if note == last_note:
        return

    # 4) note changed (or first note)
    #    → release old, press new
    if last_note is not None:
        ev_old = NOTE_TO_UINPUT[last_note]
        ui.emit(ev_old, 0)         # key up
        print(f"Released {last_note}", flush=True)

    ev_new = NOTE_TO_UINPUT.get(note)
    if ev_new:
        ui.emit(ev_new, 1)         # key down
        print(f"Detected {note} ({freq:.1f} Hz) → key down", flush=True)
        last_note = note

# ─── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    # Use PulseAudio’s monitor; record whatever’s playing to your speakers
    DEVICE = 'pulse'
    dev_info = sd.query_devices(DEVICE)
    print(f"Recording from '{DEVICE}' → {dev_info['name']}", flush=True)
    print("Play some audio... (Ctrl+C to quit)", flush=True)

    with sd.InputStream(
        device=DEVICE,
        channels=1,
        samplerate=SAMPLE_RATE,
        blocksize=HOP_SIZE,
        callback=audio_callback,
        dtype='float32',
    ):
        try:
            sd.sleep(int(1e9))
        except KeyboardInterrupt:
            print("\nExiting.", flush=True)

if __name__ == "__main__":
    main()