"""
Dokumenten- & Grenzerkennungs-Engine für VG Delikatessen.
Nutzt RAG und das lokale LLM, um Belege in PDF-Stapeln zu identifizieren und Daten im strikten JSON-Format zu extrahieren.
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional
from src.core.local_llm_client import default_llm_client, LocalLLMClient
from src.core.rag_engine import rag_engine
from src.core.persona_style import persona_engine

logger = logging.getLogger("Analyzer")


class DocumentAnalyzer:
    def __init__(self, llm_client: LocalLLMClient = default_llm_client):
        self.llm_client = llm_client

    def detect_boundaries(self, pages_info: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Ermittelt anhand von Heuristiken die logischen Beleggrenzen in einem Stapel.
        Gibt eine Liste von Dicts mit start_page und end_page zurück.
        """
        boundaries = []
        n_pages = len(pages_info)
        if n_pages == 0:
            return []

        # Sortiere nach Seitennummer
        pages_info = sorted(pages_info, key=lambda x: x["page_num"])
        current_start = pages_info[0]["page_num"]

        for idx in range(n_pages):
            page_num = pages_info[idx]["page_num"]
            text = pages_info[idx]["full_text"] or ""
            
            # Die allererste Seite in der Liste startet den ersten Beleg
            if idx == 0:
                continue

            # Heuristik 1: Ausschluss von Folgeseiten
            is_continuation = False
            continuation_patterns = [
                r"(?i)\b(seite|page|blatt)\s+([2-9]|\d{2,})\b",
                r"(?i)\bübertrag\b",
                r"(?i)\bfolgeseite\b",
                r"(?i)\bfortsetzung\b"
            ]
            for pattern in continuation_patterns:
                if re.search(pattern, text):
                    # Ausnahme: Falls auch "Seite 1" auftaucht, ist es kein klares Fortsetzungsblatt
                    if not (re.search(r"(?i)\b(seite|page)\s+1\b", text)):
                        is_continuation = True
                        break

            # Heuristik 2: Suche nach Startmarkern für neue Belege
            is_new_doc = False
            new_doc_patterns = [
                r"(?i)\b(rechnung|rechnungsnummer|rechnungs-nr|invoice|quittung|abrechnung)\b",
                r"(?i)\bseite\s+1\s+(von|of|/)\s+\d+\b",
                r"(?i)\bpage\s+1\s+(von|of|/)\s+\d+\b",
            ]
            
            # Ein neuer Beleg startet standardmäßig auf jeder Seite,
            # es sei denn, sie ist als Fortsetzungsblatt gekennzeichnet.
            if not is_continuation:
                is_new_doc = True

            # Bei Belegstart: Schließe vorherigen ab
            if is_new_doc:
                boundaries.append({"start_page": current_start, "end_page": page_num - 1})
                current_start = page_num

        # Letzten Beleg abschließen
        boundaries.append({"start_page": current_start, "end_page": pages_info[-1]["page_num"]})
        return boundaries

    def try_regex_extraction(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Versucht Datum, Lieferant und Bruttobetrag mittels regulärer Ausdrücke schnell auszulesen.
        Gibt ein Dict bei Erfolg zurück, andernfalls None.
        """
        # 1. Datum suchen (YYYY-MM-DD oder DD.MM.YYYY)
        date_str = None
        date_match = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
        if date_match:
            date_str = date_match.group(0)
        else:
            de_date_match = re.search(r"\b(\d{2})\.(\d{2})\.(\d{4})\b", text)
            if de_date_match:
                d, m, y = de_date_match.groups()
                date_str = f"{y}-{m}-{d}"
                
        # 2. Lieferant suchen
        known_suppliers = ["Metro", "Edeka", "Grossmarkt", "VG Delikatessen", "Metzgerei"]
        supplier = None
        for s in known_suppliers:
            if re.search(rf"\b{s}\b", text, re.IGNORECASE):
                supplier = s
                break
                
        # 3. Bruttobetrag suchen
        amount = None
        amount_patterns = [
            r"(?i)(?:gesamtbetrag|gesamt|summe|brutto|endbetrag|zahlbetrag)[^\d\n]*?(\d+[\.,]\d{2})\b",
            r"\b(\d+[\.,]\d{2})\s*(?:EUR|€)\b"
        ]
        for pattern in amount_patterns:
            match = re.search(pattern, text)
            if match:
                val_str = match.group(1).replace(",", ".")
                try:
                    amount = float(val_str)
                    break
                except ValueError:
                    pass
                    
        # Falls wesentliche Felder fehlen, abbrechen
        if not date_str or not supplier or not amount:
            return None
            
        # Steuersatz schätzen (7% vs 19%)
        steuer_satz = 19.0
        if "7%" in text or "7 %" in text or "steuer 7" in text.lower():
            steuer_satz = 7.0
            
        netto = round(amount / (1 + steuer_satz / 100.0), 2)
        steuer = round(amount - netto, 2)
        
        # Steuersatzkonto bestimmen
        if steuer_satz == 7.0:
            skr03 = "3400"
            skr04 = "5400"
        else:
            skr03 = "4900"
            skr04 = "6300"
            
        # 4. Belegtyp bestimmen
        belegtyp = "Rechnung"
        if re.search(r"(?i)\bangebot\b", text):
            belegtyp = "Angebot"
        elif re.search(r"(?i)\blieferschein\b", text):
            belegtyp = "Lieferschein"
        elif re.search(r"(?i)\bauftragsbestätigung\b", text) or re.search(r"(?i)\bbestellbestätigung\b", text):
            belegtyp = "Auftragsbestaetigung"
        elif re.search(r"(?i)\bmahnung\b", text):
            belegtyp = "Mahnung"
            
        return {
            "lieferant": supplier,
            "datum": date_str,
            "netto": netto,
            "steuer": steuer,
            "brutto": amount,
            "rechnungsnummer": "REG-EXPR",
            "confidence_score": 1.0,
            "warengruppe": "Fleischwaren" if steuer_satz == 7.0 else "Betriebsbedarf",
            "belegtyp": belegtyp,
            "steuersatz_prozent": steuer_satz,
            "skr03_konto": skr03,
            "skr04_konto": skr04,
            "validation_status": "PASSED"
        }

    def analyze_page_stack(self, pages_info: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Analysiert einen Stapel von PDF-Seiten, erkennt Beleggrenzen und extrahiert Rechnungsdaten.
        """
        boundaries = self.detect_boundaries(pages_info)
        logger.info(f"[Analyzer] Erkannte Beleggrenzen: {boundaries}")

        extracted_documents = []

        for bound in boundaries:
            start = bound["start_page"]
            end = bound["end_page"]
            
            # Mergen der Texte des aktuellen Belegs
            doc_pages = [p for p in pages_info if start <= p["page_num"] <= end]
            combined_text = ""
            for p in doc_pages:
                combined_text += f"\n--- SEITE {p['page_num']} ---\n" + (p['full_text'] or "")

            # 1. Regelbasierter Erstversuch via Regex
            regex_data = self.try_regex_extraction(combined_text)
            if regex_data:
                logger.info(f"[Analyzer] Regex-Extraktion erfolgreich für Seiten {start}-{end}")
                doc_data = regex_data
            else:
                # 2. KI-Fallback (LM-Manager Routing)
                logger.info(f"[Analyzer] Regex-Extraktion unvollständig für Seiten {start}-{end}. Starte KI-Fallback...")

                # RAG Suche nach bekannten Lieferanten und Kontenregeln
                rag_hits = rag_engine.search(combined_text[:500], top_k=2)
                rag_context = "\n".join([f"- {h['content']}" for h in rag_hits]) if rag_hits else "Keine spezifischen RAG-Muster."

                system_prompt = persona_engine.build_system_prompt("Beleg-Analyse & Grenzerkennung")
                user_prompt = f"""Du bist die Analyse-Engine für VG Delikatessen.
Analysiere folgenden Textauszug eines Belegs (Seiten {start} bis {end}) und extrahiere alle Rechnungsdaten im exakten JSON-Format.

### Bekannter RAG-Kontext:
{rag_context}

### Belegtext:
{combined_text[:4000]}

### Anforderung an das Ausgabe-JSON:
Antworte AUSSCHLIESSLICH mit einem validen JSON-Objekt folgender Struktur:
{{
  "lieferant": "Name des Lieferanten oder Ausstellers (z.B. Metro, Edeka, Grossmarkt)",
  "datum": "YYYY-MM-DD",
  "netto": 100.00,
  "steuer": 7.00,
  "brutto": 107.00,
  "rechnungsnummer": "RE-12345",
  "confidence_score": 0.98,
  "warengruppe": "Fleischwaren oder Betriebsbedarf",
  "belegtyp": "Rechnung, Angebot, Lieferschein, Auftragsbestaetigung, Mahnung oder Sonstiges"
}}

### Regeln zur Klassifizierung von 'belegtyp':
- "Rechnung": bei Rechnungen, Rechnungsbelegen, Fakturen, Gutschriften, Lastschriften.
- "Angebot": bei Angeboten, Kostenvoranschlägen, Offerten.
- "Lieferschein": bei Lieferscheinen, Wareneingangsdokumenten.
- "Auftragsbestaetigung": bei Auftragsbestätigungen, Bestellbestätigungen.
- "Mahnung": bei Mahnungen, Zahlungserinnerungen.
- "Sonstiges": bei Verträgen, Kontoauszügen, allgemeinen Anschreiben, etc.

Du musst versuchen, die Felder so genau wie möglich auszulesen. Falls ein Wert nicht gelesen werden kann, trage "UNKNOWN" ein (bei netto/steuer/brutto 0.0).
"""

                try:
                    raw_response = self.llm_client.generate_completion(
                        prompt=user_prompt,
                        system_prompt=system_prompt,
                        temperature=0.1,
                        json_mode=True
                    )
                    doc_data = self._parse_json_safe(raw_response)
                except Exception as e:
                    logger.error(f"[Analyzer] LLM-Analyse fehlgeschlagen für Seiten {start}-{end}: {e}")
                    doc_data = self._get_fallback_doc()

            doc_data["start_seite"] = start
            doc_data["end_seite"] = end
            extracted_documents.append(doc_data)

        return extracted_documents

    def _parse_json_safe(self, text: str) -> Dict[str, Any]:
        """Extrahiert ein JSON-Objekt sicher aus der LLM-Antwort."""
        res = None
        try:
            res = json.loads(text)
        except Exception:
            # Versuche JSON per RegEx zu finden
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    res = json.loads(match.group(0))
                except Exception:
                    pass

        if not res or not isinstance(res, dict):
            res = self._get_fallback_doc()

        # default values
        if "belegtyp" not in res:
            res["belegtyp"] = "Sonstiges"
        return res

    def _get_fallback_doc(self) -> Dict[str, Any]:
        return {
            "lieferant": "Unbekannter Lieferant",
            "datum": "2026-07-01",
            "netto": 0.0,
            "steuer": 0.0,
            "brutto": 0.0,
            "rechnungsnummer": "UNBEKANNT",
            "confidence_score": 0.50,
            "warengruppe": "Unbekannt",
            "belegtyp": "Sonstiges"
        }


# Globale Instanz
document_analyzer = DocumentAnalyzer()
