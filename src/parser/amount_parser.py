import re
import math
from typing import Union, Sequence, Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, asdict

@dataclass
class AmountCandidate:
    value: float
    currency: Optional[str]

    def __hash__(self):
        return hash((self.value, self.currency, self.field_type, self.source_text, self.line_number))

    def __eq__(self, other):
        if not isinstance(other, AmountCandidate):
            return False
        return (self.value, self.currency, self.field_type, self.source_text, self.line_number) == \
               (other.value, other.currency, other.field_type, other.source_text, other.line_number)
    field_type: Optional[str]
    tax_rate: Optional[float]
    source_text: str
    line_number: int
    page_number: int
    confidence: float
    method: str
    normalizations: List[str] = None

    def __post_init__(self):
        if self.normalizations is None:
            self.normalizations = []

    def to_dict(self):
        d = asdict(self)
        if hasattr(self, 'currency_source'):
            d['currency_source'] = self.currency_source
        if not d['normalizations']:
            del d['normalizations']
        return d

FIELD_TYPES = {
    "net": ["netto", "nettobetrag", "warenwert", "zwischensumme"],
    "tax": ["umsatzsteuer", "mehrwertsteuer", "mwst", "ust"],
    "gross": ["brutto", "gesamtbetrag", "rechnungsbetrag", "zahlbetrag", "endbetrag", "zu zahlen"],
    "skonto": ["skonto"],
    "deposit": ["pfand"],
    "shipping": ["versandkosten"]
}

CREDIT_NOTE_KEYWORDS = ["gutschrift", "stornogutschrift", "credit note", "wir schreiben ihnen gut", "haben"]

def _parse_amount_string(s: str) -> Tuple[Optional[float], List[Dict[str, Any]]]:
    original = s
    normalizations = []

    if 'O' in s:
        s_new = s.replace('O', '0')
        normalizations.append({
            "original_text": original,
            "normalized_text": s_new,
            "normalizations": ["O_TO_ZERO_IN_NUMERIC_TOKEN"]
        })
        s = s_new

    is_negative = False
    s = s.strip()
    if s.startswith('-'):
        is_negative = True
        s = s[1:]
    elif s.endswith('-'):
        is_negative = True
        s = s[:-1]

    s = s.strip()

    # Check for thousand separators with space
    if re.match(r'^\d{1,3}( \d{3})+,\d{2}$', s) or re.match(r'^\d{1,3}( \d{3})+\.\d{2}$', s):
        s = s.replace(' ', '')

    commas = s.count(',')
    dots = s.count('.')

    val = None
    try:
        if commas == 1 and dots == 0:
            val = float(s.replace(',', '.'))
        elif dots == 1 and commas == 0:
            val = float(s)
        elif dots > 0 and commas == 1:
            if s.rfind(',') > s.rfind('.'):
                s = s.replace('.', '')
                val = float(s.replace(',', '.'))
            else:
                s = s.replace(',', '')
                val = float(s)
        elif commas > 0 and dots == 1:
            if s.rfind('.') > s.rfind(','):
                s = s.replace(',', '')
                val = float(s)
            else:
                s = s.replace('.', '')
                val = float(s.replace(',', '.'))
        else:
            return None, normalizations

        if is_negative:
            val = -val

        return val, normalizations
    except ValueError:
        return None, normalizations

def _extract_currency(text: str, default_currency: str, document_text: str) -> Tuple[str, bool]:
    if re.search(r'\bEUR\b|€', text, re.IGNORECASE):
        return "EUR", False
    if re.search(r'\bUSD\b|\$', text, re.IGNORECASE):
        return "USD", False
    if re.search(r'\bCHF\b', text, re.IGNORECASE):
        return "CHF", False

    currencies_found = set()
    if re.search(r'\bEUR\b|€', document_text, re.IGNORECASE): currencies_found.add("EUR")
    if re.search(r'\bUSD\b|\$', document_text, re.IGNORECASE): currencies_found.add("USD")
    if re.search(r'\bCHF\b', document_text, re.IGNORECASE): currencies_found.add("CHF")

    if len(currencies_found) == 1:
        return currencies_found.pop(), True

    if "EUR" in currencies_found and default_currency == "EUR":
        return "EUR", True

    return default_currency, True

