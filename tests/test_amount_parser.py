import pytest
from src.parser.amount_parser import parse

def test_empty_input():
    res = parse("")
    assert res["gross"] is None
    assert res["net"] is None

def test_german_format():
    text = "Nettobetrag 100,00 EUR\n19 % MwSt 19,00 EUR\nGesamtbetrag 119,00 EUR"
    res = parse(text)
    assert res["math_valid"] is True
    assert res["net"]["value"] == 100.0
    assert res["tax"]["value"] == 19.0
    assert res["gross"]["value"] == 119.0

def test_international_format():
    text = "net 1,000.00\ntax 190.00\ngross 1,190.00"
    res = parse(text)
    assert res["math_valid"] is True
    assert res["net"]["value"] == 1000.0
    assert res["gross"]["value"] == 1190.0

def test_credit_note():
    text = "Gutschrift\nNettobetrag -100,00 EUR\n19% MwSt -19,00 EUR\nGesamtbetrag -119,00 EUR"
    res = parse(text)
    assert res["is_credit_note"] is True
    assert res["gross"]["value"] == -119.0

def test_rounding_difference():
    text = "Netto 100,00\n19% MwSt 19,01\nBrutto 119,02"
    res = parse(text)
    assert res["math_valid"] is True
    assert res["math_difference"] == 0.01

def test_ocr_error():
    text = "Netto 1OO,OO\n19% MwSt 19,OO\nBrutto 119,OO"
    res = parse(text)
    assert res["math_valid"] is True
    assert res["gross"]["value"] == 119.0
    assert len(res["gross"]["normalizations"]) > 0
    norm = res["gross"]["normalizations"][0]
    assert norm["original_text"] == "119,OO"
    assert norm["normalized_text"] == "119,00"
    assert "O_TO_ZERO_IN_NUMERIC_TOKEN" in norm["normalizations"]


def test_mixed_tax_rates():
    text = "Warenwert 19% 100,00\nMwSt 19% 19,00\nWarenwert 7% 50,00\nMwSt 7% 3,50\nGesamtbetrag 172,50"
    res = parse(text)
    assert res["math_valid"] is True
    assert len(res["tax_breakdown"]) == 2
    assert res["tax_breakdown"][0]["tax_rate"] in [19.0, 7.0]
    assert res["tax_breakdown"][1]["tax_rate"] in [19.0, 7.0]
    assert res["gross"]["value"] == 172.50

def test_multiple_competing_amounts():
    text = "Gesamtbetrag 100,00 EUR\nGesamtbetrag 200,00 EUR\nNetto 84,03 EUR\n19% MwSt 15,97"
    res = parse(text)
    assert res["math_valid"] is True
    assert res["gross"]["value"] == 100.0
    assert len(res["conflicts"]) > 0
    assert res["confidence"] < 0.98

def test_deposit():
    text = "Pfand 3,15 EUR\nNetto 10,00\nMwSt 1,90\nBrutto 11,90"
    res = parse(text)
    assert res["deposit"]["value"] == 3.15

def test_skonto():
    text = "Skonto 2,00 EUR\nNetto 100,00\nMwSt 19,00\nBrutto 119,00"
    res = parse(text)
    assert res["skonto"]["value"] == 2.0

def test_missing_values():
    text = "Es wurden keine Beträge gefunden."
    res = parse(text)
    assert res["gross"] is None
    assert res["net"] is None

def test_false_math_combination():
    text = "Netto 100,00\nMwSt 19,00\nBrutto 120,00" # wrong math
    res = parse(text)
    assert res["math_valid"] is False

def test_negative_gross():
    text = "Gesamtbetrag -150,00\nNetto -126,05\n19% MwSt -23,95"
    res = parse(text)
    assert res["math_valid"] is True
    assert res["is_credit_note"] is True
    assert res["gross"]["value"] == -150.0

def test_rounding_two_cents():
    text = "Netto 100,00\n19% MwSt 19,01\nBrutto 119,03" # difference of 0.02
    res = parse(text)
    assert res["math_valid"] is True
    assert res["math_difference"] == 0.02

def test_currency_inference():
    text = "Das Dokument in USD\nGesamtbetrag 100,00\nNetto 84,03\n19% MwSt 15,97"
    res = parse(text)
    assert res["gross"]["currency"] == "USD"


def test_missing_currency():
    text = "Gesamtbetrag 100,00\nNetto 84,03\n19% MwSt 15,97"
    res = parse(text)
    assert res["gross"]["currency"] == "EUR"

def test_conflict_credit_note():
    text = "Gutschrift\nGesamtbetrag 100,00\nNetto 84,03\n19% MwSt 15,97\nNegativer Betrag -50,00"
    res = parse(text)
    assert res["is_credit_note"] is None
    assert len(res["conflicts"]) > 0
