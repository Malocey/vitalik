# KI_BOT – Dokumentengedächtnis

Lokale, fehlertolerante Verarbeitung von Geschäftsbelegen mit OCR, deterministischer
Extraktion, optionalen LM-Studio-Workern, SQLite-FTS5-RAG, Wiki und CSV-Inventar.

## Einstieg

- [Systemarchitektur](docs/SYSTEM_ARCHITECTURE.md)
- [Aktueller Teststatus](docs/TEST_STATUS.md)
- [Dokumenten-Qualitätsbenchmark](docs/document_quality_benchmark.md)
- [LM-Studio-Cluster](docs/lm_studio_cluster.md)
- [Adaptive Fast Lane](docs/adaptive_fast_lane.md)
- [Wiederaufnehmbare Dokumentjobs](docs/resumable_document_jobs.md)

## Sichere lokale Prüfungen

```bash
python3 -m pytest -q
python3 src/core/benchmark_document_pipeline.py data/testdata --mode structural
```

Tests dürfen weder produktive Dateien verschieben noch `data/rag_index.db` oder das
Wiki verändern. Der aktuelle Integrationsstand umfasst Fast Lane und Job-Engine als
getestete Bausteine; ihre Verdrahtung in `ArchivePipeline` ist noch ausstehend.
