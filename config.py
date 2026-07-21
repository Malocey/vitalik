"""
Stub configuration to maintain backward compatibility.
Delegates everything to src/core/config.py.
"""

from src.core.config import (
    BASE_DIR,
    DATA_DIR,
    TESTDATA_DIR,
    WIKI_DIR,
    VECTORSTORE_DIR,
    MOCK_STORAGE_DIR,
    MOCK_DRIVE_DIR,
    MOCK_SEVDESK_FILE,
    LOCAL_LLM_PROVIDER,
    OLLAMA_BASE_URL,
    LM_STUDIO_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_EMBEDDING_MODEL,
    PERSONA_PROFILE_FILE,
    SKR_MAPPING_FILE,
    CHECKPOINT_FILE,
)
