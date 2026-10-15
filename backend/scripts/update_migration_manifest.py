"""Regenerate alembic/MIGRATIONS_MANIFEST.txt: one line per migration file —
file|revision|down_revision|sha256 of the LF-normalised content.

tests/test_alembic_migration_manifest.py fails when a listed migration is deleted,
renamed or edited, or when a new migration is not listed. Run this only when a new
migration is added on purpose (an applied migration must never change):

    cd backend && python -m scripts.update_migration_manifest
"""
import hashlib
import pathlib
import re

BACKEND = pathlib.Path(__file__).resolve().parent.parent
VERSIONS = BACKEND / "alembic" / "versions"
MANIFEST = BACKEND / "alembic" / "MIGRATIONS_MANIFEST.txt"
_REV = re.compile(r"^revision[^=\n]*=\s*['\"]([0-9a-f]+)['\"]", re.M)
_DOWN = re.compile(r"^down_revision[^=\n]*=\s*(.+)$", re.M)


def entries() -> list:
    rows = []
    for path in sorted(VERSIONS.glob("*.py")):
        text = path.read_bytes().replace(b"\r\n", b"\n")
        src = text.decode("utf-8")
        rev = _REV.search(src)
        down = _DOWN.search(src)
        down_ids = ",".join(sorted(re.findall(r"['\"]([0-9a-f]+)['\"]", down.group(1)))) if down else ""
        rows.append(f"{path.name}|{rev.group(1) if rev else ''}|{down_ids}|{hashlib.sha256(text).hexdigest()}")
    return rows


def main() -> None:
    MANIFEST.write_text("\n".join(entries()) + "\n", encoding="utf-8", newline="\n")
    print(f"{MANIFEST.relative_to(BACKEND)}: {len(entries())} migrations")


if __name__ == "__main__":
    main()
