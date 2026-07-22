# Fünf-PDF-Praxistest vom 22. Juli 2026

## Umfang und Laufzeit

- 5 PDF-Dateien mit zusammen 474 Seiten
- Start: 12:21:55 Uhr
- Ende: 12:33:47 Uhr
- reale Gesamtdauer einschließlich Absturz und Wiederaufnahme: ca. 11 Minuten 51 Sekunden
- erster Lauf: nativer OCR-Absturz beim 132-Seiten-Stapel
- Fortsetzung: 9 Minuten 21 Sekunden mit `OCR_MAX_WORKERS=2`

## Ergebnis

- 4 PDFs wurden verarbeitet oder als vorhandene Dublette behandelt.
- 1 PDF blieb unverändert und erhielt einen sichtbaren Fehlerstatus.
- 57 Dokumentabschnitte wurden ausgegeben.
- 55 neue Belege wurden geschrieben; 2 Abschnitte wurden als bereits persistente
  MD5-Dubletten (`VG-0028`, `VG-0070`) wiederverwendet.
- Alle 55 neuen Belege besitzen SQLite-, FTS-, PDF-, Wiki- und OCR-Nachweise.
- Der vorbestehende Abstand von einem Datensatz zwischen `belege` und
  `belege_fts` blieb unverändert; kein neuer FTS-Ausfall kam hinzu.
- Alle 57 erfolgreichen Ergebniszeilen bestätigen einen RAG-Lesezugriff und
  die Persistenz.

## Ohne erfolgreiche KI-Hilfe erkannt

Mindestens 22 Abschnitte konnten deterministisch behandelt werden:

- 2 exakte MD5-Dubletten wurden ohne erneute Analyse wiederverwendet.
- 19 Commerzbank-Kontoauszüge wurden über die geschützte Dokumenttyp-Logik
  erkannt beziehungsweise sicher in die Bankdokument-Verarbeitung geleitet.
- 1 System-/Login-Dokument wurde als nicht buchbare Information erkannt.

Die lokale OCR selbst ist ebenfalls keine generative KI. Sie lieferte für viele
Scanseiten Text mit ungefähr 0,86 bis 0,95 Confidence.

## Qualitätsbefunde

1. Die Fast Lane schickt aktuell fast alle nicht geschützten Fälle weiterhin an
   das LLM. Der erhoffte KI-Einsparungseffekt ist noch zu klein.
2. Bei LLM-Ausfall werden Belege sichtbar als `EXTRACTION_FAILED` persistiert,
   der Quellstapel kann trotzdem `Done_` erhalten. Fachlicher Erfolg und reine
   Persistenz müssen getrennt werden.
3. Der erste Stapel erzeugte 23 `EXTRACTION_FAILED`-Ergebnisse und viele
   unbekannte Lieferanten. Er ist technisch gespeichert, aber fachlich nicht
   abgenommen.
4. Ein nativer OCR-Absturz hinterließ eine verwaiste Ordnersperre. Die
   Wiederaufnahme funktionierte erst nach geprüfter Entfernung der Sperre.
5. Die vollständige Dubletten-PDF wurde erst nach OCR und Zerlegung erkannt.
   Eine Datei-MD5-Prüfung vor OCR würde mehrere Minuten sparen.
6. Weil das passende `Done_`-Ziel schon existierte, blieb die Dubletten-Quelldatei
   zusätzlich liegen. Sie würde beim nächsten Ordnerlauf erneut geprüft.
7. `Epson_26052026235058.pdf` konnte auf allen 110 Seiten von PDFium nicht
   gerendert werden. Die Datei blieb unverändert und wurde korrekt als Fehler in
   der CSV protokolliert.

## Technische Absicherung während des Tests

Die OCR-Parallelität ist nun über `OCR_MAX_WORKERS` konfigurierbar und standardmäßig
auf vier statt acht native Worker begrenzt. Der vollständige Projekttest danach
ergab **173 bestandene Tests**.

