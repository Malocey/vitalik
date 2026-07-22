from src.core.rag_engine import RAGEngine


def test_search_prefers_exact_wiki_hub_and_respects_limit(monkeypatch, tmp_path):
    engine = object.__new__(RAGEngine)
    engine.llm_client = type("LLM", (), {"generate_embedding": lambda self, text: [1.0, 0.0]})()
    engine.documents = [
        {"doc_id": "wiki_supplier_jensmann", "title": "Jensmann", "content": "Hub",
         "source": "jensmann.md", "category": "wiki_lieferant", "embedding": [1.0, 0.0]},
        {"doc_id": "noise", "title": "Andere Firma", "content": "Noise",
         "source": "noise.md", "category": "wiki_lieferant", "embedding": [1.0, 0.0]},
    ]
    monkeypatch.setattr(engine, "search_fts", lambda query, top_k: [
        {"doc_id": f"VG-{number}", "title": "Beleg", "content": "", "source": "fts5",
         "category": "beleg", "score": -1} for number in range(5)
    ])
    monkeypatch.setattr(engine, "search_sevdesk", lambda query, top_k: [])
    results = engine.search("Jensmann", top_k=3)
    assert len(results) == 3
    assert results[0]["doc_id"] == "wiki_supplier_jensmann"
