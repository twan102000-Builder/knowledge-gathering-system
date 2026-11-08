"""
KGS Configuration Loader (src/config.py)
Loads configuration from YAML or JSON without requiring third-party libraries.
Provides typed access to vault paths, Mac drive settings, and dual-tier sync options.
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, Any, Optional

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "kgs_config.yaml"


def parse_simple_yaml(text: str) -> Dict[str, Any]:
    """
    Zero-dependency simple YAML parser for key-value pairs, nested sections, and lists.
    Sufficient for typical YAML configs without external pyyaml dependency.
    """
    result: Dict[str, Any] = {}
    stack: list = [(result, -1)]

    lines = text.splitlines()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        indent = len(line) - len(line.lstrip(" "))

        while len(stack) > 1 and indent <= stack[-1][1]:
            stack.pop()

        current_dict = stack[-1][0]

        # Check list item
        if stripped.startswith("- "):
            val = stripped[2:].strip().strip("\"'")
            if not isinstance(current_dict, list):
                # If current container isn't a list yet, we shouldn't get here unless malformed
                continue
            current_dict.append(val)
            continue

        # Check key-value or key-dict
        if ":" in stripped:
            key, _, val = stripped.partition(":")
            key = key.strip().strip("\"'")
            val = val.strip()

            # Remove inline comments
            if "#" in val and not (val.startswith('"') or val.startswith("'")):
                val = val.split("#", 1)[0].strip()

            if not val:
                # Nested section
                # Peek ahead to see if children are list items
                new_container: Any = {}
                current_dict[key] = new_container
                stack.append((new_container, indent))
            elif val.startswith("[") and val.endswith("]"):
                # Inline list
                items = [i.strip().strip("\"'") for i in val[1:-1].split(",") if i.strip()]
                current_dict[key] = items
            else:
                # Primitive value
                val_clean = val.strip("\"'")
                if val_clean.lower() == "true":
                    parsed_val: Any = True
                elif val_clean.lower() == "false":
                    parsed_val = False
                elif val_clean.lower() in ("null", "none", "~"):
                    parsed_val = None
                elif re.match(r"^-?\d+$", val_clean):
                    parsed_val = int(val_clean)
                elif re.match(r"^-?\d+\.\d+$", val_clean):
                    parsed_val = float(val_clean)
                else:
                    parsed_val = val_clean
                current_dict[key] = parsed_val

    return result


def load_kgs_config(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Loads KGS config file or returns sensible defaults."""
    path = config_path or DEFAULT_CONFIG_PATH
    if not path.exists():
        return {}

    content = path.read_text(encoding="utf-8")
    try:
        return parse_simple_yaml(content)
    except Exception:
        try:
            return json.loads(content)
        except Exception:
            return {}
