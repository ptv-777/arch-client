import re
from pathlib import Path

_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def safe_download_filename(filename: str, fallback: str = "study.pkg") -> str:
    """Convert an untrusted Content-Disposition filename to one local name."""
    def clean(value: str) -> str:
        normalized = (value or "").replace("\\", "/")
        local_name = Path(normalized).name.strip().rstrip(". ")
        return re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", local_name)

    candidate = clean(filename)
    if not candidate or candidate in {".", ".."}:
        candidate = clean(fallback) or "study.pkg"
    if Path(candidate).stem.upper() in _WINDOWS_RESERVED_NAMES:
        candidate = f"_{candidate}"
    return candidate[:200]
