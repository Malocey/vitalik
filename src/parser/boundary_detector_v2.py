import re
from typing import List, Dict, Any

# --- Regex Patterns (German & English) ---
# Positive signals for a new document
PATTERN_PAGE_1_OF_N = re.compile(r'(?i)(?:seite|page|blatt)\s*1\s*(?:von|of|/)\s*\d+')
PATTERN_INVOICE_HEADER = re.compile(r'(?i)\b(?:rechnung|invoice|gutschrift|lieferschein|mahnung)\b')
PATTERN_INVOICE_NUM = re.compile(r'(?i)(?:rechnungs-?nr\.?|rechnungsnummer|invoice\s*no\.?|beleg-?nr\.?)\s*[:]?\s*([\w\-\/]+)')
PATTERN_CUSTOMER_NUM = re.compile(r'(?i)(?:kunden-?nr\.?|kundennummer|customer\s*no\.?)\s*[:]?\s*([\w\-\/]+)')
PATTERN_DATE = re.compile(r'(?i)(?:datum|date|rechnungsdatum)\s*[:]?\s*\d{1,2}[\./\-]\d{1,2}[\./\-]\d{2,4}')
PATTERN_TOTAL_AMOUNT = re.compile(r'(?i)(?:gesamtbetrag|rechnungsbetrag|zahlbetrag|total\s*amount)\s*[:]?\s*[\d\.\,]+\s*(?:€|eur|usd|\$)?')

# Continuation signals
PATTERN_PAGE_X_OF_N = re.compile(r'(?i)(?:seite|page|blatt)\s*([2-9]|\d{2,})\s*(?:von|of|/)\s*\d+')
PATTERN_CONTINUATION = re.compile(r'(?i)\b(?:übertrag|fortsetzung|continued)\b')

