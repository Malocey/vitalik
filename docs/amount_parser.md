# Amount & Tax Parser

A strictly deterministic parser for extracting financial amounts and value-added tax (VAT) data from OCR texts.

## Key Features
- **Offline & Deterministic**: No LLM, network, or external API calls are made.
- **Robust Amount Extraction**: Supports various German and international number formats (e.g., `1.234,56`, `1,234.56`, `1 234.56`).
- **Context-Aware Classification**: Identifies net, gross, tax, shipping, skonto, and deposit based on local text context.
- **Mathematical Validation**: Checks combinations of net, tax, and gross to verify mathematical correctness with tolerance up to 0.02 EUR for rounding differences.
- **Tax Rate Detection**: Infers standard 19% and 7% tax rates from text.
- **Credit Note Recognition**: Detects credit notes via keywords and negative overall amounts, gracefully handling conflicting signals by marking them and reducing confidence.
- **OCR Error Mitigation**: Corrects typical OCR errors such as misread zeros (e.g., `1O7,OO` -> `107.00`).

## Usage

```python
from src.parser.amount_parser import parse

text = "Nettobetrag 100,00 EUR\n19 % MwSt 19,00 EUR\nGesamtbetrag 119,00 EUR"
result = parse(text)

print(result["gross"]["value"])  # 119.0
print(result["math_valid"])      # True
```

You can pass either a simple string or a sequence of page dictionaries:

```python
pages = [
    {"page_num": 1, "full_text": "Netto 100,00 EUR"},
    {"page_num": 2, "full_text": "Brutto 119,00 EUR"}
]
result = parse(pages)
```

## Known Limitations
- The parser expects simple local context (on the same line or immediate context) for tax rates or field types. Highly unformatted or randomly scrambled strings might lead to missed types, although the mathematical verification acts as a fallback to deduce gross/net combinations.
- Conflicting combinations reduce confidence.
- Multiple competing tax rates on the same document are theoretically parsed but the current deterministic combination logic checks for a single coherent set of gross, net, tax pairs primarily. Additional enhancements may be needed for fully multi-rate invoices spanning multiple line items with identically named net/tax fields.
