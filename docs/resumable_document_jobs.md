# Resumable Document Jobs Architecture

Die Job-Engine bietet eine robuste und wiederaufnehmbare Verarbeitung von Dokumenten. Sie verwendet eine eigenständige SQLite-Datenbank als Persistenzschicht und ermöglicht es mehreren Workern, Jobs sicher abzuarbeiten.

## Architektur

Die Architektur trennt das Datenbank-Backend (`JobRepository`) von der Geschäftslogik (`DocumentJobEngine`).
Die SQLite-Datenbank (`data/document_jobs.db`) läuft im WAL-Modus, um Locking-Probleme bei parallelen Lese-/Schreibzugriffen zu minimieren, und verwendet einen Busy-Timeout, um mit kurzfristigen Sperren umzugehen.
Es gibt keinen zentralen Dispatcher – stattdessen greifen alle Worker über atomare Updates auf die zentrale Datenbank zu, um Jobs zu "leasen".

## Statusübergänge

Erlaubte normale Übergänge in der Pipeline:
* `DISCOVERED` -> `OCR_RUNNING` -> `OCR_COMPLETE`
* `OCR_COMPLETE` -> `ANALYSIS_RUNNING` -> `ANALYSIS_COMPLETE`
* `ANALYSIS_COMPLETE` -> `RAG_RUNNING` -> `COMMITTED`

Fehler- und Sonderstatus:
* Tritt ein Fehler auf, wird ein Job in `RETRY_PENDING` verschoben (s. Retry-Formel).
* Nach Ablauf des Backoffs oder beim manuellen Neustart wird der Job auf seinen letzten sicheren Checkpoint (einen `*_COMPLETE` oder `DISCOVERED`-Status) zurückgesetzt.
* Sind die maximalen Versuche (default: 5) erschöpft, wird der Job auf `FAILED` gesetzt.
* Jobs können bei inhaltlich kritischen oder unsicheren Metadaten auf `REVIEW_REQUIRED` gesetzt werden.

## Lease-Verhalten

Ein Job wird nicht permanent durch eine "Lock-Datei" blockiert. Stattdessen erwirbt ein Worker eine zeitlich begrenzte "Lease" (Standard: 10 Minuten).
Während diese Lease aktiv ist (überprüft über das Feld `lock_expires_at`), kann kein anderer Worker den Job bearbeiten.
Der Worker muss seine Lease verlängern, wenn die Verarbeitung länger als die Lease-Dauer benötigt.
Wenn der Worker abstürzt und die Lease abläuft, kann der Job von der Methode `release_expired_leases()` gefunden, auf den letzten sicheren Checkpoint zurückgesetzt und wieder zur Bearbeitung freigegeben werden.

Ein Worker, der versucht, einen Job fortzuschreiben, dessen Lease bereits abgelaufen und von einem anderen übernommen wurde, wird vom System abgewiesen.

## Retry-Formel

Das System verwendet exponentiellen Backoff bei fehlgeschlagenen Jobs. Das Delay nach dem `n`-ten Versuch berechnet sich wie folgt:
`min(30 * 2^(n - 1), 1800)` Sekunden.

Beispiel-Delays:
* 1. Fehler: 30 Sekunden
* 2. Fehler: 60 Sekunden
* 3. Fehler: 120 Sekunden
...
* 8+ Fehler: 1800 Sekunden (30 Minuten)

## Wiederaufnahme (Crash-Recovery)

Stürzt ein Worker im Zustand `*_RUNNING` ab, sorgt die Wiederaufnahme dafür, dass der Job nicht blind weiterverarbeitet wird. Das System setzt den Status auf den letzten sicheren Checkpoint (z.B. von `ANALYSIS_RUNNING` zurück auf `OCR_COMPLETE`). Dadurch bleiben persistierte Zwischenergebnisse (die vor dem Checkpoint gespeichert wurden) gültig, während der unterbrochene Schritt sauber von vorne begonnen wird.
