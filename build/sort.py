#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
from pathlib import Path

# --- Paths ---------------------------------------------------------------
# This script lives in a subfolder of the project root,
# the list lives in the project root.
SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent

INPUT_FILE = ROOT_DIR / "bogachenkoDNSFL.txt"   # in-place: read + overwrite

# --- Options -------------------------------------------------------------
SORT_SECTIONS = True          # sort sections inside each group (regex / domain / other)
SORT_WITHIN_SECTIONS = True   # sort rules inside each section

# --- Regexes -------------------------------------------------------------
SECTION_RE = re.compile(r'^\s*#\s*\[(.*?)\]\s*$')
# Match exact ||domain.name^ or ||domain.name lines.
# Ignores wildcards/regex inside the domain (/ \ ^ * ?).
DOMAIN_RE = re.compile(r"^\|\|([^/\^*?]+)\^?$")
# $denyallow=<list>   (stops at whitespace or at the next '$' flag)
DENYALLOW_RE = re.compile(r'\$denyallow=([^\s$]+)')


def section_key(line: str) -> str:
    """Sort key for a section header line '# [ ... ]'."""
    m = SECTION_RE.match(line)
    if m:
        return m.group(1).strip().lower()
    return line.strip().lower()


def normalize_denyallow(line: str) -> str:
    """Sort the domain list inside $denyallow=... alphabetically (case-insensitive)."""
    m = DENYALLOW_RE.search(line)
    if not m:
        return line

    domains = [d.strip() for d in m.group(1).split('|') if d.strip()]
    if len(domains) < 2:
        return line

    domains.sort(key=str.lower)
    return line[:m.start(1)] + '|'.join(domains) + line[m.end(1):]


def rule_key(line: str):
    """Sort key for a single rule line inside a section."""
    s = line.strip()

    # Section header inside a body (shouldn't normally happen, but be safe).
    m = SECTION_RE.match(s)
    if m:
        return (m.group(1).strip().lower(),)

    # Domain rules like ||example.com^ — sort by the domain itself.
    m = DOMAIN_RE.match(s)
    if m:
        return (m.group(1).lower(),)

    # Everything else (regexes, including those with $denyallow=...) — by full line.
    return (s.lower(),)


def parse_blocks(lines):
    """
    Returns:
      header - lines before the first '# [...]' section (title block)
      blocks - list of tuples (section_header_line, body_lines)
    """
    header = []
    blocks = []
    current_comment = None
    current_body = []

    for line in lines:
        if SECTION_RE.match(line):
            if current_comment is None:
                header.extend(current_body)
            else:
                blocks.append((current_comment, current_body))

            current_comment = line
            current_body = []
        else:
            if current_comment is None:
                header.append(line)
            else:
                current_body.append(line)

    if current_comment is None:
        header.extend(current_body)
    else:
        blocks.append((current_comment, current_body))

    return header, blocks


def sort_body(body):
    """Drop empty lines, normalize denyallow lists, then sort the rules."""
    entries = []
    for ln in body:
        if not ln.strip():
            continue
        entries.append(normalize_denyallow(ln))

    if SORT_WITHIN_SECTIONS:
        entries.sort(key=rule_key)

    return entries


def section_type(body) -> str:
    """
    Classify a section by its rule lines:
      'regex'  - every rule is a regex (starts with '/')
      'domain' - every rule is a domain rule (starts with '||')
      'other'  - everything else
    """
    rules = [ln.strip() for ln in body if ln.strip() and not ln.strip().startswith('#')]
    if not rules:
        return 'other'
    if all(r.startswith('/') for r in rules):
        return 'regex'
    if all(r.startswith('||') for r in rules):
        return 'domain'
    return 'other'


def main():
    try:
        text = INPUT_FILE.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"Error: The file '{INPUT_FILE}' was not found.")
        print("Make sure 'bogachenkoDNSFL.txt' is in the project root.")
        return

    lines = text.splitlines()

    header, blocks = parse_blocks(lines)

    # Split sections into groups: regex first, then domain, then the rest.
    regex_blocks, domain_blocks, other_blocks = [], [], []
    for comment, body in blocks:
        st = section_type(body)
        if st == 'regex':
            regex_blocks.append((comment, body))
        elif st == 'domain':
            domain_blocks.append((comment, body))
        else:
            other_blocks.append((comment, body))

    if SORT_SECTIONS:
        regex_blocks.sort(key=lambda b: section_key(b[0]))
        domain_blocks.sort(key=lambda b: section_key(b[0]))
        other_blocks.sort(key=lambda b: section_key(b[0]))

    # Title block (all '!' comments) stays on top; drop blank lines in it.
    header_clean = [ln for ln in header if ln.strip()]

    out = []
    out.extend(header_clean)

    # Regex rules always come first, right after the title.
    for group in (regex_blocks, domain_blocks, other_blocks):
        for comment, body in group:
            if out and out[-1] != "":
                out.append("")
            out.append(comment)
            out.extend(sort_body(body))

    # Overwrite the source file in place.
    INPUT_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"Done. Sorted in place: {INPUT_FILE}")


if __name__ == "__main__":
    main()