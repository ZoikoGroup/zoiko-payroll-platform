import { useState } from "react";
import { setUpBeCatalogue } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { ErrorNote } from "../new_zealand/nzShared";
import Notice from "../Notice";

// Shown instead of the per-row reports for a Belgian pack that holds no
// catalogue rows yet (e.g. a pack created with "New Tax"): a calm explanation,
// never a developer message, and — for a Draft pack — "Set up Belgian
// catalogue": the standard rows with the approved spec values, every other row empty (reason
// required; audited; no value copied or invented).

function SetUpCatalogue({ pack, onDone }) {
  const [reason, setReason] = useState("");
  const [state, setState] = useState({ busy: false, error: null });
  async function submit() {
    setState({ busy: true, error: null });
    try {
      await setUpBeCatalogue(pack.id, reason.trim());
      setState({ busy: false, error: null });
      onDone?.();
    } catch (err) {
      setState({ busy: false, error: err.message || "The catalogue could not be set up." });
    }
  }
  return (
    <div className="mt-3 space-y-2" data-testid="be-catalogue-setup">
      <label className={labelClass} htmlFor={`be-catalogue-reason-${pack.id}`}>Reason *</label>
      <input id={`be-catalogue-reason-${pack.id}`} className={inputClass} value={reason}
        onChange={(e) => setReason(e.target.value)} placeholder="Why this pack needs the catalogue" />
      <ErrorNote message={state.error} />
      <button type="button" onClick={submit} disabled={state.busy || !reason.trim()} data-testid="be-catalogue-setup-button"
        className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover disabled:opacity-50">
        {state.busy ? "Setting up…" : "Set up Belgian catalogue"}
      </button>
    </div>
  );
}

export default function BECatalogueNotice({ pack, onDone }) {
  const draft = pack?.status === "Draft";
  return (
    <Notice tone="info" title="This pack has no Belgian statutory rows yet." testId="be-no-catalogue">
      <p>
        {pack?.packId} v{pack?.version} holds none of the Belgian catalogue rows. Once the standard catalogue is set
        up (approved spec values filled, every other row empty), the remaining values can be added row by row or
        imported from a file. A saved value is in force; there is no signing step.
      </p>
      {draft ? <SetUpCatalogue pack={pack} onDone={onDone} /> : (
        <p className="mt-2" data-testid="be-catalogue-not-draft">
          The catalogue can only be set up while the pack is in Draft (this pack is {pack?.status}).
        </p>
      )}
    </Notice>
  );
}
