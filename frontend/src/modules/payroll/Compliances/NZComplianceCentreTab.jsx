import { useEffect, useState } from "react";
import {
  approveNzEmployerProfile, createNzEmployerProfile, getEmployees, getNzSummary, grantNzFamilyViolenceView,
  listNzEmployerProfiles, listNzFamilyViolenceHolders, proposeNzPublicHolidays, revokeNzFamilyViolenceView,
  setNzEmployerIrdNumber, verifyNzEmployerProfile, vestNzEntitlements,
} from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import { Table } from "../../../components/jurisdiction/japan/jpShared";
import JPRecordSection, { btn, isDraft, statusCol } from "../../../components/jurisdiction/japan/JPRecordSection";
import {
  FILING_METHODS, PAYE_ESCT_BASES, REASON_FIELD, REMITTANCE_CLASSES, TIMEZONES, errorText, period,
} from "../../../components/jurisdiction/new_zealand/nzOrgOptions";
import { NewZealandEmployeeRecords } from "../Payroll_Employees/NewZealandStatutoryProfilePanel";

// New Zealand Compliance Centre (ZP-NZ-ENG-001). Organisation setup (employer
// profile per legal employer, verification, employer IRD number), Holidays Act
// administration (vesting, public holidays), the family-violence permission,
// and every employee's New Zealand records. Nothing here calculates: the
// engine reads only APPROVED versions on the payday and BLOCKS when a fact or
// a signed rule is missing.

const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const ask = (message) => {
  const value = window.prompt(message);
  return value && value.trim() ? value.trim() : null;
};

function SetupStatus() {
  const [summary, error] = useLoad(() => getNzSummary());
  if (error) return <p role="alert" className="text-[12px] text-error">{error}</p>;
  if (!summary) return null;
  const pack = (summary.packs || [])[0];
  return (
    <div className="rounded-xl border border-warning/40 bg-warning/10 p-3 text-[12px] text-foreground-secondary" data-testid="nz-setup-status">
      <p className="font-semibold text-foreground">New Zealand payroll is not yet certified.</p>
      <p className="mt-1">
        Rule pack {pack ? `${pack.packId} ${pack.version} (${pack.status})` : "not seeded"}: {summary.pendingRows ?? 0} row(s)
        awaiting signature; empty authority tables: {(summary.emptyAuthorityTables || []).join(", ") || "none"}. Until
        they are signed every New Zealand payslip is blocked with its reason — never estimated.
      </p>
      <p className="mt-1">
        Approved here: {summary.activeEmployerProfiles ?? 0} employer profile(s) ({summary.verifiedEmployerProfiles ?? 0} verified),{" "}
        {summary.activeTaxProfiles ?? 0} tax profile(s), {summary.activeKiwiSaverElections ?? 0} KiwiSaver election(s),{" "}
        {summary.approvedNotices ?? 0} authority notice(s).
      </p>
    </div>
  );
}

function EmployerIrd({ profiles, onDone }) {
  const [profileId, setProfileId] = useState("");
  const [number, setNumber] = useState("");
  const [state, setState] = useState({ error: null, notice: null });
  const submit = async (e) => {
    e.preventDefault();
    const value = number;
    setNumber("");                              // never keep the typed digits around
    try {
      await setNzEmployerIrdNumber(profileId, value);
      setState({ error: null, notice: "Employer IRD number stored (encrypted)." });
      onDone();
    } catch (err) {
      setState({ error: errorText(err), notice: null });
    }
  };
  return (
    <form onSubmit={submit} className="mt-3 flex flex-wrap items-end gap-2" aria-label="Employer IRD number" data-testid="nz-employer-ird">
      <select className={input} value={profileId} required onChange={(e) => setProfileId(e.target.value)} aria-label="Employer profile">
        <option value="">Employer profile…</option>
        {(profiles || []).filter((p) => p.status === "DRAFT").map((p) => (
          <option key={p.id} value={p.id}>{p.legal_name} · from {p.effective_from}</option>
        ))}
      </select>
      <input className={input} type="password" autoComplete="off" inputMode="numeric" maxLength={9} pattern="\d{8,9}"
        required aria-label="Employer IRD number" placeholder="Employer IRD number"
        value={number} onChange={(e) => setNumber(e.target.value.replace(/\D/g, ""))} />
      <button type="submit" className={btn}>Store employer IRD number</button>
      {state.error && <span role="alert" className="text-[12px] text-error">{state.error}</span>}
      {state.notice && <span role="status" className="text-[12px] text-success">{state.notice}</span>}
    </form>
  );
}

