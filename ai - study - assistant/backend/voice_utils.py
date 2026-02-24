"""
Voice utilities: clean AI response text for natural TTS (text-to-speech).
Removes markdown and formats content so it sounds like a teacher speaking.
"""
import re


def clean_text_for_voice(text: str) -> str:
    """
    Clean and format text for natural voice output. Removes markdown symbols,
    converts bullet lists into conversational sentences, and adds natural pauses.
    Voice output should sound like a real human tutor explaining, not reading raw text.

    - Removes: *, **, -, #, _, ` (markdown)
    - Converts bullet lists to "X, Y, and Z." style
    - Normalizes whitespace and adds flow for speech
    """
    if not text or not isinstance(text, str):
        return ""

    s = text.strip()
    if not s:
        return ""

    # --- 1. Strip inline code backticks (keep content) ---
    s = re.sub(r"`([^`]+)`", r"\1", s)

    # --- 2. Strip bold ** and * (keep content) ---
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    s = re.sub(r"\*([^*]+)\*", r"\1", s)

    # --- 3. Strip underscore emphasis __ and _ (keep content) ---
    s = re.sub(r"__([^_]+)__", r"\1", s)
    s = re.sub(r"_([^_]+)_", r"\1", s)

    # --- 4. Strip heading markers # ## ### etc. (keep text) ---
    s = re.sub(r"^#{1,6}\s*", "", s, flags=re.MULTILINE)

    # --- 5. Split into lines for bullet/list handling ---
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]

    # Bullet patterns: "- item", "* item", "• item", "1. item", "1) item"
    bullet_pattern = re.compile(
        r"^(\s*[-*•]\s+|\s*\d+[.)]\s+)(.*)$", re.IGNORECASE
    )

    result_parts = []
    bullet_group = []

    def flush_bullets():
        if not bullet_group:
            return
        cleaned = [re.sub(r"^[\s*\-•\d.)]+\s*", "", x).strip() for x in bullet_group]
        cleaned = [x for x in cleaned if x]
        if len(cleaned) == 1:
            result_parts.append(cleaned[0].strip() + ".")
        elif len(cleaned) == 2:
            result_parts.append(cleaned[0] + " and " + cleaned[1] + ".")
        else:
            result_parts.append(", ".join(cleaned[:-1]) + ", and " + cleaned[-1] + ".")
        bullet_group.clear()

    for line in lines:
        # Normalize remaining markdown (leftover * in middle) but do not strip bullet yet
        line = re.sub(r"\*\*|\*", "", line)
        line = line.strip()

        if not line:
            flush_bullets()
            continue

        match = bullet_pattern.match(line)
        if match:
            bullet_group.append(match.group(2).strip())
        else:
            flush_bullets()
            # Remove any remaining stray markdown chars
            line = re.sub(r"^[\s\-*#_`]+\s*|\s*[\s\-*#_`]+$", "", line)
            if line:
                result_parts.append(line)

    flush_bullets()

    # --- 6. Join with natural pauses (period or comma) ---
    out = " ".join(result_parts)

    # --- 7. Remove any remaining markdown/symbols so TTS never reads "star", "asterisk", etc. ---
    for char in ["*", "_", "`", "#", "~", "^", "|"]:
        out = out.replace(char, "")
    out = re.sub(r"-{2,}", " ", out)
    out = re.sub(r"\s+", " ", out)
    out = re.sub(r"\s*([,.])\s*", r"\1 ", out)
    out = out.strip()
    out = re.sub(r"^[\s\-*#_`~|]+\s*|\s*[\s\-*#_`~|]+$", "", out)
    out = re.sub(r"\s+", " ", out).strip()

    if out and out[-1] not in ".!?":
        out = out + "."

    return out
