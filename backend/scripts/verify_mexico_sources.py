"""
scripts/verify_mexico_sources.py
--------------------------------
Mexico Phase 1 evidence tooling (ZP-MX-ENG-001). Read-only against the
database — it never touches it; it reads/writes only
docs/mexico/sources/SOURCES_MANIFEST.csv.

Subcommands:
  hash                 hash every file in docs/mexico/sources/ into the
                       manifest (sha256, bytes, content type, text layer);
                       a new or changed file is reset to UNVERIFIED
  header CODE [N]      print the first N text lines of a source (default 40),
                       to read its title / issuer / reform date
  set CODE k=v …       record title / issuer / url / header_version /
                       status / note for one source
  check                every manifest row's file exists and still hashes to
                       the recorded SHA-256 (exit 1 otherwise)
  compare              the independent machine check (Phase 1 plan §3):
                       every transcribed number in mexico_content.py must be
                       found in the text of the VERIFIED file its row cites —
                       an ISR bracket's four numbers on ONE line of S2
                       (exit 1 on any miss; empty content checks 0 rows)

Statuses: UNVERIFIED (hashed, not yet checked), VERIFIED (right document and
version, usable for transcription), WRONG_VERSION, INCOMPLETE, NO_TEXT_LAYER.
Only VERIFIED files can back a seeded row (seed_mexico_canonical_packs.py).

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
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCES_DIR = REPO_ROOT / "docs" / "mexico" / "sources"
MANIFEST_PATH = SOURCES_DIR / "SOURCES_MANIFEST.csv"
COLUMNS = ("code", "title", "issuer", "url", "file", "sha256", "bytes", "retrieved_at", "content_type",
           "header_version", "text_layer", "status", "note")
STATUSES = ("UNVERIFIED", "VERIFIED", "WRONG_VERSION", "INCOMPLETE", "NO_TEXT_LAYER")
EDITABLE = ("title", "issuer", "url", "header_version", "status", "note")
_CODE_RE = re.compile(r"^(S\d{1,2})_")
_NUMBER_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
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
    return out


# ── subcommands ─────────────────────────────────────────────────────────────

def cmd_hash(sources_dir: Path = None, manifest_path: Path = None) -> list:
    sources_dir = Path(sources_dir or SOURCES_DIR)
    rows = read_manifest(manifest_path)
    by_file = {r["file"]: r for r in rows}
    for path in sorted(p for p in sources_dir.iterdir() if p.is_file() and p.name != "SOURCES_MANIFEST.csv"):
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
        elif row["sha256"] and row["sha256"] != sha:
            print(f"CHANGED {path.name}: hash differs from the manifest — reset to UNVERIFIED")
            row.update(status="UNVERIFIED", header_version="", note="file changed since last verification")
        text = extract_text(path)
        row.update(
            sha256=sha, bytes=str(path.stat().st_size),
            retrieved_at=row["retrieved_at"] or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
            content_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            text_layer="yes" if len(text.strip()) >= _TEXT_LAYER_MIN_CHARS else "no",
        )
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
        row[key] = value
    if row["status"] == "VERIFIED" and not (row["title"] and row["issuer"] and row["header_version"]):
        raise SystemExit("VERIFIED needs title, issuer and header_version recorded")
    if row["status"] == "VERIFIED" and row["text_layer"] != "yes":
        raise SystemExit("VERIFIED needs a text layer (text_layer=yes) — mark NO_TEXT_LAYER instead")
    write_manifest(rows, manifest_path)
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


def _content_checks():
    """(source code, description, numbers that must be found, same-line?) for
    every transcribed content row."""
    from app.modules.payroll.engine.countries import mexico_content as c

    checks = []
    for b in c.MX_ISR_TARIFFS:
        nums = [b.lower, b.fixed_quota, b.rate_pct] + ([b.upper] if b.upper is not None else [])
        checks.append((b.source, f"ISR {b.period} {b.lower}", nums, True))
    for r in c.MX_SCALAR_CONTENT + tuple(r for rows in c.MX_ISN_CONTENT.values() for r in rows):
        nums = [v for v in (r.employee_pct, r.employer_pct, r.flat_amount) if v is not None]
        if nums:
            checks.append((r.source, f"{r.key} {r.effective_from}", nums, False))
    for w in c.MX_MIN_WAGES:
        checks.append((w.source, f"min wage {w.code}", [w.daily_amount], False))
    for b in c.MX_CEAV_SCHEDULE:
        nums = [b.lower_multiple, b.employer_pct] + ([b.upper_multiple] if b.upper_multiple is not None else [])
        checks.append((b.source, f"CEAV {b.year} {b.lower_multiple}{b.lower_unit}", nums, False))
    for w in c.MX_WORKWEEK:
        checks.append((w.source, f"workweek {w.effective_from}", [w.ordinary_weekly_max_hours], False))
    for v in c.MX_VACATION_DAYS:
        checks.append((v.source, f"vacation year {v.service_year_from}", [v.days], False))
    return checks


def cmd_compare(manifest_path: Path = None, sources_dir: Path = None) -> list:
    sources_dir = Path(sources_dir or SOURCES_DIR)
    verified = {r["code"]: r for r in read_manifest(manifest_path) if r["status"] == "VERIFIED"}
    texts, misses, checked = {}, [], 0
    for source, what, nums, same_line in _content_checks():
        checked += 1
        if source not in verified:
            misses.append(f"{what}: cites {source}, which has no VERIFIED file")
            continue
        if source not in texts:
            text = extract_text(sources_dir / verified[source]["file"])
            texts[source] = (set(numbers_in(text)), [set(numbers_in(ln)) for ln in text.splitlines()])
        everywhere, lines = texts[source]
        wanted = {Decimal(str(n)) for n in nums}
        found = any(wanted <= ln for ln in lines) if same_line else wanted <= everywhere
        if not found:
            misses.append(f"{what}: {sorted(map(str, wanted))} not found {'on one line ' if same_line else ''}in {source}")
    for m in misses:
        print("MISS", m)
    print(f"compare: {checked} content rows checked, {len(misses)} miss(es)")
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
    if cmd == "check":
        return 1 if cmd_check() else 0
    if cmd == "compare":
        return 1 if cmd_compare() else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