function EmployerProfiles() {
  const [version, setVersion] = useState(0);
  const [profiles] = useLoad(() => listNzEmployerProfiles());
  return (
    <div>
      <JPRecordSection
        key={version}
        title="Employer profile (per legal employer)" testId="nz-employer-profiles"
        description="Filing method, remittance class, ACC classification unit and references (never secrets). Set the employer IRD number on the DRAFT, approve it (second user), then verify it (second user)."
        load={listNzEmployerProfiles} create={createNzEmployerProfile}
        empty="No employer profile — New Zealand payroll is blocked until one is approved and verified."
        columns={[{ label: "In force", render: period }, { label: "Legal name", key: "legal_name" },
          { label: "Filing / remittance", render: (r) => `${r.filing_method} · ${r.remittance_class}` },
          { label: "Employer IRD", render: (r) => (r.employer_ird_vault_id ? "On file (masked)" : "Missing") },
          { label: "Verification", key: "verification_state" }, statusCol]}
        actions={[
          { label: "Approve", show: isDraft, run: (r) => approveNzEmployerProfile(r.id), ok: "Employer profile approved." },
          { label: "Verify", show: (r) => r.status === "ACTIVE" && r.verification_state !== "VERIFIED", ok: "Employer profile verified.",
            run: async (r) => {
              const reason = ask("Verification evidence / reason");
              if (!reason) throw new Error("A reason is required.");
              await verifyNzEmployerProfile(r.id, "VERIFIED", reason);
            } },
          { label: "Reject", show: (r) => r.status === "ACTIVE" && r.verification_state === "UNVERIFIED", ok: "Marked rejected.",
            run: async (r) => {
              const reason = ask("Why is the profile rejected?");
              if (!reason) throw new Error("A reason is required.");
              await verifyNzEmployerProfile(r.id, "REJECTED", reason);
            } },
        ]}
        fields={[
          { key: "effective_from", label: "Effective from", type: "date", required: true },
          { key: "legal_name", label: "Legal name", required: true },
          { key: "legal_entity_id", label: "Legal entity id (empty = organisation)", type: "number" },
          { key: "filing_method", label: "Filing method", type: "select", options: FILING_METHODS, required: true },
          { key: "filing_method_evidence_ref", label: "Filing method evidence" },
          { key: "remittance_class", label: "Remittance class", type: "select", options: REMITTANCE_CLASSES, required: true },
          { key: "annual_paye_esct_basis", label: "Annual PAYE/ESCT basis", type: "select", options: PAYE_ESCT_BASES },
          { key: "annual_paye_esct_amount", label: "Annual PAYE/ESCT amount", type: "number" },
          { key: "connected_business_group_ref", label: "Connected business group" },
          { key: "connected_business_evidence_ref", label: "Connected business evidence" },
          { key: "acc_classification_unit", label: "ACC classification unit" },
          { key: "timezone", label: "Time zone", type: "select", options: TIMEZONES },
          { key: "bank_mandate_ref", label: "Bank mandate reference" },
          { key: "filing_credential_ref", label: "Filing credential reference (key name only)" },
          { key: "evidence_ref", label: "Evidence reference" },
          REASON_FIELD,
        ]} />
      <EmployerIrd profiles={profiles} onDone={() => setVersion((v) => v + 1)} />
    </div>
  );
}

function LeaveAdministration() {
  const [asOf, setAsOf] = useState("");
  const [year, setYear] = useState(String(new Date().getFullYear()));
  const [state, setState] = useState({ busy: false, error: null, notice: null });
  const run = async (fn, notice) => {
    setState({ busy: true, error: null, notice: null });
    try {
      const result = await fn();
      setState({ busy: false, error: null, notice: notice(result) });
    } catch (e) {
      setState({ busy: false, error: errorText(e), notice: null });
    }
  };
  return (
    <section className={card} data-testid="nz-leave-admin">
      <h3 className="text-[14px] font-semibold text-foreground">Holidays Act administration</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">
        Vesting is safe to repeat (nothing vests twice) and blocks while the Holidays Act rows are unsigned. Public
        holidays are proposed per employee from the signed holiday table (national and their region).
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <input className={input} type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} aria-label="Vest as of" />
        <button type="button" className={btn} disabled={state.busy || !asOf}
          onClick={() => run(() => vestNzEntitlements({ asOf }), (r) => `Vested ${r?.vested ?? 0} entitlement(s) for ${r?.employees ?? 0} employee(s).`)}>
          Vest entitlements
        </button>
        <input className={`${input} w-20`} value={year} onChange={(e) => setYear(e.target.value.replace(/\D/g, "").slice(0, 4))}
          aria-label="Public holiday year" />
        <button type="button" className={btn} disabled={state.busy || year.length !== 4}
          onClick={() => run(() => proposeNzPublicHolidays({ year: Number(year) }), (r) => `Proposed ${(r || []).length} decision(s).`)}>
          Propose public holidays
        </button>
      </div>
      {state.error && <p role="alert" className="mt-2 text-[12px] text-error">{state.error}</p>}
      {state.notice && <p role="status" className="mt-2 text-[12px] text-success">{state.notice}</p>}
    </section>
  );
}

