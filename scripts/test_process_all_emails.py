import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.parser.multi_format_engine import multi_format_engine
from src.core.email_decision_engine import email_decision_engine
from src.core.email_draft_generator import email_draft_generator


def process_all_test_emails():
    testdata_dir = PROJECT_ROOT / "data" / "testdata"
    eml_files = sorted(testdata_dir.glob("*.eml"))
    
    print(f"\n=======================================================")
    print(f"📧 E-MAIL KI-VERARBEITUNGS-BERICHT ({len(eml_files)} Test-Mails)")
    print(f"=======================================================\n")
    
    for idx, eml_file in enumerate(eml_files, 1):
        pages_info = multi_format_engine.extract_document(eml_file)
        full_text = pages_info[0]["full_text"] if pages_info else ""
        
        email_data = {
            "subject": eml_file.stem,
            "from": eml_file.name,
            "body": full_text
        }
        
        classification = email_decision_engine.classify_email(email_data)
        draft_res = email_draft_generator.generate_draft(email_data, classification)
        
        print(f"[{idx}] DATEI: {eml_file.name}")
        print(f"    ├─ LIEFERANT: {classification['supplier_name']}")
        print(f"    ├─ ABSICHT (INTENT): {classification['intent']}")
        print(f"    ├─ EMPFOHLENE AKTION: {classification['suggested_action']}")
        print(f"    └─ KI-ANTWORT-ENTWURF:\n")
        print("┌" + "─" * 60 + "┐")
        for line in draft_res["generated_draft"].split("\n"):
            print(f"│ {line:<58} │")
        print("└" + "─" * 60 + "┘\n")


if __name__ == "__main__":
    process_all_test_emails()
