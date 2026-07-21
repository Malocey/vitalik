import math
from typing import Any, Dict, List

class FastLaneRouter:
    def __init__(
        self,
        chars_per_token: int = 4,
        prompt_overhead_tokens: int = 250,
        tokens_per_requested_field: int = 80,
        tokens_per_second: float = 20.0,
        baseline_llm_seconds_per_document: float = 50.0
    ):
        self.chars_per_token = chars_per_token
        self.prompt_overhead_tokens = prompt_overhead_tokens
        self.tokens_per_requested_field = tokens_per_requested_field
        self.tokens_per_second = tokens_per_second
        self.baseline_llm_seconds_per_document = baseline_llm_seconds_per_document

        self.protected_document_types = {
            "Kontoauszug", "Bankdokument", "Lieferschein", "Angebot",
            "Mahnung", "Zahlungserinnerung", "Vertrag", "Versicherung",
            "Steuerbescheid", "Unlesbar"
        }

    def _is_missing_field(self, field_dict: Dict[str, Any]) -> bool:
        if not field_dict:
            return True
        if field_dict.get("found") is False:
            return True
        val = field_dict.get("value")
        if val is None or val == "":
            return True
        if isinstance(val, str) and val.upper() in ["UNKNOWN", "UNBEKANNT", "REG-EXPR"]:
            return True
        return False

    def _is_amount_mathematically_correct(self, amount_result: Dict[str, Any]) -> bool:
        if not amount_result:
            return False
        if not amount_result.get("math_valid"):
            return False
        if amount_result.get("math_difference", 1.0) > 0.02:
            return False
        for field in ["net", "tax", "gross"]:
            if field not in amount_result or not amount_result[field]:
                return False
        if amount_result.get("conflicts"):
            return False
        return True

    def _has_currency_conflict(self, amount_result: Dict[str, Any]) -> bool:
        if not amount_result:
            return False

        # Check explicit conflicts array
        conflicts = amount_result.get("conflicts", [])
        for c in conflicts:
            if isinstance(c, str) and "currency" in c.lower():
                return True
            if isinstance(c, dict) and c.get("type") == "currency":
                return True

        # Check cross-field currencies
        currencies = set()
        has_null_currency = False
        for field in ["net", "tax", "gross"]:
            val = amount_result.get(field, {})
            if isinstance(val, dict):
                cur = val.get("currency")
                if cur:
                    currencies.add(cur)
                else:
                    has_null_currency = True

        if len(currencies) > 1:
            return True
        if len(currencies) > 0 and has_null_currency:
            return True

        return False

    def route(self, data: Dict[str, Any]) -> Dict[str, Any]:
        # Basic defaults
        result = {
            "route": "REJECTED",
            "llm_required": False,
            "required_steps": [],
            "blocking_reasons": [],
            "missing_fields": [],
            "llm_prompt_fields": [],
            "confidence": 1.0,
            "estimated_tokens": 0,
            "estimated_time_seconds": 0.0,
            "estimate_source": "not_required",
            "saved_llm_call": None
        }

        # Validate basic structure
        if not data or data.get("input_valid") is False:
            result["blocking_reasons"].append("invalid_input")
            return result

        pages = data.get("pages", [])
        # We don't necessarily have raw text here, but user mentioned:
        # "beschädigte Eingabe, keine Seiten, kein verwertbarer Text" -> REJECTED
        # "leere Seite"
        # However context_character_count might be 0
        ctx_chars = data.get("context_character_count", 0)
        if not pages and ctx_chars == 0:
            result["blocking_reasons"].append("no_pages")
            return result

        # A. REJECTED checked

        # Extract values
        ocr_score = data.get("ocr_quality_score", 0.0)
        boundary_conf = data.get("boundary_confidence", 0.0)

        dup_warn = data.get("duplicate_warning", False)
        if not dup_warn and isinstance(data.get("duplicate_result"), dict):
            dup_warn = data.get("duplicate_result", {}).get("is_duplicate", False)

        doc_type_res = data.get("document_type_result") or {}
        doc_type = doc_type_res.get("document_type", "")
        doc_status = doc_type_res.get("status", "")
        doc_conf = doc_type_res.get("confidence", 0.0)

        amount_res = data.get("amount_result") or {}
        supplier_res = data.get("supplier_result") or {}
        inv_num_res = data.get("invoice_number_result") or {}

        # B. MANUAL_REVIEW conditions
        manual_review_reasons = []
        if doc_type in self.protected_document_types:
            manual_review_reasons.append("protected_document_type")
        if ocr_score < 0.70:
            manual_review_reasons.append("low_ocr_score")
        if boundary_conf < 0.70:
            manual_review_reasons.append("low_boundary_confidence")
        if dup_warn:
            manual_review_reasons.append("duplicate_warning")

        if doc_status in ["AMBIGUOUS", "INSUFFICIENT_TEXT"]:
            manual_review_reasons.append("ambiguous_document_type")

        # Checking for conflicts
        if self._has_currency_conflict(amount_res):
            manual_review_reasons.append("currency_conflict")

        if amount_res.get("conflicts"):
            # amount conflicts lead to manual review as well, user rules say "Betragskonflikt"
            manual_review_reasons.append("amount_conflict")

        if manual_review_reasons:
            result["route"] = "MANUAL_REVIEW"
            result["blocking_reasons"] = manual_review_reasons
            result["confidence"] = 1.0 # certainty of routing
            return result

        # Identify missing fields
        missing = []
        if self._is_missing_field(supplier_res):
            missing.append("supplier")
        if self._is_missing_field(inv_num_res):
            missing.append("invoice_number")
        if not self._is_amount_mathematically_correct(amount_res):
            missing.append("amount_details")

        # C. FAST_LANE conditions
        fast_lane_ok = True
        if ocr_score < 0.85 or boundary_conf < 0.90:
            fast_lane_ok = False
        if doc_status != "CLASSIFIED" or doc_conf < 0.90:
            fast_lane_ok = False
        if doc_type not in ["Rechnung", "Gutschrift"]:
            fast_lane_ok = False

        sup_conf = supplier_res.get("confidence", 0.0)
        if "supplier" in missing or sup_conf < 0.90 or supplier_res.get("conflicts"):
            fast_lane_ok = False

        inv_conf = inv_num_res.get("confidence", 0.0)
        if "invoice_number" in missing or inv_conf < 0.90 or inv_num_res.get("conflicts"):
            fast_lane_ok = False

        amt_conf = amount_res.get("confidence", 0.0)
        if "amount_details" in missing or amt_conf < 0.90:
            fast_lane_ok = False

        if fast_lane_ok:
            result["route"] = "FAST_LANE"
            result["saved_llm_call"] = True
            result["confidence"] = min(ocr_score, boundary_conf, doc_conf, sup_conf, inv_conf, amt_conf)
            return result

        # Target/Full LLM calculation
        result["missing_fields"] = missing
        result["llm_prompt_fields"] = missing
        result["llm_required"] = True
        result["saved_llm_call"] = False
        result["estimate_source"] = "configured_default"

        est_tokens = math.ceil(ctx_chars / self.chars_per_token) + self.prompt_overhead_tokens + len(missing) * self.tokens_per_requested_field
        result["estimated_tokens"] = est_tokens
        result["estimated_time_seconds"] = est_tokens / self.tokens_per_second

        # Evidences for LLM confidence
        evidences = [ocr_score, boundary_conf]
        if "supplier" not in missing: evidences.append(sup_conf)
        if "invoice_number" not in missing: evidences.append(inv_conf)
        if "amount_details" not in missing: evidences.append(amt_conf)
        if doc_conf > 0: evidences.append(doc_conf)

        base_conf = min(evidences) if evidences else 0.0
        penalty = len(missing) * 0.10
        final_conf = max(0.0, min(1.0, base_conf - penalty))
        result["confidence"] = final_conf

        # D. TARGETED_LLM
        if ocr_score >= 0.75 and boundary_conf >= 0.80 and len(missing) <= 2:
            result["route"] = "TARGETED_LLM"
            return result

        # E. FULL_LLM
        result["route"] = "FULL_LLM"
        return result

    def route_batch(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        results = []
        routes_count = {
            "FAST_LANE": 0,
            "TARGETED_LLM": 0,
            "FULL_LLM": 0,
            "MANUAL_REVIEW": 0,
            "REJECTED": 0
        }

        llm_required_count = 0
        llm_calls_avoided = 0
        total_tokens = 0
        total_time_secs = 0.0

        for doc in documents:
            res = self.route(doc)
            results.append(res)

            r = res["route"]
            routes_count[r] += 1

            if res.get("llm_required"):
                llm_required_count += 1
                total_tokens += res.get("estimated_tokens", 0)
                total_time_secs += res.get("estimated_time_seconds", 0.0)

            if res.get("saved_llm_call") is True:
                llm_calls_avoided += 1

        total_docs = len(documents)
        fast_lane_share = routes_count["FAST_LANE"] / total_docs if total_docs > 0 else 0.0
        expected_llm_savings_rate = llm_calls_avoided / total_docs if total_docs > 0 else 0.0

        estimated_time_saved = llm_calls_avoided * self.baseline_llm_seconds_per_document

        return {
            "results": results,
            "summary": {
                "total_documents": total_docs,
                "route_distribution": routes_count,
                "fast_lane_share": fast_lane_share,
                "llm_required_count": llm_required_count,
                "llm_calls_avoided": llm_calls_avoided,
                "expected_llm_savings_rate": expected_llm_savings_rate,
                "estimated_llm_tokens": total_tokens,
                "estimated_llm_time_seconds": total_time_secs,
                "estimated_time_saved_seconds": estimated_time_saved,
                "time_estimate_source": "configured_baseline"
            }
        }
