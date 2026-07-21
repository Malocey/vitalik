"""
Persona- und Schreibstil-Engine für Vitalik / VG Delikatessen.
Verknüpft geschäftliche und private Kontextdaten mit Vitaliks individuellem Schreibstil.
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional
from config import PERSONA_PROFILE_FILE
from src.core.rag_engine import rag_engine


class PersonaStyleEngine:
    def __init__(self, profile_file: Path = PERSONA_PROFILE_FILE):
        self.profile_file = profile_file
        self.profile = self._load_profile()

    def _load_profile(self) -> Dict[str, Any]:
        if self.profile_file.exists():
            try:
                with open(self.profile_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass

        default_profile = {
            "name": "Vitalik",
            "unternehmen": "VG Delikatessen",
            "tonalitaet": "Pragmatisch, direkt, qualitätsbewusst, gastfreundlich",
            "schreibstil_merkmale": [
                "Kurze, präzise Sätze",
                "Kombiniert professionelle kaufmännische Details mit persönlichem Feinkost-Bezug",
                "Nutzt bei Bestätigungen klare Freigabe-Formulierungen"
            ],
            "private_und_geschaeftliche_notizen": [
                "Legt höchsten Wert auf frische und authentische Qualität bei Delikatessen",
                "Verbindet persönliche Leidenschaft für Feinkost mit effizienter Buchhaltung"
            ]
        }
        self._save_profile(default_profile)
        return default_profile

    def _save_profile(self, profile_data: Dict[str, Any]):
        with open(self.profile_file, "w", encoding="utf-8") as f:
            json.dump(profile_data, f, ensure_ascii=False, indent=2)

    def update_profile(self, new_notes: str, new_style_rules: Optional[list] = None):
        if new_notes:
            self.profile["private_und_geschaeftliche_notizen"].append(new_notes)
        if new_style_rules:
            self.profile["schreibstil_merkmale"].extend(new_style_rules)
        self._save_profile(self.profile)

    def build_system_prompt(self, task_context: str = "") -> str:
        """
        Baut den maßgeschneiderten System-Prompt für das LLM,
        inklusive Vitaliks Schreibstil und RAG-Kontext.
        """
        # Hole relevante RAG-Informationen
        rag_hits = rag_engine.search(f"Schreibstil Vitalik VG Delikatessen {task_context}", top_k=2)
        rag_context_str = "\n".join([f"- {h['content']}" for h in rag_hits]) if rag_hits else "Kein zusätzlicher RAG-Kontext."

        prompt = f"""Du bist der KI-Betriebsassistent des maßgeschneiderten Betriebssystems von VG Delikatessen.
Du agierst exakt im Sinne und Schreibstil von {self.profile.get('name')} ({self.profile.get('unternehmen')}).

### Persona & Tonalität:
- Tonalität: {self.profile.get('tonalitaet')}
- Schreibstil-Merkmale: {', '.join(self.profile.get('schreibstil_merkmale', []))}

### Verbindender Kontext (Geschäftlich & Privat):
{chr(10).join(['- ' + n for n in self.profile.get('private_und_geschaeftliche_notizen', [])])}

### RAG Wissenskontext:
{rag_context_str}

Beantworte alle Fragen und generiere alle Nachrichten strikt in diesem Schreibstil.
"""
        return prompt


# Globale Persona-Instanz
persona_engine = PersonaStyleEngine()
