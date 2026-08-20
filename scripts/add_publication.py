#!/usr/bin/env python3
"""Add or refresh publications in _data/publications.yml using the ADS API.

Setup (once)
------------
Get a token from https://ui.adsabs.harvard.edu/user/settings/token and either

    export ADS_API_TOKEN="your-token"        # e.g. in ~/.zshrc

or save it to ~/.ads/dev_key (the same file the `ads` Python package uses).

Usage
-----
    # Add a paper. Accepts an ADS bibcode, an arXiv ID, or a DOI.
    python3 scripts/add_publication.py 2025arXiv251024849W
    python3 scripts/add_publication.py arXiv:2510.24849 --category first
    python3 scripts/add_publication.py 10.1093/mnras/stac3625

    # Print the entry without writing it, to check it first.
    python3 scripts/add_publication.py 2024AJ....167..208W --dry-run

    # Keep every author instead of truncating to three plus "et al."
    python3 scripts/add_publication.py <id> --all-authors

    # Check every entry against ADS and report preprints that have since been
    # published, along with any journal/volume/page that has changed.
    python3 scripts/add_publication.py --refresh
    python3 scripts/add_publication.py --refresh --write   # apply the updates

Only the standard library is used, so there is nothing to install.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.adsabs.harvard.edu/v1/search/query"
FIELDS = ("bibcode,alternate_bibcode,title,author,year,pub,volume,page,"
          "doi,identifier,pubdate,doctype")

REPO = Path(__file__).resolve().parent.parent
DATA_FILE = REPO / "_data" / "publications.yml"

BATCH = 20          # identifiers per ADS request

# Who "--jack" means. Edit this if your name is indexed differently on ADS, or
# to widen/narrow the year range.
ME = 'author:"Warfield, Jack" year:2018-'

# Conference abstracts are excluded from --jack by default: ADS indexes every
# AAS meeting abstract and they swamp the real papers. --all-doctypes keeps them.
NOISY_DOCTYPES = {"abstract"}


# --------------------------------------------------------------------------
# ADS access
# --------------------------------------------------------------------------

def get_token():
    token = os.environ.get("ADS_API_TOKEN") or os.environ.get("ADS_DEV_KEY")
    if token:
        return token.strip()
    keyfile = Path.home() / ".ads" / "dev_key"
    if keyfile.exists():
        return keyfile.read_text().strip()
    sys.exit(
        "No ADS token found.\n"
        "  Get one at https://ui.adsabs.harvard.edu/user/settings/token\n"
        "  then: export ADS_API_TOKEN='...'  (or save it to ~/.ads/dev_key)"
    )


def query(q, token, rows=1, sort=None):
    params = {"q": q, "fl": FIELDS, "rows": rows}
    if sort:
        params["sort"] = sort
    url = f"{API}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        sys.exit(f"ADS returned HTTP {exc.code}: {body}")
    except urllib.error.URLError as exc:
        sys.exit(f"Could not reach ADS: {exc.reason}")
    return payload.get("response", {}).get("docs", [])


def normalise(ident):
    """A bare arXiv number needs the arXiv: prefix to be recognised."""
    ident = ident.strip()
    if re.fullmatch(r"\d{4}\.\d{4,5}(v\d+)?", ident):
        return "arXiv:" + ident
    return ident


def build_query(identifier):
    """Turn a bibcode / arXiv ID / DOI into an ADS query string.

    Always uses `identifier:`, never `bibcode:`. `bibcode:` matches only a
    record's *canonical* bibcode, so it silently returns nothing for the arXiv
    bibcode of any paper that has since been published -- which is exactly the
    case --refresh exists to find. `identifier:` matches arXiv IDs, DOIs, and
    both canonical and alternate bibcodes.
    """
    ident = normalise(identifier)
    if ident.startswith("10."):
        return f'doi:"{ident}"'
    return f'identifier:"{ident}"'


def doc_identifiers(doc):
    """Every string ADS knows this record by, lowercased."""
    names = {doc.get("bibcode", "")}
    names.update(doc.get("alternate_bibcode", []) or [])
    names.update(doc.get("identifier", []) or [])
    return {n.lower() for n in names if n}


def lookup_many(codes, token):
    """Map each requested identifier to its ADS record (or None)."""
    found = {}
    for i in range(0, len(codes), BATCH):
        chunk = codes[i:i + BATCH]
        clause = " OR ".join(f'"{normalise(c)}"' for c in chunk)
        docs = query(f"identifier:({clause})", token, rows=len(chunk) * 2)
        for code in chunk:
            want = normalise(code).lower()
            for doc in docs:
                if want in doc_identifiers(doc):
                    found[code] = doc
                    break
    return {c: found.get(c) for c in codes}


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------

def format_author(name):
    """'Warfield, Jack T.' -> 'J. T. Warfield'."""
    if "," not in name:
        return name.strip()
    surname, given = name.split(",", 1)
    initials = [p[0].upper() + "." for p in given.replace(".", " ").split() if p]
    return " ".join(initials + [surname.strip()])


def arxiv_id(doc):
    for ident in doc.get("identifier", []) or []:
        if ident.lower().startswith("arxiv:"):
            return ident.split(":", 1)[1]
    return None


def first(value):
    """ADS returns several fields as one-element lists."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


