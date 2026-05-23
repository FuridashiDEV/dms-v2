# Stage 52 - Real Document Search Benchmark

## Status

Completed as a safe semi-real benchmark foundation.

## What was added

- Added dataset: `docs/search_benchmark/realistic_document_search_benchmark.json`.
- Extended `benchmark_model_stack` with `--dataset realistic`.
- Added `--models all` shortcut to compare configured model, BGE-M3, multilingual-e5-large and baseline fallback without loading heavy models.
- Added regression test for realistic benchmark execution.

## Dataset coverage

- Document types: contract, appendix, act, invoice, additional agreement, order, scanned PDF scenario, report.
- Languages: Russian, Kazakh, mixed Russian/English.
- Query dimensions: counterparty, amount, date, document number, document type, contract subject.

## Safe benchmark results

Command:

```powershell
.\.venv\Scripts\python.exe manage.py benchmark_model_stack --dataset realistic --models all --limit 8 --format json
```

Observed in deterministic fallback mode:

- BAAI/bge-m3: top-1 1.0, top-3 1.0, top-5 1.0, MRR 1.0, precision@5 0.2, recall@10 1.0, avg latency about 25 ms, p95 about 28 ms.
- intfloat/multilingual-e5-large: top-1 1.0, top-3 1.0, top-5 1.0, MRR 1.0, precision@5 0.2, recall@10 1.0, avg latency about 25 ms, p95 about 26 ms.
- all-MiniLM-L6-v2: top-1 1.0, top-3 1.0, top-5 1.0, MRR 1.0, precision@5 0.2, recall@10 1.0, avg latency about 25 ms, p95 about 29 ms.

## Limitations

- This is synthetic/semi-real data, not real customer documents.
- Default mode does not load heavy models; results validate ranking pipeline and metrics shape, not true neural quality.
- Qdrant insert time remains 0 in this safe command because no disposable benchmark collection is written.
- OCR quality notes are scenario notes only; real scanned PDFs still need customer-approved testing.

## Recommendation

Keep BGE-M3 as configured default until a customer-approved benchmark shows a clear quality/latency tradeoff. Do not mix embedding dimensions or models in one Qdrant collection.
