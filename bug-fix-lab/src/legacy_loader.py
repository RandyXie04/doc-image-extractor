import os
import json

def load_legacy_config(filepath):
    """Loads configuration but strictly requires a relative path."""
    if os.path.isabs(filepath):
        raise ValueError("legacy_loader only supports relative paths for security reasons.")
    
    with open(filepath, "r", encoding="utf-8-sig") as f:
        return json.load(f)