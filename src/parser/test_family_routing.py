import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

from src.drive.sorter import determine_destination_folder

def run_tests():
    tests = [
        {"desc": "Test 1: World wide food", "doc": {"raw_text": "Rechnung von World wide food", "datum": "2026-05-14", "belegtyp": "Rechnung"}, "expected": "01_Eingangsarchiv/2026/05_Mai/Rechnungen"},
        {"desc": "Test 2: Jensmann", "doc": {"raw_text": "Lieferschein Jensmann Gmbh", "datum": "2026-10-10", "belegtyp": "Lieferschein"}, "expected": "01_Eingangsarchiv/2026/10_Oktober/Lieferscheine"},
        {"desc": "Test 3: Vitali Gebel", "doc": {"raw_text": "Herr Vitali Gebel", "datum": "2026-01-01"}, "expected": "05_Privat_Familie/Vitali_Gebel/2026"},
        {"desc": "Test 4: Max Gebel", "doc": {"raw_text": "Max Gebel privatrechnung", "datum": "2026-03-03"}, "expected": "05_Privat_Familie/Max_Gebel/2026"}
    ]

    passed = 0
    for t in tests:
        res = determine_destination_folder(t["doc"])
        if res == t["expected"]:
            print(f"✅ {t['desc']} -> {res}")
            passed += 1
        else:
            print(f"❌ {t['desc']} failed. Expected: {t['expected']}, Got: {res}")

    print(f"\n{passed}/{len(tests)} tests passed.")

if __name__ == "__main__":
    run_tests()
