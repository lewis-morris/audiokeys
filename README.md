# audiokeys

**Version 0.1.0**

AudioKeys transforms any sound into a versatile input device by listening to
your chosen audio source and matching it against user‑recorded samples. When a
match is found the corresponding keyboard key is pressed.

## Features

- Record custom sound samples and map them to single-character keypresses.
- Assign multiple samples to the same key for more robust matching.
- Support for **Linux** (uinput) and **Windows** (pynput) keyboard backends.
- Select audio input device: microphone/line-in or system audio output (loopback/monitor).
- Configurable key mapping via GUI.
- Live log of detected sounds.
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

1. Launch **AudioKeys**.
2. Click **Add Key Mapping** to record a sample. Recording stops automatically
   when silence is detected. Choose the keyboard key to associate with the
   sound. Repeat to add more samples or variations for the same key.
3. **Audio Input Device:** Choose between microphone/line-in or system output.
4. **Audio Device:** Select the specific audio device from the dropdown.
5. Click **Start Listening** to begin matching sounds. Matches will send
   keystrokes and appear in the log.
6. Click **Stop Listening** to end.

## Configuration Persistence

Your recorded samples, key mappings and last-used audio device are saved
automatically between sessions.

## Troubleshooting

- **Permissions on Linux:** You may need to set up access to the uinput device (e.g., add your user to the `uinput` group or run with `sudo`).
- **No Key Events Sent:** Check the output log for backend errors or import issues.
- **Windows Backend:** Ensure you have the necessary permissions and `pynput` is installed.


## License

MIT License – see [LICENSE](https://github.com/lewis-morris/audiokeys/blob/main/LICENSE) for details.

## Authors

- **Lewis Morris (Arched dev)** – [GitHub](https://github.com/lewis-morris)