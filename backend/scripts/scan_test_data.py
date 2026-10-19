"""
scripts/scan_test_data.py
-------------------------
CI scan for real-looking personal identifiers and secrets in fixtures, test
data, dumps and scripts (ZP-PRIV D09). Uses the real checksums in
app/core/synthetic.py, so synthetic values (which fail them) never trip it.

Findings:
  iban          an IBAN with valid mod-97 check digits
  card          a Luhn-valid 13-19 digit card number with a card prefix
                (published processor test cards are allowed)
  bsn           an 11-proof-valid 9-digit number on a line mentioning BSN
  nino          a structurally valid UK NI number with an issued prefix
  pan           a structurally valid Indian PAN
  email         an address at a consumer mail provider (gmail, outlook, ...)
  secret        live payment keys, webhook signing secrets, cloud keys,
                private keys

Existing findings are recorded in docs/privacy/test_data_scan_baseline.json
(a ratchet: it may only shrink). Any finding not in the baseline fails.

    python -m scripts.scan_test_data [--update-baseline] [paths...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import synthetic  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
BASELINE = REPO / "docs" / "privacy" / "test_data_scan_baseline.json"
DEFAULT_PATHS = ("backend/tests", "backend/scripts", "backend/alembic", "deploy", "scripts", "frontend/src",
                 "frontend/scripts", "docs")
SUFFIXES = {".py", ".json", ".csv", ".sql", ".yaml", ".yml", ".txt", ".md", ".js", ".jsx", ".ts", ".sh", ".xml",
            ".log", ".dump", ".env"}
SKIP_DIRS = {"node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".git", "evidence"}
SELF = Path(__file__).resolve()

_TEST_CARDS = {"4242424242424242", "4000056655665556", "5555555555554444", "2223003122003222", "5200828282828210",
               "5105105105105100", "378282246310005", "371449635398431", "6011111111111117", "3056930009020004",
               "4000000000000002", "4000000000009995", "4000000000000077", "4000002500003155", "4111111111111111",
               "4000000000003220", "4000000000000341", "4000000000000069", "4000000000000127", "4000000000000119",
               "4000000000003063", "4000002760003184", "4000000000000101", "4000000000000036", "4000000760000002"}
_CONSUMER_MAIL = ("gmail.com", "googlemail.com", "yahoo.com", "yahoo.co.in", "yahoo.co.uk", "hotmail.com",
                  "outlook.com", "live.com", "icloud.com", "me.com", "aol.com", "protonmail.com", "proton.me",
                  "rediffmail.com", "gmx.de", "web.de", "mail.ru", "yandex.ru", "qq.com", "163.com")
_SECRETS = (
    ("secret", re.compile(r"\bsk_live_[A-Za-z0-9]{10,}")),
    ("secret", re.compile(r"\brk_live_[A-Za-z0-9]{10,}")),
    ("secret", re.compile(r"\bwhsec_[A-Za-z0-9]{16,}")),
    ("secret", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("secret", re.compile(r"-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("secret", re.compile(r"\"private_key\":\s*\"-----BEGIN")),
)
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b")
_CARD = re.compile(r"\b(?:4\d{12}(?:\d{3})?|5[1-5]\d{14}|2[2-7]\d{14}|3[47]\d{13}|6011\d{12})\b")
_NINE = re.compile(r"\b\d{9}\b")
_NINO = re.compile(r"\b[A-Z]{2}\d{6}[A-D]\b")
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def _fingerprint(kind: str, rel: str, value: str) -> str:
    return hashlib.sha256(f"{kind}|{rel}|{value}".encode()).hexdigest()[:20]


def scan_text(text: str, rel: str) -> list:
    out = []

    def add(kind, value, line_no):
        # Values are never stored, only a fingerprint and where it was.
        out.append({"kind": kind, "file": rel, "line": line_no, "fingerprint": _fingerprint(kind, rel, value)})

    for no, line in enumerate(text.splitlines(), 1):
        if "privacy-scan: allow" in line:
            continue
        for kind, pattern in _SECRETS:
            for m in pattern.finditer(line):
                add(kind, m.group(0), no)
        for m in _IBAN.finditer(line):
            if synthetic.iban_valid(m.group(0)):
                add("iban", m.group(0), no)
        for m in _CARD.finditer(line):
            if m.group(0) not in _TEST_CARDS and synthetic.luhn_valid(m.group(0)):
                add("card", m.group(0), no)
        if re.search(r"(?i)\bbsn\b|burgerservicenummer", line):
            for m in _NINE.finditer(line):
                if synthetic.bsn_valid(m.group(0)):
                    add("bsn", m.group(0), no)
        for m in _NINO.finditer(line):
            if synthetic.nino_valid(m.group(0)):
                add("nino", m.group(0), no)
        for m in _PAN.finditer(line):
            if synthetic.pan_valid(m.group(0)):
                add("pan", m.group(0), no)
        for m in _EMAIL.finditer(line):
            if m.group(1).lower() in _CONSUMER_MAIL:
                add("email", m.group(0).lower(), no)
    return out


def scan(paths) -> list:
    findings = []
    for base in paths:
        root = (REPO / base) if not Path(base).is_absolute() else Path(base)
        files = [root] if root.is_file() else (root.rglob("*") if root.exists() else [])
        for f in files:
            if not f.is_file() or f.resolve() == SELF or f.suffix.lower() not in SUFFIXES:
                continue
            if any(part in SKIP_DIRS for part in f.parts) or f.name == BASELINE.name:
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            rel = f.resolve().relative_to(REPO).as_posix() if REPO in f.resolve().parents else str(f)
            findings.extend(scan_text(text, rel))
    return findings


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Scan fixtures, dumps and scripts for real-looking identifiers.")
    parser.add_argument("paths", nargs="*", default=list(DEFAULT_PATHS))
    parser.add_argument("--update-baseline", action="store_true")
    parser.add_argument("--baseline", type=Path, default=BASELINE)
    args = parser.parse_args(argv)
    findings = scan(args.paths)
    known = set()
    if args.baseline.exists():
        known = {f["fingerprint"] for f in json.loads(args.baseline.read_text(encoding="utf-8"))["findings"]}
    if args.update_baseline:
        keep = sorted((f for f in findings), key=lambda f: (f["file"], f["line"], f["kind"]))
        args.baseline.write_text(json.dumps({"note": "Ratchet: may only shrink. Values are never stored.",
                                             "findings": [{k: f[k] for k in ("kind", "file", "fingerprint")}
                                                          for f in keep]}, indent=2) + "\n", encoding="utf-8")
        print(f"baseline written: {len(keep)} finding(s)")
        return 0
    new = [f for f in findings if f["fingerprint"] not in known]
    for f in new:
        print(f"NEW  {f['kind']:<7} {f['file']}:{f['line']}")
    print(f"{len(findings)} finding(s), {len(new)} not in the baseline")
    return 1 if new else 0


if __name__ == "__main__":
    raise SystemExit(main())
