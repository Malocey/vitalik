import argparse
from pathlib import Path
from src.wiki.wiki_engine import karpathy_wiki

def main():
    parser = argparse.ArgumentParser(description="Lint and repair VG Delikatessen LLM-Wiki")
    parser.add_argument("--wiki", help="Path to the wiki directory (optional, overrides default)")
    parser.add_argument("--output", help="Output directory for reports (optional)")
    parser.add_argument("--repair", action="store_true", help="Repair missing article type pages deterministically")

    args = parser.parse_args()

    # If a custom wiki dir is passed, update the karpathy_wiki instance
    if args.wiki:
        karpathy_wiki.wiki_dir = Path(args.wiki)

    print(f"Linting wiki at: {karpathy_wiki.wiki_dir}")
    if args.repair:
        print("Repair mode is ENABLED. Will generate missing article type pages.")

    report = karpathy_wiki.lint_wiki(output_dir=args.output, repair=args.repair)

    print(f"\nLint completed. Status: {report['status']}")
    print(f"Total pages scanned: {report['total_pages']}")

    if report['status'] != "HEALTHY":
        if report['orphan_pages']:
            print(f"- Orphans: {len(report['orphan_pages'])}")
        if report['broken_markdown_links']:
            print(f"- Broken MD Links: {len(report['broken_markdown_links'])}")
        if report['broken_wikilinks']:
            print(f"- Broken Wikilinks: {len(report['broken_wikilinks'])}")
        if report['duplicate_slugs']:
            print(f"- Duplicate Slugs: {len(report['duplicate_slugs'])}")
        if report['duplicate_entity_ids']:
            print(f"- Duplicate Entity IDs: {len(report['duplicate_entity_ids'])}")
        if report['invalid_frontmatters']:
            print(f"- Invalid Frontmatters: {len(report['invalid_frontmatters'])}")

        missing_sources = [s for s in report['missing_sources'] if s['status'] == 'MISSING_SOURCE']
        if missing_sources:
            print(f"- Missing Sources: {len(missing_sources)}")

if __name__ == "__main__":
    main()
