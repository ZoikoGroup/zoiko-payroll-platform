"""
modules/payroll/mexico_cfdi_builder.py
--------------------------------------
The two seams of CFDI generation (MEXICO_PHASE_7_PLAN.md §1 X1, X2, X4):

- CfdiPayloadBuilder — CFDI 4.0 + Complemento de Nómina 1.2 XML from the
  committed mx_result, validated against the pinned XSD release. Phase 11b:
  SatBuilder assembles the input (mexico_cfdi_input) and builds / validates it
  (mexico_cfdi_xml) from a pinned SAT set (S28, S30, S4 — Phase 11a). It
  refuses (MX_CFDI_BUILDER_BLOCKED) only when no verified pinned set is
  installed.
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

    def prepare(self, db, run, item, release, base: dict) -> dict:
        """The full document input for one payslip (default: `base` as is)."""
        return base

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
        from app.modules.payroll import mexico_cfdi_schema

        if any(not mexico_cfdi_schema.problems(s) for s in mexico_cfdi_schema.available_sets()):
            return None
        return MXBlock("MX_CFDI_BUILDER_BLOCKED",
                       "the CFDI 4.0 + Nómina 1.2 builder needs a verified pinned SAT set (S28, S30 — Phase 11a); "
                       "none is installed")

    def prepare(self, db, run, item, release, base: dict) -> dict:
        from app.modules.payroll import mexico_cfdi_input

        return mexico_cfdi_input.document_input(db, run, item, release, base)

    def build(self, document_input: dict) -> bytes:
        from app.modules.payroll import mexico_cfdi_xml

        blocked = self.blocked()
        if blocked is not None:
            raise blocked
        return mexico_cfdi_xml.build(document_input)


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
