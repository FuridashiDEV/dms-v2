from __future__ import annotations

import os
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import FileResponse
from django.utils.module_loading import import_string


DANGEROUS_MIME_TYPES = {
    "application/x-msdownload",
    "application/x-msdos-program",
    "application/x-ms-installer",
    "application/x-sh",
    "application/x-bat",
    "application/x-cmd",
    "application/javascript",
    "text/javascript",
    "application/x-javascript",
    "text/html",
}


@dataclass(frozen=True)
class AntivirusScanResult:
    allowed: bool
    reason: str = ""


def validate_upload_security(uploaded_file, *, disallowed_extensions: set[str], max_file_mb: int):
    if not uploaded_file:
        return uploaded_file

    file_name = os.path.basename(uploaded_file.name or "")
    if len(file_name) > 255:
        raise ValidationError("File name is too long.")

    lower_name = file_name.lower()
    suffixes = [suffix for suffix in lower_name.split(".")[1:] if suffix]
    if any(f".{suffix}" in disallowed_extensions for suffix in suffixes):
        raise ValidationError("This file name contains a blocked executable extension.")

    content_type = (getattr(uploaded_file, "content_type", "") or "").split(";")[0].strip().lower()
    if content_type in DANGEROUS_MIME_TYPES:
        raise ValidationError("This file MIME type is blocked for upload.")

    if uploaded_file.size > max_file_mb * 1024 * 1024:
        raise ValidationError("File is too large.")

    scan_uploaded_file(uploaded_file)
    return uploaded_file


def scan_uploaded_file(uploaded_file) -> AntivirusScanResult:
    scanner_path = getattr(settings, "DMS_ANTIVIRUS_SCANNER", "")
    if not scanner_path:
        return AntivirusScanResult(allowed=True)

    try:
        scanner = import_string(scanner_path)
        result = scanner(uploaded_file)
    except Exception as exc:
        if getattr(settings, "DMS_ANTIVIRUS_FAIL_CLOSED", False):
            raise ValidationError("File security scan is unavailable.") from exc
        return AntivirusScanResult(allowed=True, reason="scanner_unavailable")

    if isinstance(result, AntivirusScanResult):
        scan_result = result
    elif isinstance(result, tuple):
        scan_result = AntivirusScanResult(bool(result[0]), str(result[1]) if len(result) > 1 else "")
    else:
        scan_result = AntivirusScanResult(bool(result))

    if not scan_result.allowed:
        raise ValidationError(scan_result.reason or "File did not pass security scan.")
    return scan_result


def protected_file_response(file_field, *, as_attachment: bool) -> FileResponse:
    response = FileResponse(file_field.open("rb"), as_attachment=as_attachment)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    response["Referrer-Policy"] = "no-referrer"
    response["X-Frame-Options"] = "SAMEORIGIN"
    return response
