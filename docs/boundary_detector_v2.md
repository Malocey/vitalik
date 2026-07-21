# Boundary Detector V2

## Overview

The `BoundaryDetectorV2` evaluates multi-page PDFs to detect document boundaries (start and end pages of individual documents). It relies exclusively on the extracted text (OCR) from each page and does not require AI, network access, or a database.

## Methodology

The detector analyzes the transition between consecutive pages to decide whether to split them into separate documents or merge them into a single one. This is achieved by evaluating various textual signals and calculating a transition confidence.

### Input
A list of page dictionaries containing `page_num`, `full_text`, and optionally OCR metadata.

### Output
The system outputs:
- **`documents`**: A list of detected documents with start and end pages, confidence scores, and any warnings.
- **`transitions`**: Detailed evaluation of every page transition, indicating whether it's a boundary and listing the signals found.
- **`unassigned_pages`**: Pages that do not belong to any document (e.g., blank pages, separators, insufficient OCR), with a detailed reason and classification.

## Signal Evaluation

The evaluation of a transition considers positive signals (which indicate a new document) and negative/continuation signals (which indicate the current document continues).

### Positive Boundary Signals
- "Seite 1 von N" (Page 1 of N)
- New invoice number
- Previous page was "Seite N von N" (End of document)
- Previous document ends with a total amount ("Gesamtbetrag")
- A blank separator page exists between the documents

### Continuation Signals
- "Seite X von N" (where X > 1)
- Continuation keywords like "Übertrag" or "Fortsetzung"
- Same invoice number as the previous page
- Same customer number as the previous page

## Handling Edge Cases

1. **Unassigned Pages**: Pages with less than 20 alphanumeric characters or less than 3 words are classified as `SEPARATOR_PAGE` or `BLANK_BACKSIDE` (if they immediately follow a content page). Completely empty pages are always `SEPARATOR_PAGE`.
2. **Ambiguous Boundaries**: If the transition score is ambiguous, the detector avoids splitting arbitrarily, marks `is_boundary` as `False`, and attaches a `BOUNDARY_AMBIGUOUS` warning.
3. **Missing Pages**: If there are gaps in the provided `page_num` sequence, a `MISSING_PAGE_NUMBERS` warning is added to the relevant document.
4. **Duplicate Pages**: Duplicate page numbers raise a `ValueError` immediately.

## Confidence Score Calculation

The overall document confidence is calculated based on the boundaries of the document and internal continuation signals:
- `0.4 * start_confidence`
- `0.4 * end_confidence`
- `0.2 * continuation_confidence` (averaged over all internal transitions)

If a document starts at the very first page of the file, its start confidence is neutral (0.8). Similarly, ending at the last page gives a neutral end confidence (0.8).

## Invariants

The system guarantees that every non-unassigned page is assigned to exactly one document. If this invariant is violated, a `RuntimeError` is raised.

## Known Limitations

- The logic is highly dependent on the quality of the OCR text. Poor OCR can lead to missed signals (e.g., misread invoice numbers).
- If a document contains completely contradictory signals (e.g., "Seite 1 von N" but the same invoice number), the weighted score determines the outcome, which might not always align with human intuition.
