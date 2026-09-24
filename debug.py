import os
from dotenv import load_dotenv
load_dotenv()
def debug_log(debug_mes: str) -> None:
    enabled = os.getenv("MAX_DEBUG", "false").lower() in {"1", "true", "yes"}
    if enabled:
        print(f"[MaxRessend] {debug_mes}")