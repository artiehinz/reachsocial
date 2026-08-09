#!/usr/bin/env python3
"""Calculate conservative ScrapeCreators unit economics without making a call."""

from __future__ import annotations

import argparse
import json
from decimal import Decimal

from reachsocial.economics import scrapecreators_cost_report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert an actual ScrapeCreators pack price into conservative micro-USD costs."
    )
    parser.add_argument("--pack-price-usd", required=True, type=Decimal)
    parser.add_argument("--credits", required=True, type=int)
    args = parser.parse_args()
    try:
        report = scrapecreators_cost_report(args.pack_price_usd, args.credits)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
