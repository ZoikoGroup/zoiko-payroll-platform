"""TEST-ONLY local-filesystem StampedXmlStore (Mexico final mile X5, C15).
Never imported by app/ and never installed in mexico_xml_store._STORE: tests
use it under pytest's tmp_path. Metadata (hash, size, retention) is kept in a
sidecar JSON next to each XML file."""

import json
from datetime import date
from pathlib import Path

from app.modules.payroll import mexico_xml_store as X


class LocalXmlStore(X.StampedXmlStore):
    def __init__(self, root):
        self.root = Path(root)

    def _paths(self, key):
        path = self.root / X.check_key(key)
        return path, path.with_suffix(".xml.meta.json")

    def head(self, ref):
        _, meta = self._paths(ref)
        if not meta.exists():
            return None
        m = json.loads(meta.read_text(encoding="utf-8"))
        return X.StoredXml(ref=ref, key=ref, sha256=m["sha256"], size=m["size"],
                           retention_until=date.fromisoformat(m["retention_until"]) if m["retention_until"] else None)

    def put(self, key, data, retention_until):
        same = self.write_once(self.head(key), data)
        if same is not None:
            return same
        path, meta = self._paths(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        stored = X.StoredXml(ref=key, key=key, sha256=X.sha256(data), size=len(data), retention_until=retention_until)
        meta.write_text(json.dumps({"sha256": stored.sha256, "size": stored.size,
                                    "retention_until": retention_until.isoformat() if retention_until else None}),
                        encoding="utf-8")
        return stored

    def get(self, ref):
        meta = self.head(ref)
        if meta is None:
            raise FileNotFoundError(ref)
        return self.verified(meta, self._paths(ref)[0].read_bytes())

    def delete(self, ref, on):
        meta = self.head(ref)
        if meta is None:
            return
        self.deletable(meta, on)
        for p in self._paths(ref):
            p.unlink(missing_ok=True)