def _extract_field_type(text: str) -> Optional[str]:
    text_lower = text.lower()
    for field, keywords in FIELD_TYPES.items():
        for keyword in keywords:
            if keyword in text_lower:
                return field
    return None

def _extract_tax_rate(text: str) -> Optional[float]:
    # Look for 7% or 19%
    match = re.search(r'\b(19|7)\s*%|\b(19|7)\b.*mwst|\b(19|7)\b.*ust|\b(19|7)\b.*umsatzsteuer', text.lower())
    if match:
        return float(match.group(1) or match.group(2) or match.group(3) or match.group(4))
    return None

def _find_best_match(candidates: List[AmountCandidate]) -> Tuple[Dict[str, Any], List[Dict[str, Any]], bool, float, float, List[str]]:
    # We want to find combinations of (net, tax, gross) that satisfy net + tax = gross
    # and tax_rate roughly matches.
    # Allowing rounding error up to 0.02

    nets = [c for c in candidates if c.field_type == "net" or c.field_type is None]
    taxes = [c for c in candidates if c.field_type == "tax" or c.field_type is None]
    grosses = [c for c in candidates if c.field_type == "gross" or c.field_type is None]

    valid_combos = []

    # We can also have multiple tax rates, so multiple (net, tax) pairs summing to gross
    # We'll check single rate combinations first, and then combinations of multiple (net, tax) to single gross

    for n in nets:
        for t in taxes:
            if n is t: continue
            for g in grosses:
                if g is n or g is t: continue

                # We need exact sign matching, so if credit note, all should be negative or positive depending on presentation
                # Usually OCR reads positive numbers and gross might be neg, or all are pos. Let's just use abs values for math check

                net_val = abs(n.value)
                tax_val = abs(t.value)
                gross_val = abs(g.value)

                diff = round(abs((net_val + tax_val) - gross_val), 2)
                if diff <= 0.02:
                    # check tax rate
                    implied_rate = (tax_val / net_val) * 100 if net_val != 0 else 0

                    # If tax rate is defined in candidates, check it matches
                    rate = None
                    if n.tax_rate: rate = n.tax_rate
                    elif t.tax_rate: rate = t.tax_rate
                    elif g.tax_rate: rate = g.tax_rate
                    else:
                        if abs(implied_rate - 19.0) < 1.0: rate = 19.0
                        elif abs(implied_rate - 7.0) < 1.0: rate = 7.0

                    # If rate is known, tax must match rate
                    if rate:
                        expected_tax = net_val * (rate / 100.0)
                        if abs(expected_tax - tax_val) <= 0.02:
                            valid_combos.append({
                                "net": n, "tax": t, "gross": g,
                                    "pairs": [(n, t, rate)],
                                "diff": diff, "rate": rate,
                                    "confidence": (n.confidence + t.confidence + g.confidence) / 3.0,
                                    "is_multi": False
                            })

    # Support multiple taxes mapping to same gross
    import itertools
    for g in grosses:
        for num_pairs in range(1, 4):  # Check up to 3 net/tax pairs
            for combo_nets in itertools.combinations(nets, num_pairs):
                if g in combo_nets: continue
                # find matching taxes for these nets
                for combo_taxes in itertools.product(taxes, repeat=num_pairs):
                    if g in combo_taxes: continue
                    # ensure unique items
                    if len(set(combo_taxes)) != num_pairs: continue

                    overlap = False
                    for cn in combo_nets:
                        if cn in combo_taxes: overlap = True
                    if overlap: continue

                    sum_net = sum(abs(n.value) for n in combo_nets)
                    sum_tax = sum(abs(t.value) for t in combo_taxes)
                    gross_val = abs(g.value)

                    diff = round(abs((sum_net + sum_tax) - gross_val), 2)
                    if diff <= 0.02:
                        # Verify rates
                        pairs = []
                        valid_rates = True
                        for i in range(num_pairs):
                            n_v = abs(combo_nets[i].value)
                            t_v = abs(combo_taxes[i].value)
                            rate = combo_nets[i].tax_rate or combo_taxes[i].tax_rate
                            implied = (t_v / n_v) * 100 if n_v != 0 else 0
                            if not rate:
                                if abs(implied - 19.0) < 1.0: rate = 19.0
                                elif abs(implied - 7.0) < 1.0: rate = 7.0

                            if rate:
                                exp = n_v * (rate / 100.0)
                                if abs(exp - t_v) > 0.02:
                                    valid_rates = False
                                    break
                            pairs.append((combo_nets[i], combo_taxes[i], rate))

                        if valid_rates:
                            conf = (sum(c.confidence for c in combo_nets) + sum(c.confidence for c in combo_taxes) + g.confidence) / (2*num_pairs + 1)
                            valid_combos.append({
                                "net": combo_nets[0], "tax": combo_taxes[0], "gross": g, # primary for single match logic
                                "pairs": pairs,
                                "diff": diff, "rate": pairs[0][2] if pairs[0][2] else 0.0,
                                "confidence": conf,
                                "is_multi": num_pairs > 1
                            })

    # if no combination with tax, try 0% tax
    for g in grosses:
        for n in nets:
            if g is n: continue
            diff = round(abs(abs(g.value) - abs(n.value)), 2)
            if diff <= 0.02:
                valid_combos.append({
                    "net": n, "tax": None, "gross": g,
                    "pairs": [(n, None, 0.0)],
                    "diff": diff, "rate": 0.0,
                    "confidence": (n.confidence + g.confidence) / 2.0,
                    "is_multi": False
                })

    conflicts = []
    if not valid_combos:
        return {}, [], False, 0.0, 0.0, ["No valid mathematical combination found"]

    # check for conflicting combinations
    best_combo = None
    max_conf = -1.0

    # filter valid combos based on strict field type match
    # higher confidence if field types are strictly set
    for c in valid_combos:
        score = c["confidence"]
        if c.get("is_multi"):
            for n, t, r in c["pairs"]:
                if n.field_type == "net": score += 0.1
                if t and t.field_type == "tax": score += 0.1
        else:
            if c["net"].field_type == "net": score += 0.1
            if c["tax"] and c["tax"].field_type == "tax": score += 0.1
        if c["gross"].field_type == "gross": score += 0.1
        c["score"] = score

    valid_combos.sort(key=lambda x: x["score"], reverse=True)

    best_combo = valid_combos[0]
    best_score = best_combo["score"]

    for c in valid_combos[1:]:
        if abs(c["gross"].value) != abs(best_combo["gross"].value):
            conflicts.append("Multiple competing amounts with high confidence")
            break

    # Also check other grosses that didn't make it to valid_combos
    best_gross_val = abs(best_combo["gross"].value)
    for g in grosses:
        if abs(g.value) != best_gross_val:
            conflicts.append("Multiple competing amounts with high confidence")
            break

    confidence = best_combo["confidence"]
    if conflicts:
        confidence -= 0.3

    res_dict = {
        "net": best_combo["net"].to_dict(),
        "gross": best_combo["gross"].to_dict(),
        "tax": best_combo["tax"].to_dict() if best_combo["tax"] else None
    }

    tax_breakdown = []
    for n, t, r in best_combo["pairs"]:
        if t:
            tax_breakdown.append({
                "tax_rate": r,
                "net": n.value,
                "tax": t.value,
                "gross": round(n.value + t.value, 2),
                "math_valid": True,
                "source_lines": [n.line_number, t.line_number, best_combo["gross"].line_number],
                "confidence": confidence
            })
        else:
            tax_breakdown.append({
                "tax_rate": 0.0,
                "net": n.value,
                "tax": 0.0,
                "gross": n.value,
                "math_valid": True,
                "source_lines": [n.line_number, best_combo["gross"].line_number],
                "confidence": confidence
            })

    return res_dict, tax_breakdown, True, best_combo["diff"], max(0, confidence), conflicts


