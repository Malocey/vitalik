# LM-Studio-/LM-Link-Worker-Pool

## Ziel

Mehrere Rechner verarbeiten unabhängige Belege gleichzeitig. Der Bot wählt für
jeden LLM-Aufruf den am wenigsten ausgelasteten erreichbaren Endpoint. Fällt ein
Rechner aus, wird derselbe Auftrag an den nächsten Worker weitergereicht.

## Worker vorbereiten

Auf jedem Rechner muss dasselbe Gemma-Modell in LM Studio oder `llmster`
verfügbar sein. Der Server muss im lokalen Netz erreichbar sein:

```bash
lms server start --bind 0.0.0.0 --port 1234
```

In LM Studio kann alternativ unter **Developer → Server Settings**
`Serve on Local Network` aktiviert werden. Bei Netzwerkfreigabe sollte
`Require Authentication` eingeschaltet und pro Worker ein API-Token verwendet
werden.

## Bot konfigurieren

In `.env`:

```dotenv
LOCAL_LLM_PROVIDER=lm_studio
LM_STUDIO_ENDPOINTS=http://192.168.1.101:1234/v1,http://192.168.1.102:1234/v1,http://192.168.1.103:1234/v1
LM_STUDIO_MODELS=google/gemma-4-12b-qat,supergemma-4-12b-abliterated,supergemma-4-12b-abliterated
LM_STUDIO_API_TOKENS=token-pc-1,token-pc-2,token-pc-3
LLM_MAX_IN_FLIGHT_PER_ENDPOINT=1
LLM_REQUEST_TIMEOUT=120
LLM_FAILURE_COOLDOWN=30
DEFAULT_LLM_MODEL=google/gemma-3-12b
```

Die Modell- und Token-Reihenfolge muss der Endpoint-Reihenfolge entsprechen. Nach einer
Änderung muss der Pipeline-/Dashboard-Prozess neu gestartet werden.

## LM Link

LM Link kann einen entfernten Rechner transparent über den lokalen Endpoint
`http://localhost:1234/v1` verfügbar machen. Wenn dasselbe Modell auf mehreren
LM-Link-Geräten vorhanden ist, verwendet LM Studio das bevorzugte Gerät. Dieser
lokale Endpoint zählt für den Bot deshalb als ein Worker.

Für echte gleichzeitige Verteilung auf mehrere Rechner werden mehrere separat
adressierbare LM-Studio-Endpoints in `LM_STUDIO_ENDPOINTS` eingetragen. Diese
können im LAN oder über eine abgesicherte private Netzwerkverbindung erreichbar
sein.

## Status prüfen

```bash
python3 src/core/llm_pool_status.py
```

## Scheduler testen

```bash
python3 src/core/test_llm_pool.py
```