JOURNAL_ABBREV = {
    "The Astrophysical Journal": "ApJ",
    "The Astrophysical Journal Supplement Series": "ApJS",
    "The Astronomical Journal": "AJ",
    "Monthly Notices of the Royal Astronomical Society": "MNRAS",
    "Research Notes of the American Astronomical Society": "Res. Notes AAS",
    "Astronomy and Astrophysics": "A&A",
    "Publications of the Astronomical Society of the Pacific": "PASP",
    "Nature Astronomy": "Nat. Astron.",
    "The Open Journal of Astrophysics": "OJAp",
}


def abbreviate(pub):
    if not pub:
        return None
    return JOURNAL_ABBREV.get(pub.strip(), pub.strip())


def is_preprint(doc):
    """True while a record is still only an arXiv posting."""
    pub = (first(doc.get("pub")) or "").lower()
    return not doc.get("volume") and ("arxiv" in pub or "arxiv" in doc.get("bibcode", "").lower())


def yaml_quote(text):
    """Quote a scalar only when YAML needs it."""
    text = str(text).replace("\n", " ").strip()
    if text[:1] in "-?:,[]{}#&*!|>'\"%@`" or ": " in text or " #" in text:
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def to_entry(doc, category, all_authors):
    authors = [format_author(a) for a in doc.get("author", []) or []]
    if not all_authors and len(authors) > 3:
        authors = authors[:3] + ["et al."]

    pub = abbreviate(first(doc.get("pub")))
    preprint_only = is_preprint(doc)

    lines = [f"  - title: {yaml_quote(first(doc.get('title')) or 'UNTITLED')}"]
    lines.append("    authors: [" + ", ".join(f'"{a}"' for a in authors) + "]")
    lines.append(f"    year: {doc.get('year', '')}")

    if pub and not preprint_only:
        lines.append(f"    journal: {yaml_quote(pub)}")
        if doc.get("volume"):
            lines.append(f"    volume: {doc['volume']}")
        if doc.get("page"):
            lines.append(f"    page: {yaml_quote(first(doc['page']))}")
    arx = arxiv_id(doc)
    if arx:
        lines.append(f'    preprint: "{arx}"')
    if preprint_only:
        lines.append("    status: submitted   # <- edit me")
    if doc.get("doi"):
        lines.append(f"    doi: {yaml_quote(first(doc['doi']))}")
    lines.append(f"    bibcode: {doc['bibcode']}")
    lines.append(f"    category: {category}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Reading and rewriting the data file
# --------------------------------------------------------------------------

FIELD_ORDER = ["title", "authors", "year", "journal", "volume", "page",
               "preprint", "status", "doi", "bibcode", "category", "links"]


def split_entries(text):
    """(header, [entry blocks]). Only looks after the top-level `entries:` key,
    so the list of categories above it is left alone."""
    marker = re.search(r"^entries:[ \t]*$", text, re.M)
    if not marker:
        sys.exit("Could not find the `entries:` key in publications.yml.")
    head, body = text[:marker.end()], text[marker.end():]
    starts = [m.start() for m in re.finditer(r"^  - ", body, re.M)]
    if not starts:
        return head + body, []
    return head + body[:starts[0]], [
        body[a:b] for a, b in zip(starts, starts[1:] + [len(body)])
    ]


def get_field(block, key):
    """Read a single-line field. Handles `title`, which sits on the block's
    opening "  - " line rather than at the usual four-space indent."""
    m = re.search(rf"^(?:    |  - ){key}:[ \t]*(.*?)[ \t]*$", block, re.M)
    return m.group(1) if m else None


def set_field(block, key, value):
    """Set a single-line field, inserting it in canonical order if absent."""
    line = f"    {key}: {value}"
    if re.search(rf"^    {key}:", block, re.M):
        return re.sub(rf"^    {key}:.*$", line.replace("\\", "\\\\"), block,
                      count=1, flags=re.M)

    body = block.rstrip("\n")
    tail = block[len(body):]          # keep the blank line between entries
    lines = body.split("\n")
    try:
        after = FIELD_ORDER[:FIELD_ORDER.index(key)]
    except ValueError:
        after = FIELD_ORDER
    insert_at = len(lines)
    for i, ln in enumerate(lines):
        m = re.match(r"^    ([a-z_]+):", ln)
        if m and m.group(1) not in after and m.group(1) in FIELD_ORDER:
            insert_at = i
            break
    lines.insert(insert_at, line)
    return "\n".join(lines) + tail


def drop_field(block, key):
    """Remove a single-line field."""
    return re.sub(rf"^    {key}:.*\n", "", block, count=1, flags=re.M)


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------

def known_identifiers(text):
    """Every identifier the data file already knows about, lowercased."""
    ids = set()
    for m in re.finditer(r"^\s+(?:bibcode|doi):[ \t]*(.+?)[ \t]*$", text, re.M):
        ids.add(m.group(1).strip().strip('"').lower())
    for m in re.finditer(r"^\s+preprint:[ \t]*(.+?)[ \t]*$", text, re.M):
        value = m.group(1).strip().strip('"').lower()
        ids.add(value)
        ids.add("arxiv:" + value)
    return ids


def describe(doc):
    """Two or three lines a human can judge a paper from."""
    authors = [format_author(a) for a in doc.get("author", []) or []]
    shown = ", ".join(authors[:3]) + (", et al." if len(authors) > 3 else "")
    pub = abbreviate(first(doc.get("pub")))
    if is_preprint(doc):
        venue = f"arXiv:{arxiv_id(doc) or '?'}"
    else:
        bits = [pub or "?"]
        if doc.get("volume"):
            bits.append(str(doc["volume"]))
        if doc.get("page"):
            bits.append(str(first(doc["page"])))
        venue = " ".join(bits[:1]) + (" " + ", ".join(bits[1:]) if bits[1:] else "")
    return first(doc.get("title")) or "UNTITLED", shown, venue, doc.get("year", "?")


def insert_entries(text, additions):
    """Put each new entry at the TOP of its category group, so a new paper shows
    up first rather than at the bottom of the page."""
    head, blocks = split_entries(text)
    for category, entry in additions:
        block = entry.rstrip("\n") + "\n\n"
        idx = next((i for i, b in enumerate(blocks)
                    if get_field(b, "category") == category), None)
        if idx is None:
            if blocks and not blocks[-1].endswith("\n\n"):
                blocks[-1] = blocks[-1].rstrip("\n") + "\n\n"
            blocks.append(block)
        else:
            blocks.insert(idx, block)
    return (head + "".join(blocks)).rstrip("\n") + "\n"


def ask_category(categories):
    """Prompt for one paper. Returns a category id, None to skip, or 'QUIT'."""
    menu = "  ".join(f"[{i}] {c}" for i, c in enumerate(categories, 1))
    prompt = f"    {menu}   [s]kip  [q]uit > "
    while True:
        try:
            answer = input(prompt).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return "QUIT"
        if answer in ("q", "quit"):
            return "QUIT"
        if answer in ("", "s", "skip", "n", "no"):
            return None
        if answer.isdigit() and 1 <= int(answer) <= len(categories):
            return categories[int(answer) - 1]
        if answer in categories:
            return answer
        print(f"    Not one of {', '.join(categories)}. Try again.")


def cmd_jack(args, token):
    text = DATA_FILE.read_text()
    data_categories = [
        m.group(1) for m in re.finditer(r"^  - id:[ \t]*(\S+)", text, re.M)
    ]
    if not data_categories:
        sys.exit("No categories found at the top of publications.yml.")

    print(f"Querying ADS for:  {ME}\n")
    docs = query(ME, token, rows=args.rows, sort="date desc")
    if not docs:
        sys.exit("ADS returned nothing. Check the ME query at the top of this script.")

    dropped = 0
    if not args.all_doctypes:
        keep = [d for d in docs if d.get("doctype") not in NOISY_DOCTYPES]
        dropped = len(docs) - len(keep)
        docs = keep

    known = known_identifiers(text)
    missing = [d for d in docs if not (doc_identifiers(d) & known)]

    print(f"{len(docs)} record{'' if len(docs) == 1 else 's'} on ADS"
          + (f" ({dropped} conference abstract{'' if dropped == 1 else 's'} hidden;"
              f" --all-doctypes shows them)"
             if dropped else "")
          + f"; {len(docs) - len(missing)} already in publications.yml.\n")

    if not missing:
        print("Nothing new. You are up to date.")
        return

    if args.dry_run or not sys.stdin.isatty():
        why = "--dry-run" if args.dry_run else "not a terminal, so not prompting"
        print(f"{len(missing)} not in the file ({why}):\n")
        for doc in missing:
            title, authors, venue, year = describe(doc)
            print(f"  {year}  {title}")
            print(f"        {authors}")
            print(f"        {venue}   {doc['bibcode']}\n")
        return

    print(f"{len(missing)} not in the file. For each one, pick a category.\n")

    additions = []
    for i, doc in enumerate(missing, 1):
        title, authors, venue, year = describe(doc)
        print(f"[{i}/{len(missing)}]  {year}   {venue}")
        print(f"    {title}")
        print(f"    {authors}")
        choice = ask_category(data_categories)
        print()
        if choice == "QUIT":
            print("Stopped.")
            break
        if choice is None:
            continue
        additions.append((choice, to_entry(doc, choice, args.all_authors)))

    if not additions:
        print("Nothing added.")
        return

    DATA_FILE.write_text(insert_entries(text, additions))
    print(f"Added {len(additions)} "
          f"entr{'y' if len(additions) == 1 else 'ies'} to {DATA_FILE.name}:")
    for category, entry in additions:
        print(f"  {category:12} {get_field(entry, 'title')[:60]}")
    print("\nEach was placed at the top of its category. Check the rendered page,")
    print("and fix any `status:` line the script guessed at.")


def cmd_add(args, token):
    docs = query(build_query(args.identifier), token)
    if not docs:
        sys.exit(f"ADS found nothing for {args.identifier!r}.")
    doc = docs[0]

    text = DATA_FILE.read_text()
    if doc["bibcode"] in text:
        sys.exit(f"{doc['bibcode']} is already in {DATA_FILE.name}. Nothing to do.")

    entry = to_entry(doc, args.category, args.all_authors)
    print(entry)

    if args.dry_run:
        print("\n(--dry-run: nothing written)")
        return

    with DATA_FILE.open("a") as handle:
        handle.write("\n" + entry + "\n")
    print(f"\nAppended to {DATA_FILE.relative_to(REPO)}.")
    print("Entries are grouped by category automatically, but they appear in file")
    print("order within a group -- move it up if you want it listed first.")


def plan_update(block, doc):
    """What would change for one entry. Returns (changes, new_block)."""
    changes, new = [], block

    canonical = doc["bibcode"]
    if get_field(block, "bibcode") != canonical:
        changes.append(f"bibcode -> {canonical}")
        new = set_field(new, "bibcode", canonical)

    if not is_preprint(doc):
        pub = abbreviate(first(doc.get("pub")))
        for key, value in (("journal", pub),
                           ("volume", doc.get("volume")),
                           ("page", first(doc.get("page")))):
            if value in (None, ""):
                continue
            value = yaml_quote(value)
            if get_field(new, key) != value:
                changes.append(f"{key} -> {value}")
                new = set_field(new, key, value)

        if get_field(new, "status") is not None:
            changes.append("status removed (now published)")
            new = drop_field(new, "status")

    if doc.get("doi") and get_field(new, "doi") is None:
        new = set_field(new, "doi", yaml_quote(first(doc["doi"])))
        changes.append("doi added")

    arx = arxiv_id(doc)
    if arx and get_field(new, "preprint") is None:
        new = set_field(new, "preprint", f'"{arx}"')
        changes.append("preprint added")

    return changes, new


def cmd_refresh(args, token):
    text = DATA_FILE.read_text()
    head, blocks = split_entries(text)

    codes = [get_field(b, "bibcode") for b in blocks]
    known = [c for c in codes if c]
    print(f"Checking {len(known)} of {len(blocks)} entries against ADS...\n")

    docs = lookup_many(known, token)
    updated, changed_count, missing = [], 0, []

    for block, code in zip(blocks, codes):
        doc = docs.get(code) if code else None
        if code and doc is None:
            missing.append(code)
            updated.append(block)
            continue
        if doc is None:
            updated.append(block)
            continue

        changes, new_block = plan_update(block, doc)
        if changes:
            changed_count += 1
            title = (get_field(block, "title") or "?").strip('"')
            print(f"  {title[:64]}")
            for c in changes:
                print(f"      {c}")
            print()
        updated.append(new_block)

    for code in missing:
        print(f"  ?  {code} -- ADS has no record with that identifier")
    if missing:
        print()

    if not changed_count:
        print("Everything is up to date.")
        return

    if args.write:
        DATA_FILE.write_text(head + "".join(updated))
        print(f"Updated {changed_count} entr{'y' if changed_count == 1 else 'ies'} "
              f"in {DATA_FILE.name}.")
    else:
        print(f"{changed_count} entr{'y' if changed_count == 1 else 'ies'} out of "
              f"date. Re-run with --write to apply.")


def main():
    parser = argparse.ArgumentParser(
        description="Add or refresh entries in _data/publications.yml from ADS.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("identifier", nargs="?",
                        help="ADS bibcode, arXiv ID, or DOI")
    parser.add_argument("-c", "--category", default="other",
                        help="category id from publications.yml (default: other)")
    parser.add_argument("--all-authors", action="store_true",
                        help="keep the full author list instead of 3 + et al.")
    parser.add_argument("-n", "--dry-run", action="store_true",
                        help="print the entry without writing it")
    parser.add_argument("--jack", action="store_true",
                        help="list your ADS papers that are missing from the "
                             "data file and offer to add each one")
    parser.add_argument("--rows", type=int, default=300,
                        help="with --jack, how many ADS records to fetch")
    parser.add_argument("--all-doctypes", action="store_true",
                        help="with --jack, include conference abstracts")
    parser.add_argument("--refresh", action="store_true",
                        help="check existing entries for published versions")
    parser.add_argument("--write", action="store_true",
                        help="with --refresh, apply the updates")
    args = parser.parse_args()

    if not DATA_FILE.exists():
        sys.exit(f"Cannot find {DATA_FILE}. Run this from inside the site repo.")

    token = get_token()
    if args.jack:
        cmd_jack(args, token)
    elif args.refresh:
        cmd_refresh(args, token)
    elif args.identifier:
        cmd_add(args, token)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
