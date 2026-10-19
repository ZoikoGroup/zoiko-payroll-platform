"""
modules/payroll/mexico_cfdi_builder.py
--------------------------------------
The two seams of CFDI generation that Phase 7 cannot fill yet
(MEXICO_PHASE_7_PLAN.md §1 X1, X2, X4):

- CfdiPayloadBuilder — CFDI 4.0 + Complemento de Nómina 1.2 XML from the
  committed mx_result, validated against the pinned XSD release. Needs S28
  (Nómina 1.2 catalog workbook + nomina12.xsd), S30 (CFDI 4.0 catalogs /
  Anexo 20 incl. cfdv40.xsd) and S4 — none saved. The production builder
  REFUSES (MX_CFDI_BUILDER_BLOCKED).
- CfdiSigner — cadena original + sello with the employer's CSD, whose key lives
  only in GCP Secret Manager behind a gcp-sm:// ref (MX-035). The production
  signer REFUSES (MX_CSD_SIGNING_BLOCKED) before any secret call.

Tests inject synthetic implementations (labelled, non-SAT bytes) to prove the
lifecycle; production can never create a document in Phase 7.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, Tuple

from app.modules.payroll.engine.countries.mexico import MXBlock


class CfdiPayloadBuilder(ABC):
    @abstractmethod
    def build(self, document_input: dict) -> bytes: ...

    def blocked(self) -> Optional[MXBlock]:
        """Why this builder cannot run at all (None = it can); a read-only
        probe for the Super Admin overview — never builds anything."""
        return None


class CfdiSigner(ABC):
    @abstractmethod
    def sign(self, payload: bytes, credential) -> Tuple[bytes, Optional[str]]: ...

    def blocked(self) -> Optional[MXBlock]:
        return None


class SatBuilder(CfdiPayloadBuilder):
    def blocked(self):
        return MXBlock("MX_CFDI_BUILDER_BLOCKED",
                       "the CFDI 4.0 + Nómina 1.2 builder needs S28 (catalog workbook + nomina12.xsd), S30 (CFDI 4.0 "
                       "catalogs / Anexo 20, cfdv40.xsd) and S4 — not saved yet (Phase 7 D11)")

    def build(self, document_input: dict) -> bytes:
        raise self.blocked()


class GcpSmSigner(CfdiSigner):
    def blocked(self):
        return MXBlock("MX_CSD_SIGNING_BLOCKED",
                       "CSD signing needs GCP Secret Manager with the employer's CSD key behind a gcp-sm:// reference "
                       "— not configured yet (Phase 7 D12)")

    def sign(self, payload: bytes, credential):
        raise self.blocked()


_BUILDER: CfdiPayloadBuilder = SatBuilder()
_SIGNER: CfdiSigner = GcpSmSigner()


def active_builder() -> CfdiPayloadBuilder:
    return _BUILDER


def active_signer() -> CfdiSigner:
    return _SIGNER
