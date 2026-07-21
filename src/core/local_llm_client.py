"""
Client-Adapter für lokale LLMs und Embedding-Modelle (Ollama & LM Studio).
Unterstützt Graceful Degradation / Mock-Fallback bei Offline-Zuständen mit rascher Timeout-Erkennung.
"""

import json
import logging
import math
import re
import requests
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Sequence
from config import (
    LOCAL_LLM_PROVIDER,
    OLLAMA_BASE_URL,
    LM_STUDIO_BASE_URL,
    LM_STUDIO_ENDPOINTS,
    LM_STUDIO_API_TOKENS,
    LM_STUDIO_MODELS,
    LLM_MAX_IN_FLIGHT_PER_ENDPOINT,
    LLM_REQUEST_TIMEOUT,
    LLM_FAILURE_COOLDOWN,
    DEFAULT_LLM_MODEL,
    DEFAULT_EMBEDDING_MODEL
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("LocalLLMClient")


@dataclass
class LMStudioEndpoint:
    base_url: str
    token: str = ""
    model_name: str = ""
    active_requests: int = 0
    total_requests: int = 0
    failures: int = 0
    cooldown_until: float = 0.0


class LocalLLMClient:
    def __init__(
        self,
        provider: str = LOCAL_LLM_PROVIDER,
        model_name: str = DEFAULT_LLM_MODEL,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        endpoints: Optional[Sequence[str]] = None,
        api_tokens: Optional[Sequence[str]] = None,
        endpoint_models: Optional[Sequence[str]] = None,
        request_timeout: float = LLM_REQUEST_TIMEOUT,
        failure_cooldown: float = LLM_FAILURE_COOLDOWN,
        max_in_flight_per_endpoint: int = LLM_MAX_IN_FLIGHT_PER_ENDPOINT,
    ):
        self.provider = provider.lower()
        self.model_name = model_name
        self.embedding_model = embedding_model
        endpoint_urls = list(endpoints or LM_STUDIO_ENDPOINTS or [LM_STUDIO_BASE_URL])
        tokens = list(api_tokens or LM_STUDIO_API_TOKENS)
        models = list(endpoint_models or LM_STUDIO_MODELS)
        self.endpoints = [
            LMStudioEndpoint(
                base_url=url.rstrip("/"),
                token=tokens[index] if index < len(tokens) else "",
                model_name=models[index] if index < len(models) and models[index] else model_name,
            )
            for index, url in enumerate(endpoint_urls)
        ]
        self.request_timeout = request_timeout
        self.failure_cooldown = failure_cooldown
        self.max_in_flight_per_endpoint = max(1, max_in_flight_per_endpoint)
        self._pool_lock = threading.Lock()
        self._pool_condition = threading.Condition(self._pool_lock)

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

        raise RuntimeError("Kein Ollama-Modell erreichbar; keine synthetischen Belegdaten erzeugt.")

    def _call_lm_studio(
        self,
        prompt: str,
        system_prompt: Optional[str],
        temperature: float,
        json_mode: bool
    ) -> str:
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

        attempted = set()
        while len(attempted) < len(self.endpoints):
            endpoint = self._acquire_endpoint(attempted)
            if endpoint is None:
                break
            attempted.add(endpoint.base_url)
            url = f"{endpoint.base_url}/chat/completions"
            headers = {"Authorization": f"Bearer {endpoint.token}"} if endpoint.token else {}
            endpoint_payload = dict(payload)
            endpoint_payload["model"] = endpoint.model_name or self.model_name
            try:
                res = requests.post(
                    url, json=endpoint_payload, headers=headers,
                    timeout=(3.0, self.request_timeout),
                )
                if res.status_code != 200 and json_mode:
                    endpoint_payload.pop("response_format", None)
                    res = requests.post(
                        url, json=endpoint_payload, headers=headers,
                        timeout=(3.0, self.request_timeout),
                    )
                if res.status_code == 200:
                    choices = res.json().get("choices", [])
                    if choices:
                        self._release_endpoint(endpoint, succeeded=True)
                        return choices[0].get("message", {}).get("content", "")
                logger.warning(
                    f"[LLM POOL] Worker {endpoint.base_url} antwortete mit HTTP {res.status_code}."
                )
            except Exception as e:
                logger.warning(f"[LLM POOL] Worker {endpoint.base_url} ausgefallen: {e}")
            self._release_endpoint(endpoint, succeeded=False)

        raise RuntimeError("Kein LM-Studio-Worker erreichbar; keine synthetischen Belegdaten erzeugt.")

    def _acquire_endpoint(self, excluded: set) -> Optional[LMStudioEndpoint]:
        with self._pool_condition:
            while True:
                candidates = [
                    endpoint for endpoint in self.endpoints
                    if endpoint.base_url not in excluded
                ]
                if not candidates:
                    return None
                now = time.monotonic()
                healthy = [
                    endpoint for endpoint in candidates
                    if endpoint.cooldown_until <= now
                ]
                if not healthy:
                    return None
                available = [
                    endpoint for endpoint in healthy
                    if endpoint.active_requests < self.max_in_flight_per_endpoint
                ]
                if available:
                    endpoint = min(
                        available,
                        key=lambda item: (
                            item.active_requests, item.total_requests, item.failures
                        ),
                    )
                    endpoint.active_requests += 1
                    endpoint.total_requests += 1
                    return endpoint
                self._pool_condition.wait(timeout=0.25)

    def _release_endpoint(self, endpoint: LMStudioEndpoint, succeeded: bool) -> None:
        with self._pool_condition:
            endpoint.active_requests = max(0, endpoint.active_requests - 1)
            if succeeded:
                endpoint.failures = 0
                endpoint.cooldown_until = 0.0
            else:
                endpoint.failures += 1
                endpoint.cooldown_until = time.monotonic() + self.failure_cooldown
            self._pool_condition.notify_all()

    def generate_completions_parallel(
        self,
        prompts: Sequence[str],
        max_workers: Optional[int] = None,
        **kwargs: Any,
    ) -> List[str]:
        """Verteilt unabhängige Prompts parallel auf alle konfigurierten Worker."""
        workers = max_workers or max(1, len(self.endpoints))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [
                executor.submit(self.generate_completion, prompt, **kwargs)
                for prompt in prompts
            ]
            return [future.result() for future in futures]

    def get_pool_status(self, check_health: bool = False) -> List[Dict[str, Any]]:
        """Liefert Auslastung und optional die Erreichbarkeit aller Worker."""
        status = []
        for endpoint in self.endpoints:
            reachable = None
            loaded_models: List[str] = []
            if check_health:
                headers = {"Authorization": f"Bearer {endpoint.token}"} if endpoint.token else {}
                try:
                    response = requests.get(
                        f"{endpoint.base_url}/models", headers=headers, timeout=3.0
                    )
                    reachable = response.status_code == 200
                    if reachable:
                        loaded_models = [
                            item.get("id", "") for item in response.json().get("data", [])
                        ]
                except Exception:
                    reachable = False
            status.append({
                "url": endpoint.base_url,
                "configured_model": endpoint.model_name,
                "model_available": endpoint.model_name in loaded_models if check_health else None,
                "loaded_models": loaded_models,
                "reachable": reachable,
                "active_requests": endpoint.active_requests,
                "total_requests": endpoint.total_requests,
                "failures": endpoint.failures,
                "cooldown": endpoint.cooldown_until > time.monotonic(),
            })
        return status

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
        import hashlib
        words = re.findall(r'\w+', text.lower())
        vec = [0.0] * dim
        for i, word in enumerate(words):
            h = int.from_bytes(hashlib.sha256(word.encode("utf-8")).digest()[:8], "big") % dim
            vec[h] += 1.0 / (i + 1)
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

# Globale Standard-Instanz
default_llm_client = LocalLLMClient()
