"""
scripts/verify_mexico_sources.py
--------------------------------
Mexico Phase 1 evidence tooling (ZP-MX-ENG-001). Read-only against the
database — it never touches it; it reads/writes only
docs/mexico/sources/SOURCES_MANIFEST.csv and VERIFICATION_LOG.csv beside it.

Subcommands:
  hash                 add every new file in docs/mexico/sources/ to the
                       manifest as UNVERIFIED (sha256, bytes, content type,
                       text layer). An existing row is never overwritten
                       (only blanks are filled); a changed file is refused
  header CODE [N]      print the first N text lines of a source (default 40),
                       to read its title / issuer / reform date
  set CODE k=v …       record title / issuer / url / header_version /
                       status / note for one source (never status=VERIFIED)
  verify CODE downloader=NAME [file=F]
                       the ONLY way a source becomes VERIFIED (Phase 11d):
                       a fresh direct download from the row's official URL
                       (never an archive host) must hash to the saved copy.
                       Every attempt is appended to VERIFICATION_LOG.csv
                       (downloader, timestamp, URL, response size, SHA-256,
                       MATCH / MISMATCH); only a MATCH sets VERIFIED
  check                every manifest row's file exists and still hashes to
                       the recorded SHA-256 (exit 1 otherwise)
  compare              the independent machine check (Phase 1 plan §3):
                       every transcribed number in mexico_content.py must be
                       found in the text of the VERIFIED file its row cites —
                       an ISR bracket's four numbers on ONE line of S2
                       (exit 1 on any miss; empty content checks 0 rows)

Statuses: UNVERIFIED (hashed, not yet checked), VERIFIED (right document and
version, downloaded directly from its official URL — set only by `verify`,
and counted only with its MATCH entry in the log), ARCHIVE_COPY_VERIFIED (an
Internet Archive raw capture of the official URL, checked against the
archive's digest — Phase 11a), WRONG_VERSION, INCOMPLETE, NO_TEXT_LAYER.
VERIFIED and ARCHIVE_COPY_VERIFIED files can back a row in a Draft pack
(seed_mexico_canonical_packs.py); activation needs VERIFIED (Phase 11d).

Usage:
    python -m scripts.verify_mexico_sources hash
"""
import csv
import hashlib
import mimetypes
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCES_DIR = REPO_ROOT / "docs" / "mexico" / "sources"
MANIFEST_PATH = SOURCES_DIR / "SOURCES_MANIFEST.csv"
COLUMNS = ("code", "title", "issuer", "url", "file", "sha256", "bytes", "retrieved_at", "content_type",
           "header_version", "text_layer", "status", "note")
STATUSES = ("UNVERIFIED", "VERIFIED", "ARCHIVE_COPY_VERIFIED", "WRONG_VERSION", "INCOMPLETE", "NO_TEXT_LAYER")
EDITABLE = ("title", "issuer", "url", "header_version", "status", "note")
LOG_NAME = "VERIFICATION_LOG.csv"
LOG_COLUMNS = ("code", "file", "url", "final_url", "downloaded_at", "downloader", "response_bytes", "sha256",
               "result")
_ARCHIVE_HOSTS = ("archive.org", "archive.today", "archive.ph", "archive.is", "webcache.googleusercontent.com")
_CODE_RE = re.compile(r"^(S\d{1,2})_")
_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
# INEGI prints thousands with a space ("3 566.22"): amounts with two decimals
# whose thousands are space-separated are read as one number too (Batch 1).
_SPACED_AMOUNT_RE = re.compile(r"(?<![\d.])\d{1,3}(?:[  ]\d{3})+\.\d{2}(?!\d)")
_TEXT_LAYER_MIN_CHARS = 200

# Official URLs: spec §22 register (.docx hyperlinks) + the S24–S27 addendum.
DEFAULT_URLS = {
    "S1": "https://wwwnp.sat.gob.mx/minisitio/NormatividadRMFyRGCE/normatividad_rmf_rgce2026.html",
    "S2": "https://www.sat.gob.mx/minisitio/NormatividadRMFyRGCE/documentos2026/rmf/anexos/Anexo-8-RMF-2026_DOF-28122025.pdf",
    "S3": "https://www.dof.gob.mx/nota_detalle.php?codigo=5777649&fecha=31/12/2025",
    "S4": "https://wwwmat.sat.gob.mx/consultas/97722/comprobante-de-nomina",
    "S5": "https://wwwmat.sat.gob.mx/articulo/36534/articulo-96",
    "S6": "https://www.inegi.org.mx/contenidos/saladeprensa/boletines/2026/uma/uma2026.pdf",
    "S7": "https://www.inegi.org.mx/contenidos/saladeprensa/boletines/2025/uma/uma2025.pdf",
    "S8": "https://www.gob.mx/conasami/articulos/incremento-a-los-salarios-minimos-para-2026",
    "S9": "https://www.dof.gob.mx/nota_detalle.php?codigo=5775534&fecha=09/12/2025",
    "S10": "https://www.imss.gob.mx/sites/all/statics/pdf/leyes/LSS.pdf",
    "S11": "https://www.congreso.gob.mx/sedia/biblio/prog_leg/Prog_leg_LXIV/110_DOF_16dic20.pdf",
    "S12": "https://www.imss.gob.mx/node/101777",
    "S13": "https://www.imss.gob.mx/node/1407",
    "S14": "https://www.imss.gob.mx/tramites/imss02029",
    "S15": "https://portalmx.infonavit.org.mx/wps/portal/infonavitmx/mx2/derechohabientes/centro_ayuda/10_mi_ahorro/11_sobre_mi_ahorro/",
    "S16": "https://portalmx.infonavit.org.mx/wps/portal/infonavitmx/mx2/patrones/beneficios/",
    "S17": "https://www.gob.mx/stps/documentos/reduccion-de-la-jornada-laboral-a-40-horas-preguntas-frecuentes",
    "S18": "https://dof.gob.mx/nota_detalle_popup.php?codigo=5786537",
    "S19": "https://www.gob.mx/profedet/articulos/persona-trabajadora-las-vacaciones-son-tu-derecho",
    "S20": "https://www.gob.mx/profedet/articulos/preguntas-frecuentes-sobre-aguinaldo",
    "S21": "https://www.sat.gob.mx/minisitio/RepartodeUtilidades/index.html",
    "S22": "https://www.congresocdmx.gob.mx/archivo-45edcc764eb95c905412604e86eb20195b16f27e.pdf",
    "S23": "https://www.dof.gob.mx/nota_detalle.php?codigo=5752569&fecha=20/03/2025",
    "S24": "https://www.diputados.gob.mx/LeyesBiblio/pdf/LISR.pdf",
    "S25": "https://www.diputados.gob.mx/LeyesBiblio/regley/Reg_LISR_060516.pdf",
    "S26": "https://www.diputados.gob.mx/LeyesBiblio/pdf/LFT.pdf",
    "S27": "https://www.diputados.gob.mx/LeyesBiblio/pdf/LIFNVT.pdf",
}


# ── manifest ────────────────────────────────────────────────────────────────

def read_manifest(path: Path = None) -> list:
    path = Path(path or MANIFEST_PATH)
    if not path.is_file():
        return []
    with open(path, encoding="utf-8", newline="") as fh:
        return [{col: (row.get(col) or "") for col in COLUMNS} for row in csv.DictReader(fh)]


def write_manifest(rows: list, path: Path = None) -> None:
    path = Path(path or MANIFEST_PATH)
    rows = sorted(rows, key=lambda r: (int(r["code"][1:]) if r["code"][1:].isdigit() else 999, r["file"]))
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── text extraction ────────────────────────────────────────────────────────

def extract_text(path: Path) -> str:
    """Text of a saved source: pdftotext -layout (keeps table rows on one
    line), else pypdf; HTML is tag-stripped. '' when there is no text layer."""
    path = Path(path)
    data_head = path.read_bytes()[:5]
    if data_head.startswith(b"%PDF"):
        if shutil.which("pdftotext"):
            out = subprocess.run(["pdftotext", "-layout", "-enc", "UTF-8", str(path), "-"],
                                 capture_output=True, check=False)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout.decode("utf-8", errors="replace")
        try:
            from pypdf import PdfReader

            return "\n".join((page.extract_text() or "") for page in PdfReader(str(path)).pages)
        except Exception:
            return ""
    raw = path.read_bytes().decode("utf-8", errors="replace")
    if "<html" in raw[:2000].lower():
        raw = re.sub(r"(?is)<(script|style).*?</\1>", " ", raw)
        raw = re.sub(r"(?s)<[^>]+>", " ", raw)
    return raw


def numbers_in(text: str) -> list:
    out = []
    for token in _NUMBER_RE.findall(text):
        try:
            out.append(Decimal(token.replace(",", "")))
        except InvalidOperation:
            continue
    for token in _SPACED_AMOUNT_RE.findall(text):
        out.append(Decimal(re.sub(r"[  ]", "", token)))
    return out + word_numbers(text)


# Spanish number words (Batch 2): the LSS, LFT and Ley del INFONAVIT write most
# rates in words ("uno punto cero cinco por ciento", "sesenta y cinco centesimas
# de punto porcentual"). They are read as numbers so the machine extraction can
# find them.
_UNITS = {"cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
          "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
          "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
          "veintiuno": 21, "veintiun": 21, "veintidos": 22, "veintitres": 23, "veinticuatro": 24, "veinticinco": 25,
          "veintiseis": 26, "veintisiete": 27, "veintiocho": 28, "veintinueve": 29, "treinta": 30, "cuarenta": 40,
          "cincuenta": 50, "sesenta": 60, "setenta": 70, "ochenta": 80, "noventa": 90, "cien": 100, "ciento": 100,
          "doscientos": 200, "trescientos": 300, "cuatrocientos": 400, "quinientos": 500, "seiscientos": 600,
          "setecientos": 700, "ochocientos": 800, "novecientos": 900}


def _fold(word: str) -> str:
    import unicodedata

    return "".join(ch for ch in unicodedata.normalize("NFD", word.lower()) if unicodedata.category(ch) != "Mn")


def _group(tokens):
    """Consume one integer written in words: (value, tokens used)."""
    total, used = 0, 0
    while used < len(tokens):
        t = tokens[used]
        if t == "y" and used and used + 1 < len(tokens) and tokens[used + 1] in _UNITS:
            used += 1
            continue
        if t == "mil":
            total = (total or 1) * 1000
            used += 1
            continue
        if t not in _UNITS:
            break
        if _UNITS[t] >= 100 and total % 100:          # "un cien": an article, then a new number
            break
        total += _UNITS[t]
        used += 1
    return total, used


def word_numbers(text: str) -> list:
    """Numbers written in Spanish words: integers, 'X punto Y' decimals (each
    'cero' after 'punto' is a leading zero) and 'N centesimas' (N / 100)."""
    tokens = [_fold(t) for t in re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]+", text)]
    out, i = [], 0
    while i < len(tokens):
        if tokens[i] not in _UNITS or (tokens[i] in ("cien", "ciento") and i and tokens[i - 1] == "por"):
            i += 1                                   # "por ciento" is a percent sign, not 100
            continue
        value, used = _group(tokens[i:])
        j = i + used
        number = Decimal(value)
        if j < len(tokens) and tokens[j] == "punto" and j + 1 < len(tokens) and tokens[j + 1] in _UNITS:
            k, zeros = j + 1, 0
            while k < len(tokens) and tokens[k] == "cero":
                zeros, k = zeros + 1, k + 1
            frac, fused = _group(tokens[k:])
            if fused:
                number = Decimal(f"{value}.{'0' * zeros}{frac}")
                j = k + fused
            elif zeros:
                j = k
        if j < len(tokens) and tokens[j].startswith("centesima"):
            number = Decimal(value) / 100
        out.append(number)
        i = max(j, i + 1)
    return out


# ── subcommands ─────────────────────────────────────────────────────────────

def cmd_hash(sources_dir: Path = None, manifest_path: Path = None) -> list:
    """Add every new source file as an UNVERIFIED row. An existing row is never
    overwritten (Phase 11d): only its empty fields are filled. A saved file
    whose hash no longer matches its row is refused — nothing is written."""
    sources_dir = Path(sources_dir or SOURCES_DIR)
    rows = read_manifest(manifest_path)
    by_file = {r["file"]: r for r in rows}
    changed = [p.name for p in sources_dir.iterdir()
               if p.is_file() and p.name in by_file and by_file[p.name]["sha256"]
               and by_file[p.name]["sha256"] != sha256_of(p)]
    if changed:
        raise SystemExit(f"CHANGED {', '.join(sorted(changed))}: the saved file no longer matches its manifest row. "
                         "Nothing written — restore the recorded file, or save the new one under a new name")
    for path in sorted(p for p in sources_dir.iterdir() if p.is_file() and p.suffix != ".csv"):
        match = _CODE_RE.match(path.name)
        if match is None:
            print(f"SKIP {path.name}: filename does not start with an S-code")
            continue
        code, sha = match.group(1), sha256_of(path)
        row = by_file.get(path.name)
        if row is None:
            row = {col: "" for col in COLUMNS}
            row.update(code=code, file=path.name, url=DEFAULT_URLS.get(code, ""), status="UNVERIFIED")
            rows.append(row)
            by_file[path.name] = row
        text = extract_text(path) if not row["text_layer"] else ""
        found = {
            "sha256": sha, "bytes": str(path.stat().st_size),
            "retrieved_at": datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "content_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            "text_layer": "yes" if len(text.strip()) >= _TEXT_LAYER_MIN_CHARS else "no",
        }
        for key, value in found.items():
            if not row[key]:                                    # fill blanks only — never overwrite
                row[key] = value
        print(f"{code:4} {row['status']:14} text={row['text_layer']:3} {sha[:12]}  {path.name}")
    write_manifest(rows, manifest_path)
    return rows


def cmd_header(code: str, lines: int = 40, manifest_path: Path = None, sources_dir: Path = None) -> str:
    sources_dir = Path(sources_dir or SOURCES_DIR)
    rows = [r for r in read_manifest(manifest_path) if r["code"] == code]
    if not rows:
        raise SystemExit(f"{code} is not in the manifest — run `hash` first")
    shown = []
    for row in rows:
        text = extract_text(sources_dir / row["file"])
        head = [ln.strip() for ln in text.splitlines() if ln.strip()][:lines]
        shown.append(f"== {row['file']} ==\n" + "\n".join(head))
    out = "\n".join(shown)
    print(out)
    return out


def cmd_set(code: str, assignments: list, manifest_path: Path = None, file: str = None) -> dict:
    rows = read_manifest(manifest_path)
    targets = [r for r in rows if r["code"] == code and (file is None or r["file"] == file)]
    if len(targets) != 1:
        raise SystemExit(f"{code}: expected exactly one manifest row, found {len(targets)} (pass file=…)")
    row = targets[0]
    for item in assignments:
        key, _, value = item.partition("=")
        if key not in EDITABLE:
            raise SystemExit(f"{key!r} is not editable (one of {', '.join(EDITABLE)})")
        if key == "status" and value not in STATUSES:
            raise SystemExit(f"status must be one of {', '.join(STATUSES)}")
        if key == "status" and value == "VERIFIED":
            raise SystemExit("VERIFIED is set only by `verify` — a fresh direct download from the official URL "
                             "that hashes to the saved copy")
        if key == "url" and value != row["url"] and row["status"] == "VERIFIED":
            row["status"] = "UNVERIFIED"                    # it was verified against another URL
        row[key] = value
    write_manifest(rows, manifest_path)
    return row


def _is_archive_url(url: str) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in _ARCHIVE_HOSTS)


def _download(url: str) -> tuple:
    """(final URL after redirects, response body) of a direct GET."""
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Zoiko source verification)"})
    with urllib.request.urlopen(request, timeout=180) as response:      # noqa: S310 — the official http(s) URL
        return response.geturl(), response.read()


