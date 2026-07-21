# Synthetische Beleg-Fixtures

Diese Dateien enthalten ausschließlich erfundene Daten und dürfen in Offline-Tests
verwendet werden. Die Textdatei bildet bereits extrahierten OCR-Text mit Seitenmarkern
ab; die zugehörige JSON-Datei enthält die erwarteten Ergebnisse.

Produktionscode darf Fixture-Werte niemals als Fallback verwenden. Tests müssen
Fixtures ausdrücklich laden und Ergebnisse als synthetisch kennzeichnen.
