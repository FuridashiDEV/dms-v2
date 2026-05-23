# Stage 58 - AI/OCR Processing Policy

## Status

Completed as policy review and foundation documentation. No large new module was added.

## Existing implementation reviewed

- `ProcessingJob`
- `ProcessingProfile`
- `ProcessingCostPolicy`
- `ProcessingCostQuota`
- `dms/services/processing_center.py`
- `dms/services/cost_optimization.py`
- `should_run_ocr`
- cost estimates and non-blocking usage events

## Current target policy

Organization administrators can operate with these policy modes using the existing cost/policy foundation:

- Archive only: save document without expensive AI/OCR.
- Basic indexing: keep document searchable through basic metadata/text.
- Semantic search on demand: index selected documents for semantic search.
- Full AI/OCR for selected types: use OCR/AI when document type or quality requires it.
- Batch archival processing: schedule heavier jobs for controlled background processing.

## Upload behavior

The existing upload flow remains intact. The pilot recommendation is not to run expensive AI/OCR for every document by default. OCR should run only when text is missing/low quality, marked as scanned, or explicitly requested by an approved user/admin policy.

## Limitations

- UI for organization-level policy selection should be simplified after pilot feedback.
- No hard quota blocking is enabled.
- Heavy remote/GPU processing center is foundation only.

## Manual verification

- Upload text PDF: OCR should not be required.
- Upload image/scanned file: OCR routing should mark processing as needed.
- Cost dashboard should show estimates without blocking user work.
- Failed processing should not break upload/list/detail/search fallback.
