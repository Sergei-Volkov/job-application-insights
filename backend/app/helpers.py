from datetime import datetime
import re


def summarize_process_output(text: str, max_chars: int) -> str:
    text = text.strip()
    if not text:
        return ""
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text

    marker = "\n\n... output truncated ...\n\n"
    if max_chars <= len(marker) + 2:
        return text[:max_chars]

    visible = max_chars - len(marker)
    head = visible // 2
    tail = visible - head
    return f"{text[:head]}{marker}{text[-tail:]}"


def slugify(value: str, max_len: int = 80, fallback: str = "item") -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.strip().lower()).strip("_")
    return slug[:max_len] or fallback


def today_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")
