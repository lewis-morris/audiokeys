"""
KeySender — dispatch musical events to the operating system.

This module encapsulates the logic for mapping detected notes to key
presses and releases.  The class attempts to use the Linux ``uinput``
backend for low‑level input synthesis; if that fails (for example on
non‑Linux platforms) it falls back to ``pynput``.  If both backends
are unavailable the class prints messages to standard output instead
of sending keystrokes.

Moving the key‑sending logic into its own module isolates the
dependencies and makes the code easier to test independently of the
GUI and audio capture logic.
"""

from __future__ import annotations

from typing import Mapping, Optional

from PySide6.QtWidgets import QMessageBox

"""
Key event dispatch module for AudioKeys.

This module encapsulates the logic for translating note names into
keystrokes on the underlying operating system.  It attempts to use
the Linux ``uinput`` backend when available, falling back to
``pynput`` on other platforms.  The helper functions for setting up
uinput are imported conditionally so that the module can run both
inside the ``audiokeys`` package and when executed directly from
source.
"""

# Attempt to import helper functions from the installed package.  When
# AudioKeys is not installed (e.g. during development), fall back to
# sibling modules in the same directory.
try:
    from audiokeys.utils import elevate_and_setup_uinput, resource_path  # type: ignore
except Exception:
    from utils import elevate_and_setup_uinput, resource_path  # type: ignore