function FamilyViolencePermission() {
  const [rows, error, loading, reload] = useLoad(() => listNzFamilyViolenceHolders());
  const [userId, setUserId] = useState("");
  const [reason, setReason] = useState("");
  const [state, setState] = useState({ error: null, notice: null });
  const act = async (fn, notice) => {
    try {
      await fn();
      setState({ error: null, notice });
      reload();
    } catch (e) {
      setState({ error: errorText(e), notice: null });
    }
  };
  return (
    <section className={card} data-testid="nz-fv-permission">
      <h3 className="text-[14px] font-semibold text-foreground">Family violence leave — restricted access</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">
        Family violence leave never records a reason and is hidden everywhere except to holders of this permission.
        Another organisation admin grants it, with a reason; every restricted read is logged.
      </p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={(rows || []).filter((r) => !r.revokedAt)} empty="Nobody holds the permission."
          columns={[{ label: "User", key: "userId" }, { label: "Granted", key: "grantedAt" },
            { label: "", render: (r) => (
              <button type="button" className={btn} onClick={() => {
                const why = ask("Why is the permission revoked?");
                if (why) act(() => revokeNzFamilyViolenceView(r.userId, why), "Permission revoked.");
              }}>Revoke</button>
            ) }]} />
      )}
      <div className="mt-3 flex flex-wrap items-center gap-2">
        <input className={`${input} w-28`} placeholder="User id" value={userId}
          onChange={(e) => setUserId(e.target.value.replace(/\D/g, ""))} aria-label="User id" />
        <input className={input} placeholder="Reason (e.g. case officer)" value={reason}
          onChange={(e) => setReason(e.target.value)} aria-label="Grant reason" />
        <button type="button" className={btn} disabled={!userId || !reason.trim()}
          onClick={() => act(async () => { await grantNzFamilyViolenceView(Number(userId), reason.trim()); setUserId(""); setReason(""); },
            "Permission granted.")}>
          Grant
        </button>
      </div>
      {state.error && <p role="alert" className="mt-2 text-[12px] text-error">{state.error}</p>}
      {state.notice && <p role="status" className="mt-2 text-[12px] text-success">{state.notice}</p>}
    </section>
  );
}

function EmployeeRecords() {
  const [employees, setEmployees] = useState([]);
  const [selected, setSelected] = useState("");
  useEffect(() => {
    let ignore = false;
    getEmployees({}).then((list) => {
      if (!ignore) setEmployees(list.filter((e) => (e.countryCode || e.country) === "NZ"));
    });
    return () => { ignore = true; };
  }, []);
  return (
    <section className={card} data-testid="nz-employee-picker">
      <h3 className="text-[14px] font-semibold text-foreground">Employee records</h3>
      <label className="mt-2 flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted">
        Employee
        <select className={input} value={selected} onChange={(e) => setSelected(e.target.value)}>
          <option value="">— Select a New Zealand employee —</option>
          {employees.map((e) => <option key={e.id} value={e.id}>{e.name} · {e.employeeCode}</option>)}
        </select>
      </label>
      {employees.length === 0 && <p className="mt-2 text-[12px] text-foreground-muted">No employees with country NZ.</p>}
      {selected && <div className="mt-4"><NewZealandEmployeeRecords key={selected} employeeId={Number(selected)} /></div>}
    </section>
  );
}

export default function NZComplianceCentreTab() {
  return (
    <div className="space-y-4">
      <SetupStatus />
      <EmployerProfiles />
      <LeaveAdministration />
      <FamilyViolencePermission />
      <EmployeeRecords />
    </div>
  );
}
