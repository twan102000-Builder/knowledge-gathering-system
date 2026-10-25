import subprocess
import shutil
from typing import Optional, Tuple

class ClipboardBackend:
    def __init__(self):
        self.wayland_available = shutil.which("wl-paste") is not None
        self.x11_available = shutil.which("xclip") is not None

    def get_text(self) -> Optional[str]:
        # Try Wayland
        if self.wayland_available:
            try:
                res = subprocess.run(
                    ["wl-paste", "--no-newline"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=2
                )
                if res.returncode == 0 and res.stdout:
                    return res.stdout
            except Exception:
                pass

        # Fallback to X11
        if self.x11_available:
            try:
                res = subprocess.run(
                    ["xclip", "-selection", "clipboard", "-o"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=2
                )
                if res.returncode == 0 and res.stdout:
                    return res.stdout
            except Exception:
                pass

        return None

    def get_image(self) -> Optional[Tuple[bytes, str]]:
        """
        Returns (image_bytes, format_ext) e.g. (b'...', 'png') if image in clipboard
        """
        if self.wayland_available:
            try:
                res = subprocess.run(
                    ["wl-paste", "--type", "image/png"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    timeout=3
                )
                if res.returncode == 0 and res.stdout:
                    return res.stdout, "png"
            except Exception:
                pass

        if self.x11_available:
            try:
                res = subprocess.run(
                    ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    timeout=3
                )
                if res.returncode == 0 and res.stdout:
                    return res.stdout, "png"
            except Exception:
                pass

        return None
