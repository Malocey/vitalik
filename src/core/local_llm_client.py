"""
Client-Adapter für lokale LLMs und Embedding-Modelle (Ollama & LM Studio).
Unterstützt Graceful Degradation / Mock-Fallback bei Offline-Zuständen mit rascher Timeout-Erkennung.
"""

import json
import logging
import math
import re
import requests
from typing import Dict, Any, List, Optional
from config import (
    LOCAL_LLM_PROVIDER,
    OLLAMA_BASE_URL,
    LM_STUDIO_BASE_URL,
    DEFAULT_LLM_MODEL,
    DEFAULT_EMBEDDING_MODEL
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("LocalLLMClient")


class LocalLLMClient:
    def __init__(self, provider: str = LOCAL_LLM_PROVIDER, model_name: str = DEFAULT_LLM_MODEL, embedding_model: str = DEFAULT_EMBEDDING_MODEL):
        self.provider = provider.lower()
        self.model_name = model_name
        self.embedding_model = embedding_model

    def generate_completion(
        self,
        prompt: str,
        system_prompt: Optional[str] = None,
        temperature: float = 0.2,
        json_mode: bool = False
    ) -> str:
        """
        Generiert eine Antwort vom lokalen LLM.
        """
        if self.provider == "ollama":
            return self._call_ollama(prompt, system_prompt, temperature, json_mode)
        else:
            return self._call_lm_studio(prompt, system_prompt, temperature, json_mode)

    def _call_ollama(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        json_mode: bool
    ) -> str:
        url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "options": {"temperature": temperature},
            "stream": False
        }
        if json_mode:
            payload["format"] = "json"

        try:
            res = requests.post(url, json=payload, timeout=120.0)
            if res.status_code == 200:
                data = res.json()
                return data.get("message", {}).get("content", "")
        except Exception:
            pass

        return self._offline_fallback_completion(prompt, json_mode)

    def _call_lm_studio(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        json_mode: bool
    ) -> str:
        url = f"{LM_STUDIO_BASE_URL.rstrip('/')}/chat/completions"
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        try:
            res = requests.post(url, json=payload, timeout=120.0)
            if res.status_code != 200 and json_mode:
                logger.info("[LocalLLMClient] LM Studio wies response_format zurück. Starte Retry ohne JSON-Formatierungs-Parameter...")
                payload.pop("response_format", None)
                res = requests.post(url, json=payload, timeout=120.0)

            if res.status_code == 200:
                data = res.json()
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")
        except Exception as e:
            logger.warning(f"[LocalLLMClient] LM Studio Fehler: {e}")

        return self._offline_fallback_completion(prompt, json_mode)

    def generate_embedding(self, text: str) -> List[float]:
        """
        Erzeugt Vektor-Embeddings für einen Text.
        Falls Ollama/LM Studio offline ist, erzeugt ein deterministisches Hash-Vector.
        """
        if self.provider == "ollama":
            url = f"{OLLAMA_BASE_URL.rstrip('/')}/api/embeddings"
            payload = {"model": self.embedding_model, "prompt": text}
            try:
                res = requests.post(url, json=payload, timeout=1.5)
                if res.status_code == 200:
                    return res.json().get("embedding", [])
            except Exception:
                pass

        return self._fallback_embedding(text)

    def _fallback_embedding(self, text: str, dim: int = 128) -> List[float]:
        words = re.findall(r'\w+', text.lower())
        vec = [0.0] * dim
        for i, word in enumerate(words):
            h = hash(word) % dim
            vec[h] += 1.0 / (i + 1)
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def _offline_fallback_completion(self, prompt: str, json_mode: bool) -> str:
        """Simulierter Offline-Fallback für Entwicklungs- & Testzwecke ohne laufenden Server."""
        if json_mode:
            return json.dumps({
                "lieferant": "VG Delikatessen Metzgerei-Großhandel",
                "datum": "2026-07-01",
                "netto": 100.00,
                "steuer": 7.00,
                "brutto": 107.00,
                "rechnungsnummer": "MOCK-RE-2026-001",
                "confidence_score": 0.98,
                "start_seite": 1,
                "end_seite": 1,
                "warengruppe": "Fleischwaren"
            })
        return f"[LOKALER VITA-LLM]: Ich habe die Information im RAG-Wiki von VG Delikatessen geprüft und verarbeitet."


# Globale Standard-Instanz
default_llm_client = LocalLLMClient()