class KeySender:
    """
    Dispatches note events to the operating system as key presses.

    The user can map notes to arbitrary key names via the GUI.  During
    initialisation we attempt to use the python‑uinput backend on
    Linux to synthesise low‑level input events.  If that fails or the
    module is not installed, we fall back to using pynput to send
    higher level key events.  When neither backend is available the
    class logs the intended key events to the console.

    The mapping supports single characters (e.g. ``"a"`` or ``"1"``) as
    well as special names such as ``"space"``, ``"enter"``, ``"tab"`` and
    function keys ``"f1"`` … ``"f12"``.  Unknown names are silently
    ignored.
    """

    # Mapping of friendly key names to (uinput constant name, pynput key)
    _SPECIAL_KEYS: dict[str, tuple[str, str]] = {
        "space": ("KEY_SPACE", "space"),
        "enter": ("KEY_ENTER", "enter"),
        "return": ("KEY_ENTER", "enter"),
        "tab": ("KEY_TAB", "tab"),
        "esc": ("KEY_ESC", "esc"),
        "escape": ("KEY_ESC", "esc"),
        "left": ("KEY_LEFT", "left"),
        "right": ("KEY_RIGHT", "right"),
        "up": ("KEY_UP", "up"),
        "down": ("KEY_DOWN", "down"),
        "home": ("KEY_HOME", "home"),
        "end": ("KEY_END", "end"),
        "pageup": ("KEY_PAGEUP", "page_up"),
        "pagedown": ("KEY_PAGEDOWN", "page_down"),
        "backspace": ("KEY_BACKSPACE", "backspace"),
        "delete": ("KEY_DELETE", "delete"),
        "capslock": ("KEY_CAPSLOCK", "caps_lock"),
    }
    # Add function keys f1..f12
    for i in range(1, 13):
        name = f"f{i}"
        _SPECIAL_KEYS[name] = (f"KEY_F{i}", name)

    def __init__(self, note_map: Mapping[str, str], send_enabled: bool = True) -> None:
        """
        Initialise the key sender.

        Parameters
        ----------
        note_map : Mapping[str, str]
            A mapping from note names (e.g. ``"C#"``) to friendly key
            names (e.g. ``"space"`` or ``"f1"``).  Keys that cannot be
            resolved are silently ignored.
        send_enabled : bool, optional
            When ``False`` the sender will not emit any key events.  This
            can be used for "Test Listening" modes where notes are
            detected and logged but no keystrokes should be sent.  The
            default is ``True``.
        """
        self.note_map = note_map  # note → key name
        # When send_enabled is False, suppress all key presses/releases.
        self.send_enabled: bool = send_enabled
        self.backend: str = "none"
        # Attempt to import uinput.  On non-Linux platforms this will raise
        # ImportError immediately.
        try:
            import uinput  # type: ignore
        except ImportError:
            # No uinput installed → fallback to pynput
            self._setup_pynput("python-uinput not found, falling back to pynput")
            return

        # Determine which keys we need to support.  For each mapping value we
        # attempt to resolve a uinput code via _to_uinput_code().  If nothing
        # resolves we ignore that entry.  If at least one valid code exists we
        # build the device with those codes.  When none are found we fall
        # back to letters so that the device opens and the user still sees
        # output.
        requested_codes: set[int] = set()
        for key_name in note_map.values():
            code = self._to_uinput_code(key_name)
            if code is not None:
                requested_codes.add(code)

        # Always include the alphabet so that missing mappings don’t break
        # device creation and to support legacy one‑character mappings.
        for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            try:
                requested_codes.add(getattr(uinput, f"KEY_{c}"))
            except Exception:
                pass

        # If we still have no codes (unlikely), fall back to default letter set
        if not requested_codes:
            requested_codes = {getattr(uinput, f"KEY_{c}") for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"}

        # Attempt to open the uinput device
        try:
            self.dev = uinput.Device(list(requested_codes), name="PitchKey")
            self.backend = "uinput"
        except PermissionError:
            # Ask user to elevate / install udev rule
            QMessageBox.warning(
                None,
                "Elevated Privileges Required",
                "Cannot open /dev/uinput—\n"
                "you need permission to access the uinput device.\n\n"
                "Audiokeys will attempt to configure your system now."
            )
            # Our helper to write the udev rule, reload rules, add group, etc.
            elevate_and_setup_uinput()
            # Retry opening uinput
            try:
                self.dev = uinput.Device(list(requested_codes), name="PitchKey")
                self.backend = "uinput"
            except Exception as e:
                # Still failed → fallback
                self._setup_pynput(f"uinput setup failed ({e}), falling back to pynput")

    def _setup_pynput(self, reason: str) -> None:
        """Fallback to pynput if uinput isn’t available or fails."""
        print(f"⚠️  {reason}")
        try:
            from pynput.keyboard import Controller  # type: ignore
            self.ctrl = Controller()
            self.backend = "pynput"
        except ImportError:
            self.backend = "none"
            print("⚠️  pynput not available; keystrokes will only be logged.")

    # ------------------------------------------------------------------
    def _to_uinput_code(self, name: str) -> Optional[int]:
        """
        Convert a friendly key name into a uinput event code.  Returns
        ``None`` if the name cannot be resolved.  For single characters
        this simply returns the corresponding ``KEY_<char>`` constant.  For
        recognised special names a predefined mapping is used.
        """
        try:
            import uinput  # type: ignore
        except ImportError:
            return None

        if not name:
            return None
        name = name.lower()
        # Single alphanumeric character → KEY_A, KEY_1, etc.
        if len(name) == 1 and name.isprintable():
            ch = name
            if ch.isalpha() or ch.isdigit():
                const_name = f"KEY_{ch.upper()}"
                return getattr(uinput, const_name, None)
        # Special mapping
        if name in self._SPECIAL_KEYS:
            const_name, _ = self._SPECIAL_KEYS[name]
            return getattr(uinput, const_name, None)
        return None

    def _to_pynput_key(self, name: str):
        """
        Convert a friendly key name into a pynput key representation.  If
        the name is a single printable character, it is returned as that
        character.  If it is a recognised special name, the corresponding
        ``pynput.keyboard.Key`` member is returned.  Otherwise ``None``.
        """
        if not name:
            return None
        try:
            from pynput.keyboard import Key  # type: ignore
        except ImportError:
            return None
        name = name.lower()
        # Single printable → return char directly
        if len(name) == 1 and name.isprintable():
            return name
        # Special mapping
        if name in self._SPECIAL_KEYS:
            _, pynput_name = self._SPECIAL_KEYS[name]
            # Pynput uses Key.<attribute> or key names for function keys
            # For arrow keys and named keys the attribute matches the mapping
            try:
                return getattr(Key, pynput_name)
            except AttributeError:
                # For function keys Key.f1 etc.
                return getattr(Key, pynput_name, None)
        return None

    # — internal —
    def _linux_emit(self, key_name: str, value: int) -> None:
        """Send a key event via uinput.  ``value`` is 1 for press, 0 for release."""
        if self.backend != "uinput":
            return
        code = self._to_uinput_code(key_name)
        if code is not None:
            try:
                self.dev.emit(code, value)
            except Exception:
                pass

    # — public —
    def press(self, note: str) -> None:
        key_name = self.note_map.get(note, "")
        if not key_name:
            return
        # If sending is disabled (e.g. test mode) bail out early.
        if not getattr(self, "send_enabled", True):
            return
        if self.backend == "uinput":
            self._linux_emit(key_name, 1)
        elif self.backend == "pynput":
            key = self._to_pynput_key(key_name)
            if key is not None:
                try:
                    self.ctrl.press(key)
                except Exception:
                    pass
        else:
            # Fallback: simply log the intended key press.  When send_enabled
            # is False this path is intentionally never reached because of
            # the early return above.
            print(f"[press] {key_name}")

    def release(self, note: str) -> None:
        key_name = self.note_map.get(note, "")
        if not key_name:
            return
        # If sending is disabled (e.g. test mode) bail out early.
        if not getattr(self, "send_enabled", True):
            return
        if self.backend == "uinput":
            self._linux_emit(key_name, 0)
        elif self.backend == "pynput":
            key = self._to_pynput_key(key_name)
            if key is not None:
                try:
                    self.ctrl.release(key)
                except Exception:
                    pass
        else:
            # Fallback: simply log the intended key release.  When
            # send_enabled is False this path is never reached because of
            # the early return above.
            print(f"[release] {key_name}")

    # ------------------------------------------------------------------
    def set_send_enabled(self, enabled: bool) -> None:
        """
        Enable or disable key event sending.

        When ``enabled`` is ``False`` the ``press`` and ``release``
        methods become no‑ops.  Use this to toggle test listening
        without needing to replace the ``KeySender`` entirely.
        """
        self.send_enabled = bool(enabled)


__all__ = ["KeySender"]