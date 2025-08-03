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
- Select audio input device: microphone/line-in
- Configurable key mapping via GUI.
- Cross-platform GUI

## Download

Pre‑built binaries for **Linux** and **Windows** are available on the
[GitHub Releases](https://github.com/lewis-morris/audiokeys/releases) page.
No compilation or build tools are required.

## Usage

1. Download the release for your platform and extract the archive.
2. Run the executable:
   - **Linux:** `./audiokeys`
   - **Windows:** double‑click `audiokeys.exe`
3. Choose an **Audio Input** from the toolbar. Any audio input
   device can be used.
4. Click **View / Edit Key Mapping** to create a mappings:
   - Click 'Add Key Mapping' to add a new keystroke mapping to a sound.
   - Select the keyboard key to press when the sound is detected.
   - Give the sound a descriptive name i.e 'guitar C4' or 'dog bark'.
   - Record samples (in app) of the sound you want to use **The more samples the better**  
   - Repeat for each keyboard key you want to control.  

5. Click **Start Listening**. When a recorded sound is heard, AudioKeys sends
   the mapped key press and logs the detection.
6. Click **Stop Listening** to finish.

## Configuration & Persistence

The menu bar **Settings >> Audio Parameters** allows you to tweak the 
detection settings and sensitivity if your results are suboptimal.

You can adjust the following parameters:

- **Sample Rate**: The frequency at which audio samples are captured.
- **Buffer Size**: The size of the audio buffer used for processing.
- **Noise Gate Margin**: Threshold to ignore background noise.
- **Matching Algorithm**: Choose between different algorithms for sound matching.
- **Match Threshold**: Sensitivity for detecting matches.
- **High-Pass Filter Cutoff**: Frequency below which audio is filtered out.

All settings, along with recorded samples, key mappings and the last used 
audio device are saved automatically between sessions.

## Troubleshooting

- **Permissions on Linux:** You may need to set up access to the uinput device (e.g., add your user to the `uinput` group or run with `sudo`).
- **No Key Events Sent:** Check the output log for backend errors or import issues.
- **Windows Backend:** Ensure you have the necessary permissions and `pynput` is installed.


## License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.

## Authors

- **Lewis Morris (Arched dev)** – [GitHub](https://github.com/lewis-morris)