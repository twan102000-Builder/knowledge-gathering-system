import re
import hashlib
from typing import Tuple, Dict, Any

class ContentClassifier:
    URL_REGEX = re.compile(
        r'^(https?:\/\/)?'  # http:// or https://
        r'(([a-zA-Z0-9_\-]+\.)+[a-zA-Z]{2,63})'  # domain
        r'(:\d+)?(\/[^\s]*)?$', re.IGNORECASE
    )

    CODE_INDICATORS = [
        "def ", "class ", "import ", "function", "const ", "let ", "var ",
        "SELECT ", "FROM ", "WHERE ", "public class", "void ", "#include <",
        "curl -", "sudo ", "git ", "npm "
    ]

    @staticmethod
    def compute_hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @classmethod
    def classify_text(cls, text: str) -> Tuple[str, str, Dict[str, Any]]:
        """
        Returns (category, suggested_title, metadata)
        Categories: 'url', 'code', 'text'
        """
        stripped = text.strip()
        lines = stripped.splitlines()
        first_line = lines[0] if lines else ""

        # Check URL
        if len(lines) == 1 and cls.URL_REGEX.match(stripped):
            title = f"Link: {stripped[:50]}"
            return "url", title, {"url": stripped}

        # Check Code
        is_code = False
        detected_hint = None
        if len(lines) > 1:
            for ind in cls.CODE_INDICATORS:
                if any(ind in l for l in lines[:5]):
                    is_code = True
                    detected_hint = ind.strip()
                    break

        if is_code:
            title = f"Code snippet ({detected_hint or 'script'})"
            return "code", title, {"lines_count": len(lines), "detected_hint": detected_hint}

        # General Text / Note
        title = first_line[:50] if first_line else "Snippet"
        return "text", title, {"char_count": len(stripped), "lines_count": len(lines)}
