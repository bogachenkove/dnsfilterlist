#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from collections import defaultdict
from pathlib import Path

# --- Paths ---------------------------------------------------------------
# This script lives in a subfolder of the project root,
# the list lives in the project root.
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent

INPUT_FILE = ROOT_DIR / "bogachenkoDNSFL.txt"

# --- Regexes -------------------------------------------------------------
# Match exact ||domain.name^ or ||domain.name lines.
# Ignores wildcards/regex inside the domain (/ \ ^ * ?).
DOMAIN_RE = re.compile(r"^\|\|([^/\^*?]+)\^?$")


def find_duplicate_domains(file_path: Path):
    domain_map = defaultdict(list)

    with file_path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()

            # Skip empty lines and comments (both '#' and '!').
            if not line or line[0] in "#!":
                continue

            match = DOMAIN_RE.match(line)
            if not match:
                continue

            # Domains are case-insensitive -> normalize for comparison.
            domain = match.group(1).lower()
            domain_map[domain].append((line_num, line))

    duplicates_found = False
    print("=== Searching for Duplicate Domains ===")

    for domain, entries in domain_map.items():
        if len(entries) > 1:
            duplicates_found = True
            lines_str = ", ".join(str(n) for n, _ in entries)
            print(f"Domain [ {domain} ] found {len(entries)} times (lines: {lines_str})")
            for n, content in entries:
                print(f"    line {n}: {content}")

    if not duplicates_found:
        print("No duplicates found. Your list is clean!")


def main():
    try:
        find_duplicate_domains(INPUT_FILE)
    except FileNotFoundError:
        print(f"Error: The file '{INPUT_FILE}' was not found.")
        print("Make sure 'bogachenkoDNSFL.txt' is in the project root.")


if __name__ == "__main__":
    main()