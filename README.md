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
- [Dublettenfreies Kontaktgedächtnis](docs/contact_memory.md)
- [Privater Fernzugriff und Control Center](docs/REMOTE_ACCESS.md)

## Sichere lokale Prüfungen

```bash
python3 -m pytest -q
python3 src/core/benchmark_document_pipeline.py data/testdata --mode structural
```

Tests dürfen weder produktive Dateien verschieben noch `data/rag_index.db` oder das
Wiki verändern. Die Job-Engine und das Kontaktgedächtnis sind in `ArchivePipeline`
integriert. Die Fast Lane bleibt bis zum gesonderten A/B-Benchmark deaktiviert.
