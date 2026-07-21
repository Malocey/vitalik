"""
Dreistufiger Schutzschild & Steuer-Mapping für VG Delikatessen.
Garantierte mathematische Korrektheit, Qualitätsprüfung und Kontenrahmen-Mapping für sevDesk.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, Tuple
from config import SKR_MAPPING_FILE

logger = logging.getLogger("ValidationShield")


class ValidationShield:
    def __init__(self, skr_mapping_file: Path = SKR_MAPPING_FILE):
        self.skr_mapping_file = skr_mapping_file
        self.skr_mapping = self._load_skr_mapping()

    def _load_skr_mapping(self) -> Dict[str, Any]:
        if self.skr_mapping_file.exists():
            try:
                with open(self.skr_mapping_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def validate_document(self, doc_data: Dict[str, Any]) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Führt den 3-stufigen Schutzschild aus:
        1. Mathematische Validierung: Netto + Steuer == Brutto
        2. Confidence-Score Check: >= 0.95 (95%)
        3. SKR03/SKR04 Steuer-Mapping
        
        Rückgabe: (passed: bool, status_reason: str, enriched_doc_data: dict)
        """
        netto = float(doc_data.get("netto", 0.0))
        steuer = float(doc_data.get("steuer", 0.0))
        brutto = float(doc_data.get("brutto", 0.0))
        confidence = float(doc_data.get("confidence_score", 0.0))

        # Stufe 1: Mathematische Validierung (Toleranz 0.01 € für Rundungsdifferenzen)
        math_diff = abs((netto + steuer) - brutto)
        if math_diff > 0.01:
            reason = f"Mathematischer Rechenfehler: Netto ({netto:.2f}) + Steuer ({steuer:.2f}) != Brutto ({brutto:.2f}) [Abweichung: {math_diff:.2f} €]"
            doc_data["validation_status"] = "MANUAL_REVIEW_NEEDED"
            doc_data["validation_reason"] = reason
            return False, reason, doc_data

        # Stufe 2: Confidence-Score Barriere
        if confidence < 0.95:
            reason = f"Confidence-Score zu gering: {confidence*100:.1f}% (Erforderlich: >= 95.0%)"
            doc_data["validation_status"] = "MANUAL_REVIEW_NEEDED"
            doc_data["validation_reason"] = reason
            return False, reason, doc_data

        # Stufe 3: Steuer-Mapping (SKR03 / SKR04)
        warengruppe = doc_data.get("warengruppe", "").lower()
        if "fleisch" in warengruppe or "lebensmittel" in warengruppe or steuer == 7.0:
            doc_data["skr03_konto"] = self.skr_mapping.get("SKR03", {}).get("lebensmittel_fleisch_7", {}).get("kontonummer", "3400")
            doc_data["skr04_konto"] = self.skr_mapping.get("SKR04", {}).get("lebensmittel_fleisch_7", {}).get("kontonummer", "5400")
            doc_data["steuersatz_prozent"] = 7.0
        else:
            doc_data["skr03_konto"] = self.skr_mapping.get("SKR03", {}).get("betriebsbedarf_reinigung_19", {}).get("kontonummer", "4900")
            doc_data["skr04_konto"] = self.skr_mapping.get("SKR04", {}).get("betriebsbedarf_reinigung_19", {}).get("kontonummer", "6300")
            doc_data["steuersatz_prozent"] = 19.0

        doc_data["validation_status"] = "PASSED"
        doc_data["validation_reason"] = "Alle 3 Sicherheitsbarrieren erfolgreich bestanden."
        return True, "Erfolgreich validiert", doc_data


# Globale Instanz
validation_shield = ValidationShield()
