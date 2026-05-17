from __future__ import annotations

from dataclasses import dataclass

from dms.models import ProcessingJob


@dataclass(frozen=True)
class ProcessingRole:
    name: str
    stages: tuple[str, ...]
    description: str


PROCESSING_ROLES: dict[str, ProcessingRole] = {
    "scheduler": ProcessingRole(
        name="scheduler",
        stages=(ProcessingJob.Stage.FAN_OUT, ProcessingJob.Stage.FAN_IN),
        description="Coordinates fan-out/fan-in jobs and scheduler-only queue work.",
    ),
    "ocr-worker": ProcessingRole(
        name="ocr-worker",
        stages=(ProcessingJob.Stage.OCR, ProcessingJob.Stage.TEXT_EXTRACTION),
        description="Runs OCR and text extraction jobs.",
    ),
    "embedding-worker": ProcessingRole(
        name="embedding-worker",
        stages=(ProcessingJob.Stage.CHUNKING, ProcessingJob.Stage.EMBEDDING),
        description="Runs chunking and embedding jobs.",
    ),
    "entity-worker": ProcessingRole(
        name="entity-worker",
        stages=(ProcessingJob.Stage.AI_PARSE, ProcessingJob.Stage.ENTITY_EXTRACTION),
        description="Runs AI parsing and entity extraction jobs.",
    ),
    "rerank-worker": ProcessingRole(
        name="rerank-worker",
        stages=(ProcessingJob.Stage.RERANKING,),
        description="Runs optional reranking jobs.",
    ),
    "qdrant-index-worker": ProcessingRole(
        name="qdrant-index-worker",
        stages=(ProcessingJob.Stage.REINDEX,),
        description="Runs local reindex jobs through the existing index_document service.",
    ),
    "notification-worker": ProcessingRole(
        name="notification-worker",
        stages=(),
        description="Reserved notification worker role for future async notification fan-out.",
    ),
}


def get_processing_role(name: str) -> ProcessingRole:
    try:
        return PROCESSING_ROLES[name]
    except KeyError as exc:
        available = ", ".join(sorted(PROCESSING_ROLES))
        raise ValueError(f"Unknown processing role '{name}'. Available roles: {available}.") from exc
