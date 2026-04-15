"""CLI tool for managing the vocabulary brain.

Usage:
    python vocab.py add "Freek" --hint "freak" --priority high
    python vocab.py add "Claude Code" --hint "claud coat"
    python vocab.py remove "Freek"
    python vocab.py list
    python vocab.py corrections
    python vocab.py export brain_export.json
    python vocab.py import brain_export.json
    python vocab.py stats
"""

import argparse
import sys
from pathlib import Path

from brain import VocabularyBrain
from config import load_config


def get_brain() -> VocabularyBrain:
    config = load_config()
    db_path = Path(__file__).parent / config["brain"]["db_path"]
    return VocabularyBrain(db_path)


def cmd_add(args):
    brain = get_brain()
    row_id = brain.add_term(
        args.term,
        phonetic_hint=args.hint,
        priority=args.priority,
    )
    if row_id:
        print(f"Added: {args.term}" + (f" (sounds like: {args.hint})" if args.hint else ""))
    else:
        print(f"Already exists: {args.term}")
    brain.close()


def cmd_remove(args):
    brain = get_brain()
    if brain.remove_term(args.term):
        print(f"Removed: {args.term}")
    else:
        print(f"Not found: {args.term}")
    brain.close()


def cmd_list(args):
    brain = get_brain()
    terms = brain.get_all_terms()
    if not terms:
        print("No vocabulary entries.")
        brain.close()
        return

    # Column widths
    max_term = max(len(t["term"]) for t in terms)
    max_hint = max((len(t["phonetic_hint"] or "") for t in terms), default=0)

    print(f"{'Term':<{max_term+2}} {'Hint':<{max(max_hint+2, 6)}} {'Pri':<8} {'Freq':<6} {'Source':<8}")
    print("-" * (max_term + max_hint + 36))
    for t in terms:
        hint = t["phonetic_hint"] or ""
        print(f"{t['term']:<{max_term+2}} {hint:<{max(max_hint+2, 6)}} {t['priority']:<8} {t['frequency']:<6} {t['source']:<8}")

    print(f"\nTotal: {len(terms)} terms")
    brain.close()


def cmd_corrections(args):
    brain = get_brain()
    corrections = brain.get_corrections(limit=args.limit)
    if not corrections:
        print("No corrections logged.")
        brain.close()
        return

    print(f"{'Original':<30} {'Corrected':<30} {'When'}")
    print("-" * 80)
    for c in corrections:
        print(f"{c['original']:<30} {c['corrected']:<30} {c['created_at']}")

    # Show patterns
    patterns = brain.get_correction_patterns(min_count=2)
    if patterns:
        print(f"\nRepeated patterns (threshold for auto-learn: see config):")
        for p in patterns:
            print(f"  {p['original']!r} → {p['corrected']!r} ({p['count']}x)")

    print(f"\nTotal corrections: {brain.correction_count()}")
    brain.close()


def cmd_export(args):
    brain = get_brain()
    brain.export_to_file(args.path)
    data = brain.export_json()
    print(f"Exported {len(data['vocabulary'])} terms, {len(data['corrections'])} corrections to {args.path}")
    brain.close()


def cmd_import(args):
    brain = get_brain()
    path = Path(args.path)
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)
    brain.import_from_file(path)
    print(f"Imported from {path}. Total terms: {brain.term_count()}")
    brain.close()


def cmd_stats(args):
    brain = get_brain()
    terms = brain.term_count()
    corrections = brain.correction_count()
    high_pri = len(brain.get_high_priority_terms())
    auto_terms = len([t for t in brain.get_all_terms() if t["source"] == "auto"])
    cached = brain.get_cached_prompt()

    print(f"Vocabulary Brain Stats")
    print(f"  Database:     {brain.db_path}")
    print(f"  Terms:        {terms} ({high_pri} high priority, {auto_terms} auto-learned)")
    print(f"  Corrections:  {corrections}")
    print(f"  Cached prompt: {'Yes (' + str(len(cached)) + ' chars)' if cached else 'None'}")

    patterns = brain.get_correction_patterns(min_count=2)
    if patterns:
        config = load_config()
        threshold = config["brain"]["auto_learn_threshold"]
        pending = [p for p in patterns if p["count"] < threshold]
        if pending:
            print(f"\n  Pending auto-learn (need {threshold} corrections):")
            for p in pending:
                print(f"    {p['original']!r} → {p['corrected']!r} ({p['count']}/{threshold})")

    brain.close()


def main():
    parser = argparse.ArgumentParser(
        description="Manage the vocabulary brain database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = sub.add_parser("add", help="Add a vocabulary term")
    p_add.add_argument("term", help="The term to add")
    p_add.add_argument("--hint", help="Phonetic hint (how it sounds when misrecognized)")
    p_add.add_argument("--priority", choices=["normal", "high"], default="normal",
                        help="Priority level (high = always in Whisper prompt)")
    p_add.set_defaults(func=cmd_add)

    # remove
    p_rm = sub.add_parser("remove", help="Remove a vocabulary term")
    p_rm.add_argument("term", help="The term to remove")
    p_rm.set_defaults(func=cmd_remove)

    # list
    p_list = sub.add_parser("list", help="List all vocabulary terms")
    p_list.set_defaults(func=cmd_list)

    # corrections
    p_corr = sub.add_parser("corrections", help="Show correction history")
    p_corr.add_argument("--limit", type=int, default=50, help="Max corrections to show")
    p_corr.set_defaults(func=cmd_corrections)

    # export
    p_exp = sub.add_parser("export", help="Export vocabulary to JSON")
    p_exp.add_argument("path", help="Output JSON file path")
    p_exp.set_defaults(func=cmd_export)

    # import
    p_imp = sub.add_parser("import", help="Import vocabulary from JSON")
    p_imp.add_argument("path", help="Input JSON file path")
    p_imp.set_defaults(func=cmd_import)

    # stats
    p_stats = sub.add_parser("stats", help="Show brain statistics")
    p_stats.set_defaults(func=cmd_stats)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
