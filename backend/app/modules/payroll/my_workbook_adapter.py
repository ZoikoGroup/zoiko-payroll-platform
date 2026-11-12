"""
modules/payroll/my_workbook_adapter.py
--------------------------------------
Malaysia adapter for statutory_workbook (ZP-MY-ENG-001). Sheets:

  Parameters        every scalar row (national + one per labour territory)
  MY_EPF_SCHEDULE / MY_SOCSO_SCHEDULE / MY_EIS_SCHEDULE / MY_FW_SOCSO_SCHEDULE
                    one row per member class and wage band with the employee
                    and employer amounts (MY-005: table rows, never percentages)
  Holidays          date, name, state code (blank = national)
  Earning classes   obligation x component treatment

Every value is validated and written through my_super_admin (the same rules
as the console). Writes are UNSIGNED; a second Super Admin signs afterwards.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestException
from app.modules.payroll import my_super_admin as msa
from app.modules.payroll import statutory_workbook as wbk

PARAMETERS = "Parameters"
HOLIDAYS = "Holidays"
EARNING = "Earning classes"
P_HEADERS = ["key", "territory", "description", "kind", "allowed_values", "current_value", "status", "value",
             "employee_rate_pct", "employer_rate_pct", "source_document_id", "page", "note"]
S_HEADERS = ["member_class", "wage_from", "wage_to", "employee_amount", "employer_amount", "source_document_id",
             "page"]
H_HEADERS = ["date", "name", "holiday_state", "source_document_id", "page"]
E_HEADERS = ["obligation", "component", "current_treatment", "status", "treatment", "source_document_id", "page"]


def _status(label: str, has_value: bool) -> str:
    if not has_value:
        return "MISSING"
    return "EXTRACTED" if msa.MARK in (label or "") else "VERIFIED"


def _dec(value, name: str):
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        raise ValueError(f"{name} must be a number")


def _date(value):
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip()[:10])


class MalaysiaWorkbookAdapter:
    country = "MY"

    # ── shape ────────────────────────────────────────────────────────────
    def fingerprint(self, pack) -> str:
        return wbk.pack_fingerprint(self.country, pack)

    def _rates(self, db: Session, pack):
        from app.modules.payroll.models import ContributionRate

        return (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                                  ContributionRate.organization_id.is_(None))
                .order_by(ContributionRate.sort_order, ContributionRate.id).all())

    def _slabs(self, db: Session, pack, rule_type: str):
        from app.modules.payroll.models import TaxSlab

        return (db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.rule_type == rule_type,
                                         TaxSlab.organization_id.is_(None))
                .order_by(TaxSlab.sort_order, TaxSlab.id).all())

    def _schedule_rows(self, db: Session, pack, rule_type: str) -> list:
        """Current schedule as (class, from, to, employee, employer) tuples."""
        pairs = {}
        for s in self._slabs(db, pack, rule_type):
            key = (s.filing_status, s.min_amount, s.max_amount)
            pairs.setdefault(key, {})[s.tax_regime] = s.flat_amount
        return sorted(((cls, lo, hi, v.get("EMPLOYEE"), v.get("EMPLOYER")) for (cls, lo, hi), v in pairs.items()),
                      key=lambda r: (r[0], r[1]))

    def _holiday_rows(self, db: Session, pack) -> list:
        out = []
        for s in self._slabs(db, pack, msa._content().MY_PUBLIC_HOLIDAY_RULE):
            day = (s.tax_formula or "").split(" ", 1)[0]
            out.append((day, " ".join((s.rate_label or "").replace(msa.MARK, " ").split()), s.jurisdiction_state))
        return sorted(out)

    def sheets(self, db: Session, pack) -> list:
        content = msa._content()
        vocab_hint = {k: ", ".join(content.ROUNDING_RULES) for k in content.MALAYSIA_PARAMETER_KEYS
                      if k.startswith("my_rounding_")}
        vocab_hint.update({"my_supported_pay_frequencies": ", ".join(content.PAY_FREQUENCIES_SUPPORTED),
                           "my_supported_contract_types": ", ".join(content.CONTRACT_TYPES_SUPPORTED),
                           "my_ea_due": "END_FEBRUARY", "my_form_e_due": "END_MARCH"})
        params = []
        for r in self._rates(db, pack):
            kind = content.ALL_PARAMETER_KINDS.get(r.component_key, "")
            current = (r.text_value if kind == "text" else
                       r.flat_amount if kind == "amount" else
                       " / ".join(str(v) for v in (r.employee_rate_pct, r.employer_rate_pct) if v is not None))
            has = any(v is not None for v in (r.flat_amount, r.employee_rate_pct, r.employer_rate_pct)) or \
                bool(r.text_value and r.text_value != content.PENDING)
            hint = vocab_hint.get(r.component_key, "NOT_SUPPORTED only (no vocabulary yet)" if kind == "text" else "")
            params.append([r.component_key, r.jurisdiction_state or "NATIONAL",
                           " ".join((r.label or "").replace(msa.MARK, " ").split()), kind, hint,
                           None if current in ("", None) else str(current), _status(r.label, has),
                           None, None, None, None, None, None])
        specs = [wbk.SheetSpec(PARAMETERS, P_HEADERS, params,
                               editable=["value", "employee_rate_pct", "employer_rate_pct", "source_document_id",
                                         "page", "note"],
                               note="value = amount or text; percentages go in employee_rate_pct / employer_rate_pct.")]
        for rule in content.SCHEDULE_RULES:
            rows = [[cls, lo, hi, ee, er, None, None] for cls, lo, hi, ee, er in self._schedule_rows(db, pack, rule)]
            specs.append(wbk.SheetSpec(rule, S_HEADERS, rows, editable=S_HEADERS,
                                       note=f"Classes: {', '.join(content.SCHEDULE_CLASSES[rule])}. wage_from "
                                            "exclusive, wage_to inclusive, first band from 0, last may be blank."))
        specs.append(wbk.SheetSpec(HOLIDAYS, H_HEADERS, [[d, n, s, None, None] for d, n, s in self._holiday_rows(db, pack)],
                                   editable=H_HEADERS,
                                   note=f"holiday_state blank = national; else one of {', '.join(content.HOLIDAY_STATES)}."))
        earning = []
        for s in self._slabs(db, pack, content.MY_EARNING_CLASS_RULE):
            earning.append([s.tax_regime, s.filing_status, s.assessment_basis,
                            "EXTRACTED" if msa.MARK in (s.rate_label or "") else "VERIFIED", None, None, None])
        specs.append(wbk.SheetSpec(EARNING, E_HEADERS, earning, editable=["treatment", "source_document_id", "page"],
                                   note="treatment: INCLUDED, EXCLUDED or REVIEW."))
        return specs

    # ── plan ─────────────────────────────────────────────────────────────
    def _source_ok(self, db: Session, value) -> str:
        try:
            msa._source(db, value, verify=False)
        except BadRequestException as exc:
            return str(getattr(exc, "detail", exc))
        return ""

    def plan(self, db: Session, pack, rows_by_sheet: dict) -> list:
        results = []
        results += self._plan_parameters(db, pack, rows_by_sheet.get(PARAMETERS, []))
        for rule in msa._content().SCHEDULE_RULES:
            results.append(self._plan_schedule(db, pack, rule, rows_by_sheet.get(rule, [])))
        results.append(self._plan_holidays(db, pack, rows_by_sheet.get(HOLIDAYS, [])))
        results += self._plan_earning(db, pack, rows_by_sheet.get(EARNING, []))
        return results

    def _plan_parameters(self, db: Session, pack, rows: list) -> list:
        content = msa._content()
        current = {r.component_key: r for r in self._rates(db, pack)}
        seen, results = set(), []
        for row in rows:
            key = str(row.get("key") or "").strip()
            if key not in current:
                results.append(wbk.RowResult(PARAMETERS, key or "(blank)", "INVALID", "unknown parameter key"))
                continue
            if key in seen:
                results.append(wbk.RowResult(PARAMETERS, key, "INVALID", "the key appears twice"))
                continue
            seen.add(key)
            rate, kind = current[key], content.ALL_PARAMETER_KINDS[key]
            try:
                if kind == "text":
                    raw = row.get("value")
                    new = {"text_value": str(raw).strip().upper() if raw not in (None, "") else None}
                elif kind == "amount":
                    new = {"flat_amount": _dec(row.get("value"), "value")}
                else:
                    new = {"employee_rate_pct": _dec(row.get("employee_rate_pct"), "employee_rate_pct"),
                           "employer_rate_pct": _dec(row.get("employer_rate_pct"), "employer_rate_pct")}
                    new = {k: v for k, v in new.items() if k in msa._KIND_SLOTS[kind]}
            except ValueError as exc:
                results.append(wbk.RowResult(PARAMETERS, key, "INVALID", str(exc)))
                continue
            if all(v is None for v in new.values()):
                has = any(getattr(rate, c) is not None for c in ("flat_amount", "employee_rate_pct",
                                                                 "employer_rate_pct")) or \
                    bool(rate.text_value and rate.text_value != content.PENDING)
                results.append(wbk.RowResult(PARAMETERS, key, "UNCHANGED" if has else "MISSING",
                                             "" if has else "no value in the workbook - stays blocked"))
                continue
            try:
                for column, value in new.items():
                    msa.check_rate_value(key, column, value)
            except BadRequestException as exc:
                results.append(wbk.RowResult(PARAMETERS, key, "INVALID", str(getattr(exc, "detail", exc))))
                continue
            if all(getattr(rate, c) == v for c, v in new.items() if v is not None):
                results.append(wbk.RowResult(PARAMETERS, key, "UNCHANGED"))
                continue
            problem = self._source_ok(db, row.get("source_document_id"))
            if problem:
                results.append(wbk.RowResult(PARAMETERS, key, "INVALID", problem))
                continue
            results.append(wbk.RowResult(PARAMETERS, key, "CHANGED", ", ".join(f"{c}={v}" for c, v in new.items()
                                                                                 if v is not None),
                                         change={"kind": "rate", "id": rate.id, "values": new,
                                                 "source": int(row["source_document_id"]),
                                                 "page": row.get("page")}))
        return results

    def _plan_schedule(self, db: Session, pack, rule: str, rows: list):
        if not rows:
            has = bool(self._schedule_rows(db, pack, rule))
            return wbk.RowResult(rule, rule, "UNCHANGED" if has else "MISSING",
                                 "" if has else "no schedule rows - the obligation stays blocked")
        try:
            parsed = [{"member_class": str(r.get("member_class") or "").strip().upper(),
                       "wage_from": _dec(r.get("wage_from"), "wage_from"), "wage_to": _dec(r.get("wage_to"), "wage_to"),
                       "employee_amount": _dec(r.get("employee_amount"), "employee_amount"),
                       "employer_amount": _dec(r.get("employer_amount"), "employer_amount"),
                       "source_document_id": r.get("source_document_id"), "page": r.get("page")} for r in rows]
        except ValueError as exc:
            return wbk.RowResult(rule, rule, "INVALID", str(exc))
        problems = msa.validate_schedule(rule, parsed)
        for n, r in enumerate(parsed, start=1):
            problem = self._source_ok(db, r["source_document_id"])
            if problem:
                problems.append(f"row {n}: {problem}")
        if problems:
            return wbk.RowResult(rule, rule, "INVALID", "; ".join(problems[:5]))
        current = self._schedule_rows(db, pack, rule)
        incoming = sorted((r["member_class"], r["wage_from"], r["wage_to"], r["employee_amount"], r["employer_amount"])
                          for r in parsed)
        if incoming == sorted(current):
            return wbk.RowResult(rule, rule, "UNCHANGED")
        return wbk.RowResult(rule, rule, "CHANGED", f"{len(parsed)} band(s)",
                             change={"kind": "table", "rule": rule, "rows": parsed})

    def _plan_holidays(self, db: Session, pack, rows: list):
        if not rows:
            has = bool(self._holiday_rows(db, pack))
            return wbk.RowResult(HOLIDAYS, HOLIDAYS, "UNCHANGED" if has else "MISSING",
                                 "" if has else "no public holidays - labour calculations stay blocked")
        parsed, problems = [], []
        for n, r in enumerate(rows, start=1):
            try:
                day = _date(r.get("date"))
            except (TypeError, ValueError):
                problems.append(f"row {n}: date must be an ISO date")
                continue
            state = str(r.get("holiday_state") or "").strip().upper() or None
            parsed.append({"date": day, "name": str(r.get("name") or "").strip(), "holiday_state": state,
                           "source_document_id": r.get("source_document_id"), "page": r.get("page")})
        problems += msa.validate_holidays(parsed, pack)
        for n, r in enumerate(parsed, start=1):
            problem = self._source_ok(db, r["source_document_id"])
            if problem:
                problems.append(f"row {n}: {problem}")
        if problems:
            return wbk.RowResult(HOLIDAYS, HOLIDAYS, "INVALID", "; ".join(problems[:5]))
        incoming = sorted((r["date"].isoformat(), r["name"], r["holiday_state"]) for r in parsed)
        if incoming == self._holiday_rows(db, pack):
            return wbk.RowResult(HOLIDAYS, HOLIDAYS, "UNCHANGED")
        return wbk.RowResult(HOLIDAYS, HOLIDAYS, "CHANGED", f"{len(parsed)} holiday(s)",
                             change={"kind": "table", "rule": msa._content().MY_PUBLIC_HOLIDAY_RULE, "rows": parsed})

    def _plan_earning(self, db: Session, pack, rows: list) -> list:
        content = msa._content()
        current = {(s.tax_regime, s.filing_status): s for s in self._slabs(db, pack, content.MY_EARNING_CLASS_RULE)}
        seen, results = set(), []
        for row in rows:
            key = (str(row.get("obligation") or "").strip().upper(), str(row.get("component") or "").strip().upper())
            ref = f"{key[0]} x {key[1]}"
            if key not in current:
                results.append(wbk.RowResult(EARNING, ref, "INVALID", "unknown obligation / component"))
                continue
            if key in seen:
                results.append(wbk.RowResult(EARNING, ref, "INVALID", "the pair appears twice"))
                continue
            seen.add(key)
            treatment = str(row.get("treatment") or "").strip().upper()
            slab = current[key]
            if not treatment or treatment == slab.assessment_basis:
                results.append(wbk.RowResult(EARNING, ref, "UNCHANGED"))
                continue
            if treatment not in content.TREATMENTS:
                results.append(wbk.RowResult(EARNING, ref, "INVALID", f"treatment must be one of "
                                                                      f"{', '.join(content.TREATMENTS)}"))
                continue
            problem = self._source_ok(db, row.get("source_document_id"))
            if problem:
                results.append(wbk.RowResult(EARNING, ref, "INVALID", problem))
                continue
            results.append(wbk.RowResult(EARNING, ref, "CHANGED", f"{slab.assessment_basis} -> {treatment}",
                                         change={"kind": "slab", "id": slab.id, "treatment": treatment,
                                                 "source": int(row["source_document_id"]), "page": row.get("page")}))
        return results

    # ── apply (unsigned writes through my_super_admin) ───────────────────
    def apply(self, db: Session, pack, changes: list, actor_id, reason: str) -> dict:
        names = {"employee_rate_pct": "employeeRatePct", "employer_rate_pct": "employerRatePct",
                 "flat_amount": "flatAmount", "text_value": "textValue"}
        written = {"parameters": 0, "tables": 0, "earningClasses": 0}
        for result in changes:
            change = result.change
            if change["kind"] == "rate":
                payload = {names[c]: (format(v, "f") if isinstance(v, Decimal) else v)
                           for c, v in change["values"].items() if v is not None}
                msa.update_row(db, "rate", change["id"], {**payload, "reason": reason,
                                                          "sourceDocumentId": change["source"],
                                                          "page": change.get("page")}, actor_id)
                written["parameters"] += 1
            elif change["kind"] == "slab":
                msa.update_row(db, "slab", change["id"], {"treatment": change["treatment"], "reason": reason,
                                                          "sourceDocumentId": change["source"],
                                                          "page": change.get("page")}, actor_id)
                written["earningClasses"] += 1
            else:
                written["tables"] += msa.replace_table(db, pack.id, change["rule"], change["rows"], actor_id, reason)
        return written
