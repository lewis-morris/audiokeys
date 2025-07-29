# audiokeys

**Version 0.1.0**

PianoKeyboard transforms any instrument into a versatile input device by listening to your chosen
audio source, detecting each played note in real time, and instantly translating it into a keystroke.

## Features

- Real-time pitch detection using **aubio**.
- Map each note in an octive to single-character keypresses.
- Support for **Linux** (uinput) and **Windows** (pynput) keyboard backends.
- Select audio input device: microphone/line-in or system audio output (loopback/monitor).
- Configurable key mapping via GUI.
- Live log of detected and released notes.
- Cross-platform GUI built with **PySide6**.

## Download

Pre-built releases for Linux and Windows are available on the [GitHub Releases](https://github.com/lewis-morris/audiokeys/releases) page.

## Quick Start

1. Download the appropriate release for your platform.
2. Extract the archive.
3. Run the executable:
   - **Linux:** `./audiokeys`
   - **Windows:** double-click `audiokeys.exe`

## Usage

1. Launch **PianoKeyboard**.
2. **Key Mapping:** Edit the single-character mappings for each note using the grid.
3. **Audio Input Device:** Choose between microphone/line-in or system output.
4. **Audio Device:** Select the specific audio device from the dropdown.
5. Click **Start Listening** to begin detecting notes. Detected notes will send keystrokes and appear in the log.
6. Click **Stop Listening** to end.
7. Use **Calibrate Selected Device** in Settings to measure background noise and
   optionally run pitch calibration for more reliable note detection.

## Configuration Persistence

Your key mappings and last-used audio device are saved automatically between sessions.

## Troubleshooting

- **Permissions on Linux:** You may need to set up access to the uinput device (e.g., add your user to the `uinput` group or run with `sudo`).
- **No Key Events Sent:** Check the output log for backend errors or import issues.
- **Windows Backend:** Ensure you have the necessary permissions and `pynput` is installed.


## License

MIT License – see [LICENSE](https://github.com/lewis-morris/audiokeys/blob/main/LICENSE) for details.

## Authors

- **Lewis Morris (Arched dev)** – [GitHub](https://github.com/lewis-morris)