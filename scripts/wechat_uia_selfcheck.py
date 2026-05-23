from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wx_ai_assistant.cli import main as cli_main  # noqa: E402


def main() -> int:
    sys.argv = [sys.argv[0], "selfcheck", *sys.argv[1:]]
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
