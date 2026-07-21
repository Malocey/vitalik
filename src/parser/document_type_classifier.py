import re
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

@dataclass
class Evidence:
    signal: str
    source_text: str
    weight: float

@dataclass
class ClassificationResult:
    document_type: str
    confidence: float
    automatic_booking_allowed: bool
    positive_evidence: List[Dict[str, Any]]
    negative_evidence: List[Dict[str, Any]]
    conflicting_types: List[Dict[str, Any]]
    status: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_type": self.document_type,
            "confidence": round(self.confidence, 4),
            "automatic_booking_allowed": self.automatic_booking_allowed,
            "positive_evidence": self.positive_evidence,
            "negative_evidence": self.negative_evidence,
            "conflicting_types": self.conflicting_types,
            "status": self.status,
        }

class DocumentTypeClassifier:

    # Document Types
    TYPE_RECHNUNG = "Rechnung"
    TYPE_GUTSCHRIFT = "Gutschrift"
    TYPE_STORNO = "Stornorechnung"
    TYPE_LIEFERSCHEIN = "Lieferschein"
    TYPE_ANGEBOT = "Angebot"
    TYPE_AUFTRAGSBESTAETIGUNG = "Auftragsbestaetigung"
    TYPE_MAHNUNG = "Mahnung"
    TYPE_ZAHLUNGSERINNERUNG = "Zahlungserinnerung"
    TYPE_KONTOAUSZUG = "Kontoauszug"
    TYPE_BANKDOKUMENT = "Bankdokument"
    TYPE_KASSENBON = "Kassenbon"
    TYPE_TANKBELEG = "Tankbeleg"
    TYPE_VERTRAG = "Vertrag"
    TYPE_VERSICHERUNG = "Versicherung"
    TYPE_STEUERBESCHEID = "Steuerbescheid"
    TYPE_SONSTIGES = "Sonstiges"
    TYPE_UNLESBAR = "Unlesbar"

    # Status
    STATUS_CLASSIFIED = "CLASSIFIED"
    STATUS_INSUFFICIENT_TEXT = "INSUFFICIENT_TEXT"
    STATUS_AMBIGUOUS = "AMBIGUOUS"

    def __init__(self):
        # Weights Definitions
        self.STRONG_WEIGHT = 0.8
        self.MEDIUM_WEIGHT = 0.4
        self.WEAK_WEIGHT = 0.2

        # Signals mapping: Type -> {'positive': {signal: weight, ...}, 'negative': {signal: weight, ...}}
        self.SIGNALS = {
            self.TYPE_RECHNUNG: {
                "positive": {
                    r"\brechnung(?!sadresse|\s*nr|\s*nummer)\b": self.WEAK_WEIGHT,
                    r"\brechnungs-?nr\.?\b": self.STRONG_WEIGHT,
                    r"\brechnungsnummer\b": self.STRONG_WEIGHT,
                    r"\brechnungsbetrag\b": self.STRONG_WEIGHT,
                    r"\brechnungsdatum\b": self.MEDIUM_WEIGHT,
                    r"\bzu zahlen\b": self.MEDIUM_WEIGHT,
                    r"\bf[aä]llig bis\b": self.MEDIUM_WEIGHT,
                    r"\bumsatzsteuer\b": self.WEAK_WEIGHT,
                },
                "negative": {
                    r"\bgutschrift\b": self.STRONG_WEIGHT,
                    r"\bstornorechnung\b": self.STRONG_WEIGHT,
                    r"\bstorno\b": self.STRONG_WEIGHT,
                    r"\blieferschein\b": self.STRONG_WEIGHT,
                    r"\bangebot\b": self.STRONG_WEIGHT,
                    r"\bmahnung\b": self.STRONG_WEIGHT,
                    r"\bzahlungserinnerung\b": self.STRONG_WEIGHT,
                    r"\bauftragsbest[aä]tigung\b": self.STRONG_WEIGHT,
                    r"\bversicherung\b": self.STRONG_WEIGHT,
                    r"\bvertrag\b": self.STRONG_WEIGHT,
                }
            },
            self.TYPE_GUTSCHRIFT: {
                "positive": {
                    r"\bgutschrift\b": self.STRONG_WEIGHT,
                    r"\bgutschriftsbetrag\b": self.STRONG_WEIGHT,
                    r"\bgutschriftsnummer\b": self.STRONG_WEIGHT,
                    r"\bwir schreiben.*gut\b": self.STRONG_WEIGHT,
                },
                "negative": {
                    r"\bmahnung\b": self.STRONG_WEIGHT,
                }
            },
            self.TYPE_STORNO: {
                "positive": {
                    r"\bstorno\b": self.STRONG_WEIGHT,
                    r"\bstornierung\b": self.STRONG_WEIGHT,
                    r"\bstornorechnung\b": self.STRONG_WEIGHT,
                },
                "negative": {}
            },
            self.TYPE_LIEFERSCHEIN: {
                "positive": {
                    r"\blieferschein\b": self.STRONG_WEIGHT,
                    r"\blieferschein-?nr\.?\b": self.STRONG_WEIGHT,
                    r"\blieferdatum\b": self.MEDIUM_WEIGHT,
                    r"\bwareneingang\b": self.MEDIUM_WEIGHT,
                    r"\bpackliste\b": self.MEDIUM_WEIGHT,
                },
                "negative": {
                    r"\bzu zahlen\b": self.STRONG_WEIGHT,
                    r"\brechnungs-?nr\.?\b": self.STRONG_WEIGHT,
                    r"\brechnungsnummer\b": self.STRONG_WEIGHT,
                    r"\brechnungsbetrag\b": self.STRONG_WEIGHT,
                }
            },
            self.TYPE_ANGEBOT: {
                "positive": {
                    r"\bangebot\b": self.STRONG_WEIGHT,
                    r"\bangebotsnummer\b": self.STRONG_WEIGHT,
                    r"\bunverbindliches angebot\b": self.STRONG_WEIGHT,
                    r"\bkostenvoranschlag\b": self.STRONG_WEIGHT,
                },
                "negative": {
                    r"\brechnungs-?nr\.?\b": self.STRONG_WEIGHT,
                    r"\bauftragsbest[aä]tigung\b": self.STRONG_WEIGHT,
                }
            },
            self.TYPE_AUFTRAGSBESTAETIGUNG: {
                "positive": {
                    r"\bauftragsbest[aä]tigung\b": self.STRONG_WEIGHT,
                    r"\bbestellbest[aä]tigung\b": self.STRONG_WEIGHT,
                    r"\bauftrag best[aä]tigen\b": self.MEDIUM_WEIGHT,
                },
                "negative": {
                    r"\bangebot\b": self.STRONG_WEIGHT,
                    r"\brechnung\b": self.WEAK_WEIGHT,
                }
            },
            self.TYPE_MAHNUNG: {
                "positive": {
                    r"\bmahnung\b": self.STRONG_WEIGHT,
                    r"\bmahnstufe\b": self.STRONG_WEIGHT,
                    r"\bmahngeb[uü]hr\b": self.STRONG_WEIGHT,
                    r"\bletzte aufforderung\b": self.STRONG_WEIGHT,
                    r"\bzahlungserinnerung\b": self.WEAK_WEIGHT,
                },
                "negative": {
                    r"\bgutschrift\b": self.STRONG_WEIGHT,
                }
            },
            self.TYPE_ZAHLUNGSERINNERUNG: {
                "positive": {
                    r"\bzahlungserinnerung\b": self.STRONG_WEIGHT,
                    r"\berinnerung\b": self.MEDIUM_WEIGHT,
                },
                "negative": {
                    r"\bmahnung\b": self.STRONG_WEIGHT,
                }
            },
            self.TYPE_KONTOAUSZUG: {
                "positive": {
                    r"\bkontoauszug\b": self.STRONG_WEIGHT,
                    r"\bauszug-?nr\.?\b": self.STRONG_WEIGHT,
                    r"\bbuchungsdatum\b": self.STRONG_WEIGHT,
                    r"\bsoll\s*/\s*haben\b": self.STRONG_WEIGHT,
                    r"\balter kontostand\b": self.MEDIUM_WEIGHT,
                    r"\bneuer kontostand\b": self.MEDIUM_WEIGHT,
                },
                "negative": {
                    r"\brechnungs-?nr\.?\b": self.STRONG_WEIGHT,
                }
            },
            self.TYPE_BANKDOKUMENT: {
                "positive": {
                    r"\bbankdokument\b": self.WEAK_WEIGHT,
                    r"\bkonto\s?nr\.?\b": self.MEDIUM_WEIGHT,
                    r"\biban\b": self.MEDIUM_WEIGHT,
                    r"\bbedingungen f[uü]r den zahlungsverkehr\b": self.STRONG_WEIGHT,
                    r"\beinlagensicherungsfonds\b": self.STRONG_WEIGHT,
                    r"\bbankverbindung\b": self.WEAK_WEIGHT,
                },
                "negative": {}
            },
            self.TYPE_KASSENBON: {
                "positive": {
                    r"\bkassenbon\b": self.STRONG_WEIGHT,
                    r"\bquittung\b": self.MEDIUM_WEIGHT,
                    r"\bbar\b": self.WEAK_WEIGHT,
                    r"\bgegeben\b": self.WEAK_WEIGHT,
                    r"\br[uü]ckgeld\b": self.WEAK_WEIGHT,
                    r"\bbon-?nr\.?\b": self.STRONG_WEIGHT,
                },
                "negative": {}
            },
            self.TYPE_TANKBELEG: {
                "positive": {
                    r"\btankbeleg\b": self.STRONG_WEIGHT,
                    r"\btankstelle\b": self.WEAK_WEIGHT,
                    r"\bliter\b": self.WEAK_WEIGHT,
                    r"\bkraftstoff\b": self.MEDIUM_WEIGHT,
                    r"\bzapfs[aä]ule\b": self.MEDIUM_WEIGHT,
                    r"\bpreis je liter\b": self.MEDIUM_WEIGHT,
                    r"\bsuper( e10| e5| 95| plus)?\b": self.MEDIUM_WEIGHT,
                    r"\bdiesel\b": self.WEAK_WEIGHT,
                },
                "negative": {}
            },
            self.TYPE_VERTRAG: {
                "positive": {
                    r"\bvertrag\b": self.STRONG_WEIGHT,
                    r"\bvertragsnummer\b": self.STRONG_WEIGHT,
                    r"\bvertragsbeginn\b": self.STRONG_WEIGHT,
                    r"\bmietvertrag\b": self.STRONG_WEIGHT,
                    r"\bdarlehensvertrag\b": self.STRONG_WEIGHT,
                    r"\bunterschrift\b": self.WEAK_WEIGHT,
                },
                "negative": {}
            },
            self.TYPE_VERSICHERUNG: {
                "positive": {
                    r"\bversicherung\b": self.STRONG_WEIGHT,
                    r"\bversicherungsschein\b": self.STRONG_WEIGHT,
                    r"\bversicherungsnummer\b": self.STRONG_WEIGHT,
                    r"\bpolice\b": self.STRONG_WEIGHT,
                },
                "negative": {}
            },
            self.TYPE_STEUERBESCHEID: {
                "positive": {
                    r"\bsteuerbescheid\b": self.STRONG_WEIGHT,
                    r"\bfon\b": self.WEAK_WEIGHT, # Finanzamt
                    r"\bfinanzamt\b": self.STRONG_WEIGHT,
                    r"\bsteuernummer\b": self.MEDIUM_WEIGHT,
                    r"\beinkommensteuer\b": self.STRONG_WEIGHT,
                    r"\bsteuererkl[aä]rung\b": self.STRONG_WEIGHT,
                },
                "negative": {}
            },
            self.TYPE_SONSTIGES: {
                "positive": {},
                "negative": {}
            }
        }

    def _normalize_text(self, text: str) -> str:
        # Lowercase for case-insensitive matching
        text = text.lower()
        # Common OCR fixes
        text = text.replace("kontoauszvg", "kontoauszug")
        text = text.replace("rechnungs-nr", "rechnungsnummer")
        text = text.replace("rechnungs nr", "rechnungsnummer")
        text = text.replace("rn.", "rechnungsnummer")
        return text

    def _check_insufficient_text(self, text: str, ocr_quality: Optional[float] = None) -> bool:
        if not text or not text.strip():
            return True

        # Check alphanumeric characters count
        alphanumeric_count = sum(1 for c in text if c.isalnum())
        if alphanumeric_count < 20:
            return True

        # Check meaningful words count (words with at least 3 letters)
        words = re.findall(r'\b[a-zA-ZäöüÄÖÜß]{3,}\b', text)
        if len(words) < 3:
            return True

        # Consider optional OCR quality if provided
        if ocr_quality is not None and ocr_quality < 0.2:
            # If the OCR quality is exceptionally low, treat it as insufficient text
            return True

        return False

    def _check_tankbeleg_combination(self, text: str) -> Optional[float]:
        # Tankbeleg combination logic
        tankbeleg_signals = [
            r"\btankstelle\b",
            r"\bliter\b",
            r"(kraftstoff|super|diesel)",
            r"\bzapfs[aä]ule\b",
            r"\bpreis je liter\b",
            r"\bgesamtbetrag\b"
        ]

        matches = 0
        for pattern in tankbeleg_signals:
            if re.search(pattern, text):
                matches += 1

        if matches >= 3:
            return min(1.0, matches * 0.25)
        return None

    def classify(self, text: str, pages: Optional[int] = None, ocr_quality: Optional[float] = None) -> Dict[str, Any]:
        normalized_text = self._normalize_text(text)

        # 1. Check for insufficient text
        if self._check_insufficient_text(normalized_text, ocr_quality):
            return ClassificationResult(
                document_type=self.TYPE_UNLESBAR,
                confidence=1.0,
                automatic_booking_allowed=False,
                positive_evidence=[],
                negative_evidence=[],
                conflicting_types=[],
                status=self.STATUS_INSUFFICIENT_TEXT
            ).to_dict()

        # 2. Score calculation
        scores = {}
        evidences = {}

        for doc_type, rules in self.SIGNALS.items():
            pos_score = 0.0
            neg_score = 0.0
            pos_evidence = []
            neg_evidence = []

            for pattern, weight in rules.get("positive", {}).items():
                if match := re.search(pattern, normalized_text):
                    pos_score += weight
                    pos_evidence.append({
                        "signal": pattern.replace('\\b', '').replace('\\s*', ' ').replace('\\.?', '.').replace('?', '').strip('\\/'),
                        "source_text": match.group(0),
                        "weight": weight
                    })

            for pattern, weight in rules.get("negative", {}).items():
                if match := re.search(pattern, normalized_text):
                    neg_score += weight
                    neg_evidence.append({
                        "signal": pattern.replace('\\b', '').replace('\\s*', ' ').replace('\\.?', '.').replace('?', '').strip('\\/'),
                        "source_text": match.group(0),
                        "weight": weight
                    })

            # Special Tankbeleg combinations
            if doc_type == self.TYPE_TANKBELEG:
                tank_score = self._check_tankbeleg_combination(normalized_text)
                if tank_score:
                    pos_score += tank_score
                    pos_evidence.append({
                        "signal": "Tankbeleg Kombinationssignale",
                        "source_text": "Kombination aus Tankstelle, Liter, Kraftstoff etc.",
                        "weight": tank_score
                    })

            # Bankdokument protection
            if doc_type in [self.TYPE_KONTOAUSZUG, self.TYPE_BANKDOKUMENT]:
                 # These naturally accrue score if the keywords match, which prevents automatic booking later
                 pass

            score = max(0.0, min(1.0, pos_score - neg_score))
            scores[doc_type] = score
            evidences[doc_type] = {"pos": pos_evidence, "neg": neg_evidence}

        # Ensure Sonstiges has a baseline score if nothing else matches well
        if not any(s > 0 for s in scores.values()):
            scores[self.TYPE_SONSTIGES] = 0.1

        # 3. Determine best types
        sorted_types = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        best_type, best_score = sorted_types[0]

        # 4. Check for ambiguity
        is_ambiguous = False
        conflicting_types = []
        if len(sorted_types) > 1:
            second_best_type, second_best_score = sorted_types[1]
            if best_score > 0 and (best_score - second_best_score) < 0.15 and second_best_score > 0:
                is_ambiguous = True
                conflicting_types = [
                    {"document_type": best_type, "score": round(best_score, 4)},
                    {"document_type": second_best_type, "score": round(second_best_score, 4)}
                ]

        # Ensure that if it is ambiguous, document_type is the best scored one

        # 5. Determine automatic booking allowed
        automatic_booking_allowed = False
        status = self.STATUS_CLASSIFIED

        if is_ambiguous:
            status = self.STATUS_AMBIGUOUS
        else:
            if best_type in [self.TYPE_RECHNUNG, self.TYPE_GUTSCHRIFT] and best_score >= 0.90:
                # Check for blocking signals for automatic booking
                has_blocking_signals = False
                blocking_types = [
                    self.TYPE_KONTOAUSZUG, self.TYPE_BANKDOKUMENT,
                    self.TYPE_VERTRAG, self.TYPE_ANGEBOT,
                    self.TYPE_LIEFERSCHEIN, self.TYPE_MAHNUNG
                ]
                for b_type in blocking_types:
                    if scores.get(b_type, 0.0) > 0.1: # Even weak presence blocks
                        has_blocking_signals = True
                        break

                if not has_blocking_signals:
                    automatic_booking_allowed = True

        return ClassificationResult(
            document_type=best_type,
            confidence=best_score,
            automatic_booking_allowed=automatic_booking_allowed,
            positive_evidence=evidences[best_type]["pos"],
            negative_evidence=evidences[best_type]["neg"],
            conflicting_types=conflicting_types,
            status=status
        ).to_dict()
