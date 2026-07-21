"""Tests für parallele Verteilung und Failover des LM-Studio-Pools."""

import sys
import threading
import time
from collections import Counter
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.local_llm_client import LocalLLMClient


class FakeResponse:
    def __init__(self, status_code, content=""):
        self.status_code = status_code
        self.content = content

    def json(self):
        return {"choices": [{"message": {"content": self.content}}]}


def test_parallel_distribution() -> None:
    calls = []
    lock = threading.Lock()
    active = Counter()
    peak = Counter()

    def fake_post(url, json, headers, timeout):
        with lock:
            calls.append((url, headers.get("Authorization"), json.get("model")))
            host = url.split("/")[2]
            active[host] += 1
            peak[host] = max(peak[host], active[host])
        time.sleep(0.02)
        with lock:
            active[host] -= 1
        return FakeResponse(200, url)

    client = LocalLLMClient(
        provider="lm_studio",
        endpoints=["http://worker-a:1234/v1", "http://worker-b:1234/v1"],
        api_tokens=["token-a", "token-b"],
        endpoint_models=["gemma-worker-a", "gemma-worker-b"],
        max_in_flight_per_endpoint=1,
        request_timeout=1,
    )
    with patch("src.core.local_llm_client.requests.post", side_effect=fake_post):
        results = client.generate_completions_parallel(
            [f"Aufgabe {index}" for index in range(8)], max_workers=8
        )

    distribution = Counter(url.split("/")[2] for url, _, _ in calls)
    assert len(results) == 8
    assert distribution["worker-a:1234"] > 0
    assert distribution["worker-b:1234"] > 0
    assert {auth for _, auth, _ in calls} == {"Bearer token-a", "Bearer token-b"}
    assert {model for _, _, model in calls} == {"gemma-worker-a", "gemma-worker-b"}
    assert max(peak.values()) == 1


def test_failover() -> None:
    def fake_post(url, json, headers, timeout):
        if "worker-bad" in url:
            raise ConnectionError("nicht erreichbar")
        return FakeResponse(200, "vom Ersatz-Worker")

    client = LocalLLMClient(
        provider="lm_studio",
        endpoints=["http://worker-bad:1234/v1", "http://worker-good:1234/v1"],
        endpoint_models=["gemma-bad", "gemma-good"],
        request_timeout=1,
        failure_cooldown=30,
    )
    with patch("src.core.local_llm_client.requests.post", side_effect=fake_post):
        result = client.generate_completion("Test")
    assert result == "vom Ersatz-Worker"
    status = client.get_pool_status()
    assert status[0]["failures"] == 1 and status[0]["cooldown"]
    assert status[1]["failures"] == 0


if __name__ == "__main__":
    test_parallel_distribution()
    test_failover()
    print("LM-Studio-Pooltests erfolgreich")