def parse(input_data: Union[str, Sequence[Dict[str, Any]]], default_currency: str = "EUR") -> Dict[str, Any]:
    if not input_data:
        return {
            "net": None, "tax": None, "gross": None, "tax_breakdown": [],
            "skonto": None, "deposit": None, "is_credit_note": False,
            "math_valid": False, "math_difference": 0.0, "confidence": 0.0, "conflicts": []
        }

    lines = []
    document_text = ""

    if isinstance(input_data, str):
        document_text = input_data
        current_page = 1
        for i, line in enumerate(input_data.split('\n')):
            page_match = re.search(r'--- SEITE (\d+) ---', line, re.IGNORECASE)
            if page_match:
                current_page = int(page_match.group(1))
            lines.append({
                "text": line,
                "line_number": i + 1,
                "page_number": current_page
            })
    else:
        for page in input_data:
            page_num = page.get("page_num", 1)
            text = page.get("full_text", "")
            document_text += text + "\n"
            for i, line in enumerate(text.split('\n')):
                lines.append({
                    "text": line,
                    "line_number": i + 1,
                    "page_number": page_num
                })

    candidates = []

    # We want to match isolated numbers or numbers with currency
    pattern = r'(?<![0-9Oa-zA-Z])(-?\s*(?:[0-9O]{1,3}(?:[ .,][0-9O]{3})*|[0-9O]+)[.,][0-9O]{1,2}\s*-?)(?![0-9Oa-zA-Z])'

    for line in lines:
        text = line["text"]
        # Find all matches
        for match in re.finditer(pattern, text):
            raw_str = match.group(1)
            val, normalizations = _parse_amount_string(raw_str)
            if val is not None:
                currency, inferred = _extract_currency(text, default_currency, document_text)
                field_type = _extract_field_type(text)
                tax_rate = _extract_tax_rate(text)

                currency_src = "inferred_default" if inferred else currency

                confidence = 0.98
                if normalizations:
                    confidence -= 0.1

                candidate = AmountCandidate(
                    value=val,
                    currency=currency,
                    field_type=field_type,
                    tax_rate=tax_rate,
                    source_text=text.strip(),
                    line_number=line["line_number"],
                    page_number=line["page_number"],
                    confidence=confidence,
                    method="label_context",
                    normalizations=normalizations
                )

                # To support extra fields like currency_source we dynamically set it
                # though dataclasses won't serialize it naturally, we will handle it in to_dict later
                # Or just modify AmountCandidate
                candidate.currency_source = currency_src
                candidates.append(candidate)

    result = {
        "net": None,
        "tax": None,
        "gross": None,
        "tax_breakdown": [],
        "skonto": None,
        "deposit": None,
        "is_credit_note": False,
        "math_valid": False,
        "math_difference": 0.0,
        "confidence": 0.0,
        "conflicts": []
    }

    if not candidates:
        return result

    is_credit_note_signals = 0
    document_text_lower = document_text.lower()
    for kw in CREDIT_NOTE_KEYWORDS:
        if kw in document_text_lower:
            is_credit_note_signals += 1

    # Neg amounts check
    neg_gross_signals = sum(1 for c in candidates if c.field_type == "gross" and c.value < 0)
    if neg_gross_signals > 0:
        is_credit_note_signals += 1

    # We will identify skonto and deposit
    skontos = [c for c in candidates if c.field_type == "skonto"]
    deposits = [c for c in candidates if c.field_type == "deposit"]

    res_dict, tax_breakdown, math_valid, math_diff, confidence, conflicts = _find_best_match(candidates)

    result["net"] = res_dict.get("net")
    result["tax"] = res_dict.get("tax")
    result["gross"] = res_dict.get("gross")
    result["tax_breakdown"] = tax_breakdown
    result["math_valid"] = math_valid
    result["math_difference"] = math_diff
    result["confidence"] = confidence
    result["conflicts"] = conflicts

    if skontos:
        result["skonto"] = skontos[0].to_dict()
    if deposits:
        result["deposit"] = deposits[0].to_dict()

    pos_candidates = sum(1 for c in candidates if c.value > 0)
    neg_candidates = sum(1 for c in candidates if c.value < 0)

    if is_credit_note_signals > 0 and pos_candidates > 0 and neg_candidates > 0:
        result["is_credit_note"] = None
        result["conflicts"].append("Conflicting credit note signals")
        result["confidence"] = max(0, result["confidence"] - 0.2)
    elif is_credit_note_signals > 0:
        result["is_credit_note"] = True
    elif pos_candidates > 0 and neg_candidates > 0:
        result["is_credit_note"] = None
        result["conflicts"].append("Conflicting credit note signals")
        result["confidence"] = max(0, result["confidence"] - 0.2)
    else:
        result["is_credit_note"] = False

    return result
