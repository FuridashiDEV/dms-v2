import hashlib
import mimetypes
from pathlib import Path


HIGH_RISK_EXTENSIONS = {
    ".doc",
    ".xls",
    ".ppt",
    ".odt",
    ".ods",
    ".odp",
    ".rtf",
}

MEDIUM_RISK_EXTENSIONS = {
    ".docx",
    ".xlsx",
    ".xlsm",
    ".pptx",
    ".pptm",
}


def calculate_sha256(path: str) -> str:
    file_path = Path(path)
    if not file_path.exists():
        return ""

    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_mime_type(file_name: str) -> str:
    mime_type, _ = mimetypes.guess_type(file_name or "")
    return mime_type or "application/octet-stream"


def detect_format_risk(file_name: str) -> str:
    ext = Path(file_name or "").suffix.lower()
    if not ext:
        return "UNKNOWN"
    if ext in HIGH_RISK_EXTENSIONS:
        return "HIGH"
    if ext in MEDIUM_RISK_EXTENSIONS:
        return "MEDIUM"
    return "LOW"
