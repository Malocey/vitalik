# Privater Fernzugriff und Control Center

## Sicherheitsmodell

Das Dashboard lauscht ausschließlich auf `127.0.0.1:8000`. Tailscale Serve stellt
es privat per HTTPS im Tailnet bereit. Es gibt keine Router-Portfreigabe und keinen
Tailscale Funnel. Identitätsheader werden nur von einem Loopback-Proxy akzeptiert.
Der macOS-Dienst verwendet `REMOTE_ADMIN_USERS`, wenn die Variable beim Installieren
gesetzt ist. Ohne Vorgabe wird der Besitzer des lokalen Tailscale-Geräts verwendet.

Das Control Center unter `/admin` bietet:

- System-, Speicher-, RAG- und Jobstatus;
- LM-Studio-Workerstatus;
- redigierte, rotierende Logs;
- Pause, Fortsetzen und Freigabe abgelaufener Leases;
- kontrolliertes Retry finaler Review-/Fehlerjobs;
- separates Auditlog aller Verwaltungsaktionen.

Es gibt absichtlich keine beliebige Shell- oder Dateibrowser-Funktion. Scanpfade
sind auf `data/inbox`, `data/testdata` oder explizit konfigurierte
`REMOTE_SCAN_ROOTS` begrenzt. IBAN, E-Mail, USt-ID, Quellpfade und Checkpointdaten
werden nicht unmaskiert an den Browser ausgegeben.

## Automatische macOS-Installation

```bash
REMOTE_ADMIN_USERS="gdamien00@gmail.com" bash scripts/install_control_center_macos.sh
```

Das Skript installiert Python-Abhängigkeiten, erzeugt einen LaunchAgent, erkennt
den angemeldeten Tailscale-Besitzer, startet das Dashboard bei jeder Anmeldung und
aktiviert Tailscale Serve. Die persönliche Passkey-/Hardware-Key-Registrierung
bleibt eine einmalige Identitätsaktion im Tailscale-Konto.

Für den Zugriff von außen muss exakt diese Google-Identität Mitglied oder
freigegebener externer Nutzer des privaten Tailnets sein. Auf dem externen Gerät
wird Tailscale installiert und mit derselben Adresse angemeldet. Das Dashboard
bleibt über Tailscale Serve privat; Funnel und Router-Portfreigaben bleiben aus.

## Desktopzugriff

- macOS: Systemeinstellungen → Allgemein → Freigaben → Bildschirmfreigabe; nur
  den eigenen Verwaltungsbenutzer zulassen. Verbindung über MagicDNS mit der
  macOS-App „Bildschirmfreigabe“ oder einem vertrauenswürdigen VNC-Client.
- Windows: RDP mit Network Level Authentication aktivieren und ausschließlich über
  die Tailscale-IP beziehungsweise MagicDNS verwenden.
- Ports 5900 und 3389 niemals im Internetrouter weiterleiten.

Die Policy-Vorlage `config/tailscale-policy.example.hujson` beschränkt Control
Center, VNC/RDP und SSH auf den Admin, verlangt einen aktuellen stabilen
Tailscale-Client und erzwingt bei SSH jedes Mal eine erneute Anmeldung.

## Logdateien

- `data/logs/application.log`: rotierendes Anwendungslog
- `data/logs/admin_audit.jsonl`: redigiertes Verwaltungs-Auditlog
- `data/logs/control-center.stdout.log`: Dienst-Standardausgabe
- `data/logs/control-center.stderr.log`: Dienstfehler

Logs und Runtime-Zustände sind von Git ausgeschlossen.
