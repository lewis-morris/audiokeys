# AudioKeys

**Version 0.1.0**

AudioKeys transforms short audio snippets into keyboard input. The application
listens to your selected audio source, compares what it hears against
user‑recorded samples and presses the associated key whenever a match is
detected.

## Features

- Record custom sound samples and map them to single-character keypresses.
- Assign multiple samples to the same key for more robust matching.
- Support for **Linux** (uinput) and **Windows** (pynput) keyboard backends.
- Select audio input device: microphone/line-in or system audio output (loopback/monitor).
- Configurable key mapping via GUI.
- Choose between waveform, MFCC or DTW matching algorithms.
- Live log of detected sounds.
- Cross-platform GUI built with **PySide6**.

## Download

Pre‑built binaries for **Linux** and **Windows** are available on the
[GitHub Releases](https://github.com/lewis-morris/audiokeys/releases) page.
No compilation or build tools are required.

## Usage

1. Download the release for your platform and extract the archive.
2. Run the executable:
   - **Linux:** `./audiokeys`
   - **Windows:** double‑click `audiokeys.exe`
3. Choose an **Audio Input** from the toolbar. Any microphone or loopback
   device can be used.
4. Click **Add Key Mapping** to create a mapping:
   - Record **five to ten samples** of the sound you want to use.
   - Give the sound a descriptive name.
   - Select the keyboard key to press when the sound is detected.
   Repeat for each key you want to control.
5. Open **Settings** to adjust detection parameters such as sample rate,
   buffer size, noise gate margin, matching algorithm, match threshold and
   high‑pass filter cutoff. These controls help tune sensitivity for your
   environment.
6. Click **Start Listening**. When a recorded sound is heard, AudioKeys sends
   the mapped key press and logs the detection.
7. Click **Stop Listening** to finish.

## Configuration Persistence

Recorded samples, key mappings and the last used audio device are saved
automatically between sessions.

## Troubleshooting

- **Permissions on Linux:** You may need to set up access to the uinput device (e.g., add your user to the `uinput` group or run with `sudo`).
- **No Key Events Sent:** Check the output log for backend errors or import issues.
- **Windows Backend:** Ensure you have the necessary permissions and `pynput` is installed.


## License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.

## Authors

- **Lewis Morris (Arched dev)** – [GitHub](https://github.com/lewis-morris)