# Import, AI, And Workflow Guide

## Import

Status: implemented

Use `/documents/import/` to import multiple files. The import layer creates ordinary `Document` records and `DocumentVersion` records. Import details are available at `/imports/<id>/`.

Duplicate detection uses SHA-256 where available. Duplicate detection is informational and should be reviewed by an internal user.

Import does not bypass permissions and does not replace the single upload flow at `/documents/upload/`.

## AI Processing

Status: partially implemented

AI processing uses current parser/extraction services and stores results in:

- `ProcessingJob`
- `ExtractedField`

AI output is stored as suggestions. Users review suggestions at `/documents/<id>/ai-review/`. The project applies only allowed confirmed fields to `Document`. Unconfirmed or rejected fields do not update document metadata.

## AI Parser Endpoint

Status: partially implemented

The route `/ai/parse/` exists for parser-related behavior in the current app. It should not be treated as a full public AI API.

## AI Limitations

- Real OCR quality must be tested with representative scanned PDFs.
- LLM/parser quality is not guaranteed by tests alone.
- Heavy async bulk AI processing is not implemented.
- AI results require manual validation before they affect document metadata.

## Workflow

Status: partially implemented

Workflow models:

- `WorkflowTemplate`
- `WorkflowStepTemplate`
- `WorkflowInstance`
- `WorkflowAction`

Internal routes:

- `/documents/<id>/workflow/start/`
- `/documents/<id>/workflow/<instance_id>/<action>/`

Supported actions include approve, reject, request changes, and comment. Actions are permission checked against the assigned approver and organization scope. Workflow changes can update `Document.status`.

## Workflow Limitations

- No BPMN engine.
- No no-code builder.
- No external approver account model.
- No automatic legal signing.
- No complex escalation/SLA engine.
