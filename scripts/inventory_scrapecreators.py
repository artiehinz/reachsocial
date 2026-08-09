"""Build a sanitized, review-only inventory from ScrapeCreators OpenAPI.

This command never reads a provider token and never changes the live service
catalog. Its output is an engineering queue, not an availability claim.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from reachsocial.provider_inventory import DEFAULT_SOURCE, build_inventory, load_openapi


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    inventory = build_inventory(load_openapi(args.source), source=args.source)
    rendered = json.dumps(inventory, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
        print(
            f"Wrote {inventory['summary']['operations']} review candidates to {args.output}"
        )
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
