"""Course title helpers: split "Main: Subtitle", slugs, and abbreviation-insensitive comparison."""

import re
import unicodedata

# "Special Topics in ...", "Topics in ...", "Topic: ...", "Special Topic in ..."
TOPIC_PREFIX_RE = re.compile(r"^(special\s+)?topics?\b", re.IGNORECASE)
# Main/subtitle separators as used on counts.oxy.edu: ": ", ". ", " - ", "History- Encoding".
SEPARATOR_RE = re.compile(r":\s*|\.\s+|\s+[-\u2013\u2014]+\s+|(?<=\w)[-\u2013]\s+")
# Before a period these are abbreviations, not the end of a main title: "U.S", initials, "St", "Dr".
ABBREVIATION_END_RE = re.compile(r"(?:^|[\s.])(?:[A-Z]|[A-Z][a-z])$")
LAB_SUFFIX_RE = re.compile(r"\s+(laboratory|lab)$", re.IGNORECASE)
WORD_FORMS = {"sci": "science", "lab": "laboratory", "intro": "introduction"}


# The source turns curly quotes and dashes into "?": "Man?s Burden", "the role ? if any ? of".
APOSTROPHE_RE = re.compile(r"(?<=[A-Za-z])\?(?=[a-z])")
DASH_RE = re.compile(r" \? ")


def fix_question_marks(text: str) -> str:
    return DASH_RE.sub(" \u2014 ", APOSTROPHE_RE.sub("'", text))


def split_title(title: str) -> tuple[str, str | None]:
    """("Special Topics in Computer Science", "Deep Learning") from either "...: Deep Learning"
    or "... . Deep Learning". The first separator wins; a period after an initial does not split.
    """
    for match in SEPARATOR_RE.finditer(title):
        main = title[: match.start()].strip()
        if not main:
            continue
        if match.group().startswith(".") and ABBREVIATION_END_RE.search(main):
            continue
        sub = title[match.end() :].strip()
        return (main, sub) if sub else (title.strip(), None)
    return title.strip(), None


def has_topic_prefix(title: str) -> bool:
    return bool(TOPIC_PREFIX_RE.match(title))


def strip_lab_suffix(title: str) -> str:
    return LAB_SUFFIX_RE.sub("", title).strip()


def ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def slugify(text: str) -> str:
    """Lowercase ASCII words joined by hyphens: "Art & Money: II" -> art-and-money-ii."""
    text = ascii_fold(text).lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def title_key(title: str) -> str:
    """Comparison form that ignores case, punctuation and common abbreviations, so
    "Fundamentals/Computer Sci Lab" == "Fundamentals of Computer Science Laboratory"."""
    text = ascii_fold(title).lower().replace("&", " and ").replace("/", " of ")
    words = re.findall(r"[a-z0-9]+", text)
    return " ".join(WORD_FORMS.get(w, w) for w in words)
