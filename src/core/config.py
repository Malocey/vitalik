"""
Zentrale Konfiguration für das Digitale Nervensystem von VG Delikatessen.
Verwaltet lokale Pfade, LLM/Embedding-Endpoints und RAG-Wiki-Parameter.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Pfade für Daten, RAG-Wiki und Mocks
DATA_DIR = BASE_DIR / "data"
TESTDATA_DIR = DATA_DIR / "testdata"
WIKI_DIR = DATA_DIR / "wiki"
VECTORSTORE_DIR = DATA_DIR / "vectorstore"
MOCK_STORAGE_DIR = DATA_DIR / "mock_storage"
MOCK_DRIVE_DIR = MOCK_STORAGE_DIR / "Drive"
MOCK_SEVDESK_FILE = MOCK_STORAGE_DIR / "sevdesk_buchungen.json"

# Sicherstellen, dass alle Verzeichnisse existieren
for d in [DATA_DIR, TESTDATA_DIR, WIKI_DIR, VECTORSTORE_DIR, MOCK_STORAGE_DIR, MOCK_DRIVE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# Lokale LLM / Embedding Einstellungen (Ollama / LM Studio)
LOCAL_LLM_PROVIDER = os.getenv("LOCAL_LLM_PROVIDER", "lm_studio")  # 'ollama' oder 'lm_studio'
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
LM_STUDIO_BASE_URL = os.getenv("LM_STUDIO_BASE_URL", "http://localhost:1234/v1")

# Modellnamen (konfigurierbar)
DEFAULT_LLM_MODEL = os.getenv("DEFAULT_LLM_MODEL", "supergemma-4-12b-abliterated")
DEFAULT_EMBEDDING_MODEL = os.getenv("DEFAULT_EMBEDDING_MODEL", "nomic-embed-text")

# Persona & Schreibstil Konfiguration
PERSONA_PROFILE_FILE = DATA_DIR / "persona_profile.json"
SKR_MAPPING_FILE = DATA_DIR / "skr_mapping.json"
CHECKPOINT_FILE = DATA_DIR / "checkpoint.json"