class BoundaryDetectorV2:
    def __init__(self):
        pass

    def _clean_text(self, text: str) -> str:
        return text.strip() if text else ""

    def _count_alnum(self, text: str) -> int:
        return sum(c.isalnum() for c in text)

    def _count_words(self, text: str) -> int:
        words = [w for w in text.split() if len(w) > 1 and any(c.isalnum() for c in w)]
        return len(words)

    def _is_insufficient_text(self, text: str) -> bool:
        if not text:
            return True
        alnum_count = self._count_alnum(text)
        word_count = self._count_words(text)

        if alnum_count < 20 or word_count < 3:
            return True
        return False

    def _extract_invoice_number(self, text: str) -> str:
        match = PATTERN_INVOICE_NUM.search(text)
        return match.group(1).lower() if match else ""

    def _extract_customer_number(self, text: str) -> str:
        match = PATTERN_CUSTOMER_NUM.search(text)
        return match.group(1).lower() if match else ""

    def _check_page_n_of_n(self, text: str) -> bool:
        match = re.search(r'(?i)(?:seite|page|blatt)\s*(\d+)\s*(?:von|of|/)\s*(\d+)', text)
        if match:
            return match.group(1) == match.group(2)
        return False

    def _check_page_1_of_n(self, text: str) -> bool:
        return bool(PATTERN_PAGE_1_OF_N.search(text))

    def detect(self, pages: List[Dict[str, Any]]) -> Dict[str, Any]:
        result = {
            "documents": [],
            "transitions": [],
            "unassigned_pages": []
        }

        if not pages:
            return result

        # 1. Sort pages and check for duplicates
        sorted_pages = sorted(pages, key=lambda x: x.get("page_num", 0))
        seen_pages = set()
        for p in sorted_pages:
            p_num = p.get("page_num")
            if p_num is None:
                continue
            if p_num in seen_pages:
                raise ValueError(f"Duplicate page number found: {p_num}")
            seen_pages.add(p_num)

        # 2. Check for missing page numbers (gaps)
        page_nums = [p.get("page_num") for p in sorted_pages if p.get("page_num") is not None]
        has_missing_pages = False
        if len(page_nums) > 1:
            for i in range(1, len(page_nums)):
                if page_nums[i] - page_nums[i-1] > 1:
                    has_missing_pages = True
                    break

        # 3. Pre-process pages: identify unassigned/separators
        processed_pages = []
        unassigned = []

        for i, p in enumerate(sorted_pages):
            text = self._clean_text(p.get("full_text", ""))
            p_num = p.get("page_num")

            if self._is_insufficient_text(text):
                alnum = self._count_alnum(text)
                # Is it a completely blank page?
                if alnum == 0:
                     classification = "SEPARATOR_PAGE"
                     reason = "Empty page"
                # Is it a blank backside?
                elif i > 0 and not self._is_insufficient_text(self._clean_text(sorted_pages[i-1].get("full_text", ""))):
                     classification = "BLANK_BACKSIDE"
                     reason = "Almost empty page following a content page"
                else:
                     classification = "SEPARATOR_PAGE"
                     reason = "Less than 20 alphanumeric characters or less than 3 words"

                unassigned_page = {
                    "page_num": p_num,
                    "classification": classification,
                    "reason": reason,
                    "confidence": 0.98
                }
                unassigned.append(unassigned_page)
                processed_pages.append({"page": p, "is_unassigned": True, "classification": classification})
            else:
                processed_pages.append({"page": p, "is_unassigned": False})

        result["unassigned_pages"] = unassigned

        documents = []
        transitions = []

        def finalize_document(start_idx: int, end_idx: int, start_conf: float, end_conf: float, cont_conf: float, cont_count: int):
            doc_pages = [pp["page"]["page_num"] for pp in processed_pages[start_idx:end_idx+1] if not pp["is_unassigned"]]
            if not doc_pages:
                return

            final_cont_conf = cont_conf / max(1, cont_count) if cont_count > 0 else 0.8
            overall_conf = 0.4 * start_conf + 0.4 * end_conf + 0.2 * final_cont_conf

            warnings = []
            if has_missing_pages:
                warnings.append("MISSING_PAGE_NUMBERS")

            documents.append({
                "start_page": doc_pages[0],
                "end_page": doc_pages[-1],
                "confidence": min(1.0, overall_conf),
                "start_reasons": [],
                "continuation_reasons": [],
                "warnings": warnings,
                "_internal_pages": doc_pages # for invariant check
            })

        # Find first content page
        start_idx = 0
        while start_idx < len(processed_pages) and processed_pages[start_idx]["is_unassigned"]:
            start_idx += 1

        if start_idx >= len(processed_pages):
            self._verify_invariant(sorted_pages, unassigned, documents)
            return result

        current_doc_start_idx = start_idx
        prev_content_idx = start_idx

        doc_continuation_confidence = 0.0
        continuation_signal_count = 0
        last_start_transition_conf = 0.8 # Neutral for first doc

        for i in range(start_idx + 1, len(processed_pages)):
            curr_p = processed_pages[i]
            if curr_p["is_unassigned"]:
                continue

            prev_p = processed_pages[prev_content_idx]

            curr_text = self._clean_text(curr_p["page"].get("full_text", ""))
            prev_text = self._clean_text(prev_p["page"].get("full_text", ""))

            pos_signals = []
            neg_signals = []
            pos_weight = 0.0
            neg_weight = 0.0

            # Positive signals
            if self._check_page_1_of_n(curr_text):
                pos_signals.append("Seite 1 von N")
                pos_weight += 0.6

            curr_inv_num = self._extract_invoice_number(curr_text)
            prev_inv_num = self._extract_invoice_number(prev_text)
            if curr_inv_num and prev_inv_num and curr_inv_num != prev_inv_num:
                pos_signals.append("Neue Rechnungsnummer")
                pos_weight += 0.8

            if PATTERN_INVOICE_HEADER.search(curr_text) and not PATTERN_INVOICE_HEADER.search(prev_text):
                pos_signals.append("Neuer Dokumentkopf")
                pos_weight += 0.5

            if PATTERN_DATE.search(curr_text) and not PATTERN_DATE.search(prev_text):
                pos_signals.append("Neues Rechnungsdatum")
                pos_weight += 0.3

            if self._check_page_n_of_n(prev_text):
                pos_signals.append("Vorherige Seite ist Seite N von N")
                pos_weight += 0.7

            if PATTERN_TOTAL_AMOUNT.search(prev_text):
                pos_signals.append("Vorheriges Dokument endet mit Gesamtbetrag")
                pos_weight += 0.4

            has_separator = any(processed_pages[sep_idx]["classification"] == "SEPARATOR_PAGE"
                                for sep_idx in range(prev_content_idx + 1, i)
                                if processed_pages[sep_idx]["is_unassigned"])
            if has_separator:
                pos_signals.append("Leerseite zwischen Dokumenten")
                pos_weight += 0.5

            # Negative/Continuation signals
            if PATTERN_PAGE_X_OF_N.search(curr_text):
                neg_signals.append("Seite X von N")
                neg_weight += 0.6

            if PATTERN_CONTINUATION.search(curr_text):
                neg_signals.append("Übertrag / Fortsetzung")
                neg_weight += 0.5

            if curr_inv_num and prev_inv_num and curr_inv_num == prev_inv_num:
                neg_signals.append("Gleiche Rechnungsnummer")
                neg_weight += 0.7

            curr_cust = self._extract_customer_number(curr_text)
            prev_cust = self._extract_customer_number(prev_text)
            if curr_cust and prev_cust and curr_cust == prev_cust:
                neg_signals.append("Gleiche Kundennummer")
                neg_weight += 0.4

            # Decision
            # Standard threshold is around 0.5
            boundary_score = 0.2 + pos_weight - neg_weight
            boundary_score = max(0.0, min(1.0, boundary_score))

            is_boundary = False
            is_ambiguous = False

            if boundary_score > 0.6:
                is_boundary = True
            elif boundary_score >= 0.4:
                is_ambiguous = True

            transition = {
                "from_page": prev_p["page"]["page_num"],
                "to_page": curr_p["page"]["page_num"],
                "is_boundary": is_boundary,
                "confidence": boundary_score if is_boundary else 1.0 - boundary_score,
                "positive_signals": pos_signals,
                "negative_signals": neg_signals
            }

            if is_ambiguous:
                is_boundary = False
                transition["is_boundary"] = False
                transition["warnings"] = ["BOUNDARY_AMBIGUOUS"]
                transition["alternative_is_boundary"] = True
                transition["confidence"] = 1.0 - boundary_score

            transitions.append(transition)

            if is_boundary:
                finalize_document(
                    start_idx=current_doc_start_idx,
                    end_idx=prev_content_idx,
                    start_conf=last_start_transition_conf,
                    end_conf=boundary_score,
                    cont_conf=doc_continuation_confidence,
                    cont_count=continuation_signal_count
                )
                current_doc_start_idx = i
                doc_continuation_confidence = 0.0
                continuation_signal_count = 0
                last_start_transition_conf = boundary_score
            else:
                doc_continuation_confidence += (1.0 - boundary_score)
                continuation_signal_count += 1

            prev_content_idx = i

        # Finalize the last document
        finalize_document(
            start_idx=current_doc_start_idx,
            end_idx=prev_content_idx,
            start_conf=last_start_transition_conf,
            end_conf=0.8,
            cont_conf=doc_continuation_confidence,
            cont_count=continuation_signal_count
        )

        result["documents"] = documents
        result["transitions"] = transitions

        self._verify_invariant(sorted_pages, unassigned, documents)

        # Cleanup internal pages key
        for doc in result["documents"]:
            if "_internal_pages" in doc:
                del doc["_internal_pages"]

        return result

    def _verify_invariant(self, all_pages, unassigned, documents):
        unassigned_nums = {u["page_num"] for u in unassigned}
        assigned_nums = set()

        for doc in documents:
            for p_num in doc["_internal_pages"]:
                if p_num in assigned_nums:
                    raise RuntimeError(f"Invariant violated: Page {p_num} assigned to multiple documents.")
                assigned_nums.add(p_num)

        all_nums = {p["page_num"] for p in all_pages if p.get("page_num") is not None}

        for p_num in all_nums:
            if p_num not in unassigned_nums and p_num not in assigned_nums:
                raise RuntimeError(f"Invariant violated: Page {p_num} is not assigned to any document or unassigned list.")

        intersection = unassigned_nums.intersection(assigned_nums)
        if intersection:
            raise RuntimeError(f"Invariant violated: Pages {intersection} are in both assigned and unassigned lists.")


