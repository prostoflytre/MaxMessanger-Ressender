"""Environment-controlled logging helpers for the Max resender."""

import os
from dotenv import load_dotenv
load_dotenv()
def debug_log(debug_mes: str) -> None:
    """Print a diagnostic message when Max debug mode is enabled."""
    enabled = os.getenv("MAX_DEBUG", "false").lower() in {"1", "true", "yes"}
    if enabled:
        print(f"[MaxRessend] {debug_mes}")

def debug_channels() -> bool:
    """Return whether debug-specific Redis channels should be used."""
    enabled = os.getenv("MAX_DEBUG", "false").lower() in {"1", "true", "yes"}
    if enabled:
        return True
    return False