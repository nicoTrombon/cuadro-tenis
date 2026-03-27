"""
OCR utilities for extracting player names from draw images (JPG/PNG) or PDFs.
"""
import re
import io
from PIL import Image, ImageEnhance, ImageFilter

try:
    import pytesseract
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

try:
    import pdfplumber
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False


# Words to discard from OCR output
_DISCARD_PATTERNS = [
    r"^\d+$",                                   # Pure numbers
    r"^\d{1,2}[/\-\.\s]\d{1,2}",               # Dates like 25/3, 25 3
    r"^(RONDA|ROUND|QUARTS|QUARTER|SEMI|FINAL|CUARTOS|OCTAVOS|VUITENS|SEMIFINALS)$",
    r"^(RONDA|ROUND)\s+\d+$",
    r"^\d+[aªº]?\s*(RONDA|ROUND)$",
    r"^(MASCULÍ|FEMENÍ|MASCULINO|FEMENINO|ABSOLUT|ABSOLUTO).*$",
    r"^(TENNIS|MASTERS|OPEN|CHAMPIONSHIP|CUP|TROPHY).*$",
    r"^[IVX]+$",                                # Roman numerals alone
    r"^\d+[\s\-]*(may|jun|jul|ago|sep|oct|nov|dic|ene|feb|mar|abr|moy|mey).*$",
    r"^[\d\s\:\.\-\/]+$",                       # Only digits, spaces, colons, dots
    r"^[^a-zA-ZáéíóúüñÁÉÍÓÚÜÑ]*$",             # No Latin letters at all
]
_DISCARD_RE = [re.compile(p, re.IGNORECASE) for p in _DISCARD_PATTERNS]

# Minimum word count for a name (helps filter single-character OCR noise)
MIN_NAME_LENGTH = 3


def _preprocess_image(img: Image.Image) -> Image.Image:
    """
    Prepare image for OCR:
    - Scale up 4× (typical bracket images are small)
    - Convert to greyscale
    - Apply Otsu-style binarization to get clean black-on-white text
    """
    # Scale up 4× with high-quality resampling
    img = img.resize((img.width * 4, img.height * 4), Image.LANCZOS)
    img = img.convert("L")

    try:
        import numpy as np
        arr = np.array(img, dtype=np.uint8)
        # Otsu threshold: split at mean + (max-mean)*0.2 as a simple approximation
        threshold = int(arr.mean() + (arr.max() - arr.mean()) * 0.15)
        threshold = max(100, min(threshold, 220))
        binary = np.where(arr < threshold, 0, 255).astype(np.uint8)
        img = Image.fromarray(binary)
    except ImportError:
        # Fallback without numpy
        img = ImageEnhance.Contrast(img).enhance(3.0)

    return img


def _is_discardable(text: str) -> bool:
    text = text.strip()
    if len(text) < MIN_NAME_LENGTH:
        return True
    # Must contain at least 2 alphabetic characters in a row (not just initials or noise)
    if not re.search(r"[a-zA-ZáéíóúüñÁÉÍÓÚÜÑ]{2}", text):
        return True
    # Must have at least one word with 3+ letters (not just short noise)
    words_with_letters = [w for w in text.split() if re.search(r"[a-zA-ZáéíóúüñÁÉÍÓÚÜÑ]{3}", w)]
    if len(words_with_letters) < 1:
        return True
    for pattern in _DISCARD_RE:
        if pattern.match(text):
            return True
    return False


_TRAILING_DATE_RE = re.compile(
    r"[\s\d\:\-\/]*(0?\d|[12]\d|3[01])[\s\-\/](0?\d|1[0-2])[\s\-]*([\d:\s]*)$|"
    r"\s+\d{1,2}[\s\-](may|jun|jul|ago|sep|oct|nov|dic|ene|feb|mar|abr|moy|mey).*$",
    re.IGNORECASE,
)
_TRAILING_TIME_RE = re.compile(r"\s+\d{1,2}[\s:\.]\d{2}(\s+\d+)*\s*$")


def _clean_name(text: str) -> str:
    """Remove spurious characters and trailing dates/times from an extracted name."""
    # Strip trailing date/time patterns (e.g. "FERRAN 16 4 19 00" → "FERRAN")
    text = _TRAILING_DATE_RE.sub("", text)
    text = _TRAILING_TIME_RE.sub("", text)
    # Remove leftover non-name characters
    text = re.sub(r"[^\w\s\-\.\']", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# Matches: "1 NAME", "17 NAME", "1. NAME", "17.NAME", "17NAME" (number glued to name)
_NUMBERED_ENTRY_RE = re.compile(
    r"^\d{1,2}[.\s]*([A-ZÁÉÍÓÚÜÑa-záéíóúüñ].*)$"
)


def _parse_numbered_line(text: str) -> str | None:
    """
    If line starts with a player ranking number (1-64), return just the name part.
    Handles: '1 NAME', '17. NAME', '17NAME' (OCR glued), '17.NAME'.
    """
    m = _NUMBERED_ENTRY_RE.match(text.strip())
    if m:
        return m.group(1).strip()
    return None


def _extract_names_from_data(data: dict) -> list[str]:
    """
    Parse pytesseract image_to_data output and return a de-duplicated,
    position-ordered list of candidate player names.

    Strategy:
    - Group words by line (block_num + par_num + line_num)
    - Sort lines by top-Y coordinate
    - Filter out noise lines
    - Keep lines in the left ~45% of the image (round-1 column)
    """
    n = len(data["text"])
    if n == 0:
        return []

    # Find image width from max right coordinate
    max_right = max(
        (data["left"][i] + data["width"][i])
        for i in range(n)
        if data["width"][i] > 0
    ) or 1

    # Group tokens into lines
    lines: dict[tuple, dict] = {}
    for i in range(n):
        word = data["text"][i].strip()
        if not word:
            continue
        conf = int(data["conf"][i]) if str(data["conf"][i]).lstrip("-").isdigit() else -1
        if conf < 20:
            continue

        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        if key not in lines:
            lines[key] = {
                "words": [],
                "top": data["top"][i],
                "left": data["left"][i],
                "right": data["left"][i] + data["width"][i],
            }
        lines[key]["words"].append(word)
        lines[key]["top"] = min(lines[key]["top"], data["top"][i])
        lines[key]["left"] = min(lines[key]["left"], data["left"][i])
        lines[key]["right"] = max(
            lines[key]["right"], data["left"][i] + data["width"][i]
        )

    # Sort by vertical position
    sorted_lines = sorted(lines.values(), key=lambda l: l["top"])

    names = []
    for line in sorted_lines:
        text = " ".join(line["words"])

        # Strip leading player number FIRST (before date cleaning),
        # so "17 CARLOS 16/4 19:00" → "CARLOS 16/4 19:00" → "CARLOS"
        parsed = _parse_numbered_line(text)
        if parsed:
            text = parsed

        # Now clean trailing dates/times and noise
        text = _clean_name(text)

        if _is_discardable(text):
            continue

        # Only keep entries in the left portion of the image
        # (round-1 column is typically in the left 45%)
        if line["left"] > max_right * 0.45:
            continue

        names.append(text)

    return names


def extract_from_image(image_bytes: bytes) -> list[str]:
    """
    Run OCR on a JPG/PNG bracket image and return a list of candidate
    player names in draw order (top to bottom).
    """
    if not TESSERACT_AVAILABLE:
        return []

    img = Image.open(io.BytesIO(image_bytes))
    img = _preprocess_image(img)

    data = pytesseract.image_to_data(
        img,
        lang="spa+eng",
        config="--psm 6",
        output_type=pytesseract.Output.DICT,
    )
    return _extract_names_from_data(data)


def extract_from_pdf(pdf_bytes: bytes) -> list[str]:
    """
    Extract text from each page of a PDF and return candidate player names.
    """
    if not PDF_AVAILABLE:
        return []

    names = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            words = page.extract_words(x_tolerance=3, y_tolerance=3)
            if not words:
                # Fall back to OCR on the page image
                img = page.to_image(resolution=200).original
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                names.extend(extract_from_image(buf.getvalue()))
                continue

            # Sort by vertical position
            words_sorted = sorted(words, key=lambda w: (w["top"], w["x0"]))

            # Group into lines (words within 5px vertical tolerance are the same line)
            current_line: list[dict] = []
            current_top = None
            lines_text = []
            for w in words_sorted:
                if current_top is None or abs(w["top"] - current_top) < 6:
                    current_line.append(w)
                    current_top = w["top"] if current_top is None else current_top
                else:
                    if current_line:
                        lines_text.append(
                            (" ".join(wd["text"] for wd in current_line), current_line[0]["x0"])
                        )
                    current_line = [w]
                    current_top = w["top"]
            if current_line:
                lines_text.append(
                    (" ".join(wd["text"] for wd in current_line), current_line[0]["x0"])
                )

            # Determine left column threshold
            max_x = max(x for _, x in lines_text) if lines_text else 1

            for text, x0 in lines_text:
                text = _clean_name(text)
                if _is_discardable(text):
                    continue
                if x0 > max_x * 0.45:
                    continue
                names.append(text)

    return names


def extract_players(file_bytes: bytes, filename: str) -> list[str]:
    """
    Dispatch to the correct extractor based on file type.
    Returns a de-duplicated list of candidate player names.
    """
    fname = filename.lower()
    if fname.endswith(".pdf"):
        raw = extract_from_pdf(file_bytes)
    else:
        raw = extract_from_image(file_bytes)

    # De-duplicate while preserving order
    seen = set()
    result = []
    for name in raw:
        key = name.upper().strip()
        if key and key not in seen:
            seen.add(key)
            result.append(name)

    return result
