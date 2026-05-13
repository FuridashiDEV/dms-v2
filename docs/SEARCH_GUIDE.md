# Search Guide

This guide describes the current DMS search experience after Stage 26.

## Search Modes

- Hybrid: default mode. Combines entity/text matching with semantic Qdrant hits when the vector index is available.
- Exact: text/entity matching only. It does not call embeddings or Qdrant.
- Semantic: semantic search first. If embeddings or Qdrant are unavailable, the page safely falls back to text/entity matching and keeps the same access checks.

The search core from Stage 25 remains responsible for normalization, aliases, entity extraction, embeddings, Qdrant collections and reindexing.

## Filters

The document search page supports:

- search query;
- search mode;
- document type;
- counterparty;
- amount range;
- document date range;
- department;
- folder;
- status.

All results are still filtered through organization isolation and object-level document access.

## Result Explanation

Each result can show:

- why it matched, such as text terms, aliases, entities or semantic score;
- the entities that matched the interpreted query;
- a short snippet from the document text or description;
- related documents that the current user is allowed to access.

The UI does not expose raw Qdrant payload, secure tokens or inaccessible related documents.

## Qdrant Fallback

If Qdrant is unavailable, returns no hits, or the embedding cannot be built, search falls back to the safe text/entity layer. This avoids blocking users while preserving permissions.

## Search Quality Evaluation

Run a permission-aware quality check:

```powershell
.\.venv\Scripts\python.exe manage.py evaluate_search_quality --user demo_admin --limit 5
```

Optional JSON cases file:

```json
[
  {
    "query": "contract with IP Firma for tools",
    "expected_title_contains": "Contract with IP Firma"
  }
]
```

Then run:

```powershell
.\.venv\Scripts\python.exe manage.py evaluate_search_quality --user demo_admin --cases docs/search_cases.json --limit 5
```

The command reports a simple precision-at-limit score. It is a QA aid, not a mathematical guarantee of search accuracy.

## Manual QA Checklist

1. Search for a contract by counterparty, subject and amount.
2. Switch between Hybrid, Exact and Semantic modes.
3. Apply counterparty and amount filters together.
4. Stop Qdrant and verify safe fallback.
5. Confirm snippets and explanations are useful.
6. Confirm related documents appear only when accessible.
7. Confirm users cannot infer inaccessible documents through search results.
