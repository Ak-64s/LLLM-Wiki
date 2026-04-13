import argparse
import sys
from pathlib import Path

from src.core.config import load_config
from src.core.lint import format_report, run_all_checks


def main() -> None:
    parser = argparse.ArgumentParser(description="Run wiki health checks.")
    parser.add_argument("--save", action="store_true", help="Write report to lint-report.md")
    args = parser.parse_args()

    cfg = load_config()
    vault_path = Path(cfg.vault_path)

    try:
        report = run_all_checks(str(vault_path))
        output = format_report(report)
        print(output)

        if args.save:
            report_path = vault_path / "wiki" / "lint-report.md"
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(output, encoding="utf-8")
            print(f"\nReport saved to {report_path.as_posix()}")

    except SystemExit as e:
        print(f"Error: {e.code}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
