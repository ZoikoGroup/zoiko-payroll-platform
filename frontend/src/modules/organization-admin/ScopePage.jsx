import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { scopeService } from "../../service/scopeService";
import { listOrgUsers } from "../../service/orgAdminService";
import { getEmployees } from "../../service/payrollService";

// Legal Entities & Pay Groups (ZP-PRIV C.3). A payroll admin with entity or
// pay-group scope sees ONLY the workers placed in them - enforced on the
// server for every list, search, export and payslip; this page manages the
// units, the placements and each payroll admin's scope.
const card = "rounded-xl border border-border-light bg-surface p-5 shadow-sm space-y-3";
const btn = "inline-flex items-center rounded-lg px-3 py-1.5 text-sm font-medium disabled:opacity-50";
const input = "rounded-lg border border-border-light bg-surface px-3 py-2 text-sm text-foreground";

function useLoad(fn) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const reload = useCallback(async () => {
    try {
      setData(await fn());
      setError(null);
    } catch (err) {
      setError(err.message || "Could not load.");
    }
  }, [fn]);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    reload();
  }, [reload]);
  return { data, error, reload };
}

function UnitsTab() {
  const entities = useLoad(scopeService.listEntities);
  const groups = useLoad(scopeService.listPayGroups);
  const [entityName, setEntityName] = useState("");
  const [groupName, setGroupName] = useState("");
  const [groupEntity, setGroupEntity] = useState("");
  const [error, setError] = useState(null);

  async function run(fn) {
    setError(null);
    try {
      await fn();
    } catch (err) {
      setError(err.message || "That did not work.");
    }
  }

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      {error && <p role="alert" className="text-sm text-red-600 lg:col-span-2">{error}</p>}
      <div className={card}>
        <h2 className="text-lg font-semibold text-foreground">Legal entities</h2>
        <ul className="divide-y divide-border-light text-sm text-foreground">
          {(entities.data || []).map((e) => <li key={e.id} className="py-2">{e.name}{e.country ? ` · ${e.country}` : ""}</li>)}
          {entities.data?.length === 0 && <li className="py-2 text-foreground-secondary">None yet.</li>}
        </ul>
        <div className="flex gap-2">
          <input className={`${input} flex-1`} placeholder="New entity name" value={entityName} onChange={(e) => setEntityName(e.target.value)} />
          <button type="button" className={`${btn} bg-blue-600 text-white`} disabled={!entityName.trim()}
            onClick={() => run(async () => { await scopeService.createEntity({ name: entityName.trim() }); setEntityName(""); entities.reload(); })}>
            Add
          </button>
        </div>
      </div>
      <div className={card}>
        <h2 className="text-lg font-semibold text-foreground">Pay groups</h2>
        <ul className="divide-y divide-border-light text-sm text-foreground">
          {(groups.data || []).map((g) => (
            <li key={g.id} className="flex items-center justify-between py-2">
              <span>{g.name}{g.isDefault ? " (default)" : ""}{!g.isActive ? " — inactive" : ""}</span>
              <span className="text-foreground-secondary">
                {(entities.data || []).find((e) => e.id === g.legalEntityId)?.name || "Any entity"}
              </span>
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap gap-2">
          <input className={`${input} flex-1`} placeholder="New pay group name" value={groupName} onChange={(e) => setGroupName(e.target.value)} />
          <select className={input} value={groupEntity} onChange={(e) => setGroupEntity(e.target.value)} aria-label="Legal entity">
            <option value="">Any entity</option>
            {(entities.data || []).map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
          </select>
          <button type="button" className={`${btn} bg-blue-600 text-white`} disabled={!groupName.trim()}
            onClick={() => run(async () => {
              await scopeService.createPayGroup({ name: groupName.trim(), legalEntityId: groupEntity ? Number(groupEntity) : null });
              setGroupName("");
              groups.reload();
            })}>
            Add
          </button>
        </div>
      </div>
    </div>
  );
}

function PlacementTab() {
  const employees = useLoad(getEmployees);
  const entities = useLoad(scopeService.listEntities);
  const groups = useLoad(scopeService.listPayGroups);
  const [saving, setSaving] = useState(null);
  const [error, setError] = useState(null);

  async function place(emp, patch) {
    setSaving(emp.id);
    setError(null);
    try {
      await scopeService.setPlacement(emp.id, {
        legalEntityId: patch.legalEntityId !== undefined ? patch.legalEntityId : emp.legalEntityId ?? null,
        payGroupId: patch.payGroupId !== undefined ? patch.payGroupId : emp.payGroupId ?? null,
      });
      await employees.reload();
    } catch (err) {
      setError(err.message || "Could not save the placement.");
    } finally {
      setSaving(null);
    }
  }

  const list = Array.isArray(employees.data) ? employees.data : employees.data?.items || [];
  return (
    <div className={`${card} overflow-x-auto`}>
      {error && <p role="alert" className="text-sm text-red-600">{error}</p>}
      <p className="text-sm text-foreground-secondary">
        Workers without an entity or pay group are visible only to organization-wide admins.
      </p>
      <table className="w-full text-left text-sm">
        <thead className="text-foreground-secondary">
          <tr><th className="py-2 pr-3">Employee</th><th className="pr-3">Legal entity</th><th>Pay group</th></tr>
        </thead>
        <tbody className="divide-y divide-border-light text-foreground">
          {list.map((emp) => (
            <tr key={emp.id}>
              <td className="py-2 pr-3">{emp.name} · {emp.employeeCode}</td>
              <td className="pr-3">
                <select className={input} disabled={saving === emp.id} value={emp.legalEntityId ?? ""}
                  onChange={(e) => place(emp, { legalEntityId: e.target.value ? Number(e.target.value) : null })}
                  aria-label={`Legal entity for ${emp.name}`}>
                  <option value="">Unassigned</option>
                  {(entities.data || []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                </select>
              </td>
              <td>
                <select className={input} disabled={saving === emp.id} value={emp.payGroupId ?? ""}
                  onChange={(e) => place(emp, { payGroupId: e.target.value ? Number(e.target.value) : null })}
                  aria-label={`Pay group for ${emp.name}`}>
                  <option value="">Unassigned</option>
                  {(groups.data || []).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TeamScopeTab({ initialUser }) {
  const users = useLoad(useCallback(() => listOrgUsers({ limit: 200 }), []));
  const entities = useLoad(scopeService.listEntities);
  const groups = useLoad(scopeService.listPayGroups);
  const [userId, setUserId] = useState(initialUser || "");
  const [scope, setScope] = useState(null);
  const [message, setMessage] = useState(null);

  useEffect(() => {
    if (!userId) return;
    scopeService.getUserScope(userId).then(setScope).catch((err) => setMessage(err.message));
  }, [userId]);

  const admins = (users.data?.users || users.data?.items || users.data || []).filter?.((u) => u.role === "payroll_admin") || [];
  function toggle(key, id) {
    const set = new Set(scope[key]);
    if (set.has(id)) set.delete(id);
    else set.add(id);
    setScope({ ...scope, [key]: [...set] });
  }

  async function save() {
    try {
      setScope(await scopeService.setUserScope(userId, { legalEntityIds: scope.legalEntityIds, payGroupIds: scope.payGroupIds }));
      setMessage("Scope saved.");
    } catch (err) {
      setMessage(err.message || "Could not save the scope.");
    }
  }

  return (
    <div className={card}>
      <label className="block space-y-1 text-sm">
        <span className="text-foreground-secondary">Payroll admin</span>
        <select className={`${input} w-full`} value={userId} onChange={(e) => { setUserId(e.target.value); setMessage(null); }}>
          <option value="">Choose a payroll admin</option>
          {admins.map((u) => <option key={u.id} value={u.id}>{u.first_name} {u.last_name} · {u.email}</option>)}
        </select>
      </label>
      {scope && (
        <>
          <p className="text-sm text-foreground">
            {scope.legalEntityIds.length || scope.payGroupIds.length
              ? "Sees only workers in the ticked units."
              : "Organization-wide (no scope set)."}
          </p>
          <div className="grid gap-4 sm:grid-cols-2 text-sm">
            <fieldset><legend className="font-medium text-foreground">Legal entities</legend>
              {(entities.data || []).map((x) => (
                <label key={x.id} className="flex items-center gap-2 text-foreground">
                  <input type="checkbox" checked={scope.legalEntityIds.includes(x.id)} onChange={() => toggle("legalEntityIds", x.id)} />{x.name}
                </label>
              ))}
            </fieldset>
            <fieldset><legend className="font-medium text-foreground">Pay groups</legend>
              {(groups.data || []).map((x) => (
                <label key={x.id} className="flex items-center gap-2 text-foreground">
                  <input type="checkbox" checked={scope.payGroupIds.includes(x.id)} onChange={() => toggle("payGroupIds", x.id)} />{x.name}
                </label>
              ))}
            </fieldset>
          </div>
          <button type="button" className={`${btn} bg-blue-600 text-white`} onClick={save}>Save scope</button>
        </>
      )}
      {message && <p role="status" className="text-sm text-foreground-secondary">{message}</p>}
    </div>
  );
}

export default function ScopePage() {
  const [params, setParams] = useSearchParams();
  const tab = ["units", "placement", "team"].includes(params.get("tab")) ? params.get("tab") : "units";
  return (
    <div className="space-y-5 p-4 sm:p-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Legal Entities & Pay Groups</h1>
        <p className="text-sm text-foreground-secondary">
          Limit payroll admins to the parts of your organization they run.
        </p>
      </div>
      <div role="tablist" className="flex gap-2 border-b border-border-light">
        {[["units", "Entities & pay groups"], ["placement", "Worker placement"], ["team", "Team scope"]].map(([key, label]) => (
          <button key={key} type="button" role="tab" aria-selected={tab === key}
            onClick={() => setParams((p) => { p.set("tab", key); return p; })}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === key ? "border-blue-600 font-semibold text-foreground" : "border-transparent text-foreground-secondary"}`}>
            {label}
          </button>
        ))}
      </div>
      {tab === "units" && <UnitsTab />}
      {tab === "placement" && <PlacementTab />}
      {tab === "team" && <TeamScopeTab initialUser={params.get("user") || ""} />}
    </div>
  );
}
