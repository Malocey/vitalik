"""Zeigt Erreichbarkeit und Auslastung aller konfigurierten LLM-Worker."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.core.local_llm_client import default_llm_client


if __name__ == "__main__":
    for worker in default_llm_client.get_pool_status(check_health=True):
        state = "ONLINE" if worker["reachable"] else "OFFLINE"
        print(
            f"[{state}] {worker['url']} | aktiv={worker['active_requests']} "
            f"gesamt={worker['total_requests']} fehler={worker['failures']} | "
            f"modell={worker['configured_model']} "
            f"verfügbar={worker['model_available']}"
        )
