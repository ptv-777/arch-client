
import re
import unicodedata

def normalize_name(name: str) -> str:
    if not name:
        return ""
    s = str(name).replace("^", " ")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s