def compare_boundaries(expected: Dict[str, Any], predicted: Dict[str, Any]) -> Dict[str, float]:
    exp_docs = expected.get("documents", [])
    pred_docs = predicted.get("documents", [])

    if not exp_docs and not pred_docs:
        return {
            "exact_precision": 1.0,
            "exact_recall": 1.0,
            "start_page_accuracy": 1.0,
            "end_page_accuracy": 1.0,
            "page_assignment_accuracy": 1.0
        }

    if not pred_docs:
         return {
            "exact_precision": 0.0,
            "exact_recall": 0.0,
            "start_page_accuracy": 0.0,
            "end_page_accuracy": 0.0,
            "page_assignment_accuracy": 0.0
        }

    exp_boundaries = {(d["start_page"], d["end_page"]) for d in exp_docs}
    pred_boundaries = {(d["start_page"], d["end_page"]) for d in pred_docs}

    exact_matches = exp_boundaries.intersection(pred_boundaries)
    exact_precision = len(exact_matches) / len(pred_boundaries) if pred_boundaries else 0.0
    exact_recall = len(exact_matches) / len(exp_boundaries) if exp_boundaries else 0.0

    exp_starts = {d["start_page"] for d in exp_docs}
    pred_starts = {d["start_page"] for d in pred_docs}
    start_matches = exp_starts.intersection(pred_starts)
    start_page_accuracy = len(start_matches) / len(exp_starts) if exp_starts else 0.0

    exp_ends = {d["end_page"] for d in exp_docs}
    pred_ends = {d["end_page"] for d in pred_docs}
    end_matches = exp_ends.intersection(pred_ends)
    end_page_accuracy = len(end_matches) / len(exp_ends) if exp_ends else 0.0

    # Page assignment accuracy: fraction of content pages assigned to the correct document boundaries
    # A page is correctly assigned if its true (start, end) matches predicted (start, end)
    exp_page_map = {}
    for d in exp_docs:
        # Assuming continuous ranges for page assignment metrics (simplification)
        for p in range(d["start_page"], d["end_page"] + 1):
            exp_page_map[p] = (d["start_page"], d["end_page"])

    pred_page_map = {}
    for d in pred_docs:
        for p in range(d["start_page"], d["end_page"] + 1):
            pred_page_map[p] = (d["start_page"], d["end_page"])

    correct_pages = 0
    total_pages = len(exp_page_map)
    for p, bounds in exp_page_map.items():
        if p in pred_page_map and pred_page_map[p] == bounds:
            correct_pages += 1

    page_assignment_accuracy = correct_pages / total_pages if total_pages > 0 else 0.0

    return {
        "exact_precision": exact_precision,
        "exact_recall": exact_recall,
        "start_page_accuracy": start_page_accuracy,
        "end_page_accuracy": end_page_accuracy,
        "page_assignment_accuracy": page_assignment_accuracy
    }