def _append_log(entry: dict, manifest_path: Path = None) -> None:
    path = Path(manifest_path or MANIFEST_PATH).parent / LOG_NAME
    new = not path.is_file()
    with open(path, "a", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=LOG_COLUMNS)
        if new:
            writer.writeheader()
        writer.writerow(entry)


def cmd_verify(code: str, downloader: str, file: str = None, manifest_path: Path = None, sources_dir: Path = None,
               fetch=None, now=None) -> dict:
    """Mark one saved source VERIFIED: download it afresh from its official
    URL and require the SHA-256 to equal the saved copy's. Never from an
    archive capture. Every attempt is logged; only a MATCH sets VERIFIED."""
    sources_dir = Path(sources_dir or SOURCES_DIR)
    downloader = (downloader or "").strip()
    if not downloader:
        raise SystemExit("downloader=NAME is required (who ran the download)")
    rows = read_manifest(manifest_path)
    targets = [r for r in rows if r["code"] == code and (file is None or r["file"] == file)]
    if len(targets) != 1:
        raise SystemExit(f"{code}: expected exactly one manifest row, found {len(targets)} (pass file=…)")
    row = targets[0]
    url = row["url"]
    if not url.lower().startswith(("https://", "http://")) or _is_archive_url(url):
        raise SystemExit(f"{code}: the manifest URL must be the official URL, not an archive capture ({url!r})")
    if not (row["title"] and row["issuer"] and row["header_version"]):
        raise SystemExit("VERIFIED needs title, issuer and header_version recorded")
    if row["text_layer"] != "yes":
        raise SystemExit("VERIFIED needs a text layer (text_layer=yes) — mark NO_TEXT_LAYER instead")
    saved = sources_dir / row["file"]
    if not saved.is_file() or sha256_of(saved) != row["sha256"]:
        raise SystemExit(f"{code} {row['file']}: the saved copy is missing or no longer matches the manifest — "
                         "run `hash` first")
    final_url, body = (fetch or _download)(url)
    if _is_archive_url(final_url):
        raise SystemExit(f"{code}: the download was redirected to an archive host ({final_url}) — not a direct "
                         "download")
    digest = hashlib.sha256(body).hexdigest()
    result = "MATCH" if digest == row["sha256"] else "MISMATCH"
    _append_log({"code": code, "file": row["file"], "url": url, "final_url": final_url,
                 "downloaded_at": (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "downloader": downloader, "response_bytes": str(len(body)), "sha256": digest, "result": result},
                manifest_path)
    if result != "MATCH":
        raise SystemExit(f"{code} {row['file']}: the direct download hashes to {digest[:12]}…, the saved copy to "
                         f"{row['sha256'][:12]}… — not VERIFIED (logged as MISMATCH)")
    row["status"] = "VERIFIED"
    write_manifest(rows, manifest_path)
    print(f"VERIFIED {code} {row['file']} ({len(body)} bytes, {digest[:12]}…) by {downloader}")
    return row


def cmd_check(manifest_path: Path = None, sources_dir: Path = None) -> list:
    sources_dir = Path(sources_dir or SOURCES_DIR)
    problems = []
    for row in read_manifest(manifest_path):
        path = sources_dir / row["file"]
        if not path.is_file():
            problems.append(f"{row['code']} {row['file']}: file missing")
        elif sha256_of(path) != row["sha256"]:
            problems.append(f"{row['code']} {row['file']}: SHA-256 differs from the manifest")
    for p in problems:
        print("FAIL", p)
    return problems


_QUOTE_RE = re.compile(r"'([^']{12,})'")


def _quotes(source_ref: str) -> list:
    """The verbatim wordings a citation quotes ('…', 12 characters or more)."""
    return [q.rstrip(" .,;") for q in _QUOTE_RE.findall(source_ref or "")]


def _content_checks():
    """(source code, description, numbers that must be found, same-line?) for
    every transcribed content row."""
    from app.modules.payroll.engine.countries import mexico_content as c

    checks = []
    annual = tuple(b for rows in getattr(c, "MX_ISR_ANNUAL_TARIFFS", {}).values() for b in rows)   # W1-4
    for b in c.MX_ISR_TARIFFS + annual:
        nums = [b.lower, b.fixed_quota, b.rate_pct] + ([b.upper] if b.upper is not None else [])
        checks.append((b.source, f"ISR {b.period} {b.lower}", nums, True))
    derived = getattr(c, "MX_DERIVED_VALUES", {})
    for r in c.MX_SCALAR_CONTENT + tuple(r for rows in c.MX_ISN_CONTENT.values() for r in rows):
        # W1-1: a text rule has no number to find, so every wording its citation
        # quotes must be in the cited file (numeric rows' quotes are checked too).
        for quote in _quotes(r.source_ref):
            checks.append((r.source, f"{r.key} quote '{quote[:40]}'", ("NAME", quote), False))
        if r.key in derived:                     # printed nowhere: look for its printed components
            d = derived[r.key]
            parts = [d[k] for k in ("base", "step", "quota", "share", "premium") if k in d]
            checks.append((r.source, f"{r.key} (DERIVED from {', '.join(parts)})", parts, False))
            continue
        nums = [v for v in (r.employee_pct, r.employer_pct, r.flat_amount) if v is not None]
        if nums:
            checks.append((r.source, f"{r.key} {r.effective_from}", nums, False))
    for w in c.MX_MIN_WAGES:
        checks.append((w.source, f"min wage {w.code} {w.zone or ''}".strip(), [w.daily_amount], False))
    cross = getattr(c, "MX_CEAV_TEXT_CROSSCHECK", None)
    for b in c.MX_CEAV_SCHEDULE:
        nums = [b.lower_multiple, b.employer_pct] + ([b.upper_multiple] if b.upper_multiple is not None else [])
        if cross is not None and b.year == cross[1]:
            # S11's table is a scanned image; its final-year column is the S10 Art. 168 text table
            checks.append((cross[0], f"CEAV {b.year} {b.lower_multiple}{b.lower_unit} (vs {cross[2]})", nums, False))
        elif cross is not None:
            checks.append((None, f"CEAV {b.year} {b.lower_multiple}{b.lower_unit}", "IMAGE", False))
        else:
            checks.append((b.source, f"CEAV {b.year} {b.lower_multiple}{b.lower_unit}", nums, False))
    for w in c.MX_WORKWEEK:
        checks.append((w.source, f"workweek {w.effective_from}", [w.ordinary_weekly_max_hours], False))
    vac_rule = getattr(c, "MX_VACATION_RULE_NUMBERS", None)
    for v in c.MX_VACATION_DAYS:
        if vac_rule:                              # DERIVED from Art. 76 wording: look for the rule's numbers
            checks.append((v.source, f"vacation years {v.service_year_from}-{v.service_year_to} (DERIVED)",
                           list(vac_rule), False))
        else:
            checks.append((v.source, f"vacation year {v.service_year_from}", [v.days], False))
    for m in c.MX_ZLFN_MUNICIPALITIES:
        checks.append((m.source, f"ZLFN {m.state} {m.municipality}", ("NAME", m.municipality), False))
    # W1-2: module-direct rules (ISN inclusion, special pay, termination, PTU,
    # annual adjustment, calendar...) carry no table row — each citation must
    # quote the wording it rests on, and every quote must be in its file.
    for label, source, ref in _rule_citations(c):
        quotes = _quotes(ref)
        if not quotes:
            checks.append((source, f"{label}: quotes no wording", ("NAME", "\x00no quoted wording\x00"), False))
        for quote in quotes:
            checks.append((source, f"{label} quote '{quote[:40]}'", ("NAME", quote), False))
    return checks


def _rule_citations(c) -> list:
    """(label, source, source_ref) for every module-direct rule in mexico_content.
    A rule object may cite several files through `citations` ((source, ref), …)."""
    def cites(label, obj):
        pairs = getattr(obj, "citations", None) or ((obj.source, obj.source_ref),)
        return [(label, src, ref) for src, ref in pairs]

    out = []
    for (state, concept), (_inc, src, ref) in sorted(getattr(c, "MX_SPECIAL_PAY_ISN_INCLUSION", {}).items()):
        out.append((f"ISN {state} {concept}", src, ref))
    for name in ("MX_SPECIAL_PAY_RULES", "MX_TERMINATION_REASONS", "MX_PTU_EXCLUSION_REASONS",
                 "MX_ANNUAL_ADJUSTMENT_EXCLUSION_REASONS"):
        for key, obj in sorted(getattr(c, name, {}).items()):
            out += cites(f"{name} {key}", obj)
    for name in ("MX_AGUINALDO_RULE", "MX_FINIQUITO_RULE", "MX_PTU_RULE", "MX_ANNUAL_ADJUSTMENT_RULE",
                 "MX_RISK_PREMIUM_PERIOD", "MX_IMSS_MOVEMENT_DEADLINE"):
        obj = getattr(c, name, None)
        if obj is not None:
            out += cites(name, obj)
    for rule in getattr(c, "MX_FILING_CALENDAR", ()):
        out += cites(f"filing {rule.report_type} {rule.state or ''}".strip(), rule)
    for year, (_dates, src, ref) in sorted(getattr(c, "MX_OFFICIAL_HOLIDAYS", {}).items()):
        out.append((f"holidays {year}", src, ref))
    return out


def cmd_compare(manifest_path: Path = None, sources_dir: Path = None) -> list:
    from app.modules.payroll import mexico_sources

    sources_dir = Path(sources_dir or SOURCES_DIR)
    # A cite is CODE or CODE/file; a Draft pack may rest on an archive copy
    # (Phase 11d), so the check runs on every file usable for a Draft pack.
    rows = read_manifest(manifest_path)
    verified = mexico_sources.usable(rows, mexico_sources.DRAFT_STATUSES,
                                     mexico_sources.read_log(manifest_path or MANIFEST_PATH))
    texts, misses, checked, images, raw = {}, [], 0, 0, {}
    for source, what, nums, same_line in _content_checks():
        checked += 1
        if nums == "IMAGE":                     # no text layer: the blind transcription and tests check it
            images += 1
            continue
        if source not in verified:
            misses.append(f"{what}: cites {source}, which has no usable (VERIFIED or archive-copy) file")
            continue
        if source not in texts:
            text = extract_text(sources_dir / verified[source]["file"])
            texts[source] = (set(numbers_in(text)), [set(numbers_in(ln)) for ln in text.splitlines()])
        if isinstance(nums, tuple) and nums[0] == "NAME":
            if source not in raw:
                import html as _html

                raw[source] = re.sub(r"\s+", " ", _fold(_html.unescape(extract_text(sources_dir / verified[source]["file"]))))
            if re.sub(r"\s+", " ", _fold(nums[1])) not in raw[source]:
                misses.append(f"{what}: name not found in {source}")
            continue
        everywhere, lines = texts[source]
        wanted = {Decimal(str(n)) for n in nums}
        found = any(wanted <= ln for ln in lines) if same_line else wanted <= everywhere
        if not found:
            misses.append(f"{what}: {sorted(map(str, wanted))} not found {'on one line ' if same_line else ''}in {source}")
    for m in misses:
        print("MISS", m)
    print(f"compare: {checked} content rows checked, {len(misses)} miss(es)"
          + (f", {images} in an image table (no text layer; checked by the blind transcription and tests)"
             if images else ""))
    return misses


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        print(__doc__)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "hash":
        cmd_hash()
        return 0
    if cmd == "header" and rest:
        cmd_header(rest[0], int(rest[1]) if len(rest) > 1 else 40)
        return 0
    if cmd == "set" and len(rest) >= 2:
        file = next((a.partition("=")[2] for a in rest[1:] if a.startswith("file=")), None)
        cmd_set(rest[0], [a for a in rest[1:] if not a.startswith("file=")], file=file)
        return 0
    if cmd == "verify" and len(rest) >= 2:
        opts = dict(a.partition("=")[::2] for a in rest[1:])
        cmd_verify(rest[0], opts.get("downloader", ""), file=opts.get("file"))
        return 0
    if cmd == "check":
        return 1 if cmd_check() else 0
    if cmd == "compare":
        return 1 if cmd_compare() else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
