import getpass
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterable


def elevate_and_setup_uinput():
    user = getpass.getuser()
    script = f"""#!/bin/bash
set -e
# Ensure the uinput kernel module is loaded so /dev/uinput exists
if ! lsmod | grep -q '^uinput'; then
    modprobe uinput || true
fi
# Install a udev rule to assign the uinput device to the 'input' group with
# world‑writable permissions.  Without this rule the node defaults to 0600.
echo 'KERNEL=="uinput", MODE="0660", GROUP="input"' > /etc/udev/rules.d/99-uinput.rules
udevadm control --reload-rules
udevadm trigger

# Create the input group if missing and add the current user to it.  Although
# membership will only take effect on the next login, the rule above will
# make the node world writable immediately.
getent group input >/dev/null || groupadd input
usermod -aG input {user}

# Relax permissions on the existing device node so that the current session
# can access it without having to re-login.  On systems with strict security
# policies this may not persist across reboots, but it avoids forcing users
# to reboot right now.
chmod 666 /dev/uinput 2>/dev/null || true
"""
    # Write to a temp file
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        f.write(script)
        tmpfile = f.name
    os.chmod(tmpfile, 0o755)

    # Run it all at once with pkexec
    try:
        subprocess.check_call(["pkexec", tmpfile])
    finally:
        os.unlink(tmpfile)

    print(
        "\nSetup complete!\n"
        "You can now use the app without logging out. "
        "However, after a reboot you may need to run this setup again "
        "unless the udev rule and group membership are effective."
    )


def resource_path(relative_path: str) -> str:
    """
    Get absolute path to resource, works for dev and for PyInstaller.

    Args:
        relative_path (str): Relative path to the resource.
    Returns:
        str: Absolute path to the resource.
    """
    if getattr(sys, "frozen", False):
        # PyInstaller places extracted files in _MEIPASS
        base_path = getattr(sys, "_MEIPASS")
    else:
        # running in a normal Python environment
        base_path = os.path.abspath(os.path.dirname(__file__))

    return os.path.join(base_path, relative_path)


def generate_sample_id(base: str, existing: Iterable[str]) -> str:
    """Return a unique sample identifier.

    The identifier takes the form ``"{base}_{n}"`` where ``n`` is the lowest
    positive integer that does not collide with ``existing``.

    Parameters
    ----------
    base:
        Base name provided by the user, e.g. ``"tap"``.
    existing:
        Collection of identifiers already in use.

    Returns
    -------
    str
        A unique identifier incorporating ``base``.
    """

    # Ensure the base is safe for filenames by stripping whitespace and
    # replacing internal spaces with underscores.  This keeps saved ``.npy``
    # files consistent across platforms.
    safe_base = base.strip().replace(" ", "_") or "sample"
    index = 1
    candidate = f"{safe_base}_{index}"
    existing_set = set(existing)
    while candidate in existing_set:
        index += 1
        candidate = f"{safe_base}_{index}"
    return candidate


__all__ = ["elevate_and_setup_uinput", "resource_path", "generate_sample_id"]
