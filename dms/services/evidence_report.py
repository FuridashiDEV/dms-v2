from __future__ import annotations

import hashlib
import json
from typing import Any


def evidence_report_checksum(package: dict[str, Any]) -> str:
    payload = json.dumps(package, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_evidence_timeline(package: dict[str, Any]) -> list[dict[str, str]]:
    timeline: list[dict[str, str]] = []

    document = package.get("document") or {}
    if document.get("created_at"):
        timeline.append(
            {
                "at": document["created_at"],
                "type": "document.created",
                "label": f"Document created: {document.get('title', '')}",
            }
        )

    for version in package.get("versions", []):
        if version.get("created_at"):
            timeline.append(
                {
                    "at": version["created_at"],
                    "type": "version.created",
                    "label": f"Version {version.get('number')} created",
                }
            )

    for job in (package.get("ai") or {}).get("processing_jobs", []):
        if job.get("created_at"):
            timeline.append(
                {
                    "at": job["created_at"],
                    "type": "ai.processing",
                    "label": f"AI processing {job.get('status', '')}",
                }
            )

    for workflow in package.get("workflow", []):
        if workflow.get("started_at"):
            timeline.append(
                {
                    "at": workflow["started_at"],
                    "type": "workflow.started",
                    "label": f"Workflow started: {(workflow.get('template') or {}).get('name', '')}",
                }
            )
        for action in workflow.get("actions", []):
            if action.get("created_at"):
                timeline.append(
                    {
                        "at": action["created_at"],
                        "type": "workflow.action",
                        "label": f"Workflow action: {action.get('action_type', '')}",
                    }
                )

    for exchange in package.get("exchanges", []):
        if exchange.get("created_at"):
            timeline.append(
                {
                    "at": exchange["created_at"],
                    "type": "exchange.created",
                    "label": f"Exchange {exchange.get('direction', '')} {exchange.get('status', '')}",
                }
            )
        for event in exchange.get("events", []):
            if event.get("created_at"):
                timeline.append(
                    {
                        "at": event["created_at"],
                        "type": "exchange.event",
                        "label": f"Exchange event: {event.get('event_type', '')}",
                    }
                )
        for message in exchange.get("messages", []):
            if message.get("created_at"):
                timeline.append(
                    {
                        "at": message["created_at"],
                        "type": "exchange.message",
                        "label": f"Exchange message: {message.get('author_type', '')}",
                    }
                )

    for event in package.get("audit_events", []):
        if event.get("created_at"):
            timeline.append(
                {
                    "at": event["created_at"],
                    "type": "audit.event",
                    "label": f"Audit event: {event.get('event_type', '')}",
                }
            )

    return sorted(timeline, key=lambda item: item["at"])


def build_evidence_report_context(package: dict[str, Any]) -> dict[str, Any]:
    checksum = evidence_report_checksum(package)
    return {
        "package": package,
        "schema": package.get("schema") or {},
        "export": package.get("export") or {},
        "organization": package.get("organization") or {},
        "document": package.get("document") or {},
        "versions": package.get("versions") or [],
        "related_documents": package.get("related_documents") or [],
        "ai": package.get("ai") or {},
        "workflow": package.get("workflow") or [],
        "exchanges": package.get("exchanges") or [],
        "audit_events": package.get("audit_events") or [],
        "timeline": build_evidence_timeline(package),
        "report_checksum_sha256": checksum,
        "limitations": [
            "This report is a human-readable view of DMS records and does not claim independent legal force.",
            "The report does not include electronic signature, blockchain proof, raw file contents, secure tokens, token hashes, API keys or server file paths.",
            "Access is limited to users who can access the source document in the current organization.",
        ],
    }
