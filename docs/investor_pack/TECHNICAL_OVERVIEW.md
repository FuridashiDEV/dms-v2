# Technical Overview

DocFlow is a Django/PostgreSQL application with a service-layer approach around document creation, search, evidence, workflow, exchange, billing foundation, observability and processing.

## Implemented foundations

- Django models for organizations, members, documents, versions, audit, processing jobs, workflows, exchanges, integrations, billing plans and usage.
- Document upload flow preserves the original file and creates DocumentVersion.
- Organization isolation is enforced in querysets and services.
- Search uses normalized text, extracted entities, aliases, vector store foundation and reranking foundation.
- Qdrant is optional and has safe fallback behavior.
- Processing jobs have retry/backpressure foundations.
- Webhook delivery has retries and secret redaction.

## Deployment shape

- Local/dev mode remains supported.
- Docker and Kubernetes-ready templates are foundation only.
- First pilot can run on a VM with Postgres, media storage and optional Qdrant.

## Technical limitations

- Heavy embedding/OCR/reranking models are not loaded by default.
- Benchmark datasets are synthetic/semi-real until customer pilot documents are approved for testing.
- HA cluster and managed GPU operations are post-pilot scaling work.
