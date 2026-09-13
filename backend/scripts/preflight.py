"""Check a deployment before it serves traffic: `python -m scripts.preflight`.

Exits 0 when the config, the database revision and Redis are all fit to roll out, 1 with a list of problems otherwise.
Safe to run against a live deployment: it reads, it never writes.

``--config-only`` checks the env file alone, so it works before the stack is up (``--no-deps``).
"""

import argparse
import asyncio
import sys
from pathlib import Path

backend_dir = Path(__file__).parent.parent
sys.path.append(str(backend_dir))

from src.infrastructure.config.settings import settings  # noqa: E402
from src.infrastructure.deploy.preflight import config_problems, run_checks  # noqa: E402

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--config-only",
    action="store_true",
    help="Only check the configuration, skipping the database and Redis (they need not be running).",
)


async def main() -> None:
    args = parser.parse_args()
    problems = config_problems(settings) if args.config_only else await run_checks(settings)
    if not problems:
        print("preflight: ok")
        return

    print(f"preflight: {len(problems)} problem(s)\n")
    for problem in problems:
        print(f"  • {problem}")
    sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
