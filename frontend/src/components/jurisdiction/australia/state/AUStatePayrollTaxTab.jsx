import { useState } from "react";
import RatesTab from "../../RatesTab";
import SlabsTab from "../../SlabsTab";
import RateFormModal from "../../RateFormModal";
import SlabFormModal from "../../SlabFormModal";
import ConfirmDialog from "../../../ConfirmDialog";
import { useToast } from "../../../../context/ToastContext";
import { deleteCanonicalContributionRate, deleteCanonicalTaxSlab } from "../../../../service/superAdminService";

// One state pack's own payroll-tax configuration. Each of the 8 states
// reads from only ONE of these two shapes (§14-18, see
// engine/countries/australia.py's calculate_au_state_payroll_tax): WA/
// QLD/VIC/NT/SA read flat threshold/rate/taper PARAMETERS via
// resolve_jurisdiction_parameter (plain ContributionRate rows — same
// mechanism as Medicare/Super), while NSW/TAS/ACT read a genuine
// marginal BRACKET table (plain TaxSlab rows via the same
// _calculate_annual_tax every ordinary income-tax bracket already
// uses). Rather than branch the UI per state (fragile — a copy/paste
// error here would silently misconfigure a state), this shows both
// generic editors stacked, same as the country-level pack's own
// "Contribution Rates"/"Tax Slabs" tabs — whichever this state actually
// uses ends up populated, the other stays empty, exactly like the
// existing empty-state contract everywhere else.
export default function AUStatePayrollTaxTab({ pack, rates, slabs, onReload }) {
  const { addToast } = useToast() || {};
  const [showNewRate, setShowNewRate] = useState(false);
  const [editingRate, setEditingRate] = useState(null);
  const [deletingRate, setDeletingRate] = useState(null);
  const [showNewSlab, setShowNewSlab] = useState(false);
  const [editingSlab, setEditingSlab] = useState(null);
  const [deletingSlab, setDeletingSlab] = useState(null);

  return (
    <div className="space-y-6">
      <div>
        <h4 className="mb-2 text-[11px] font-bold uppercase tracking-wider text-foreground-muted">
          Threshold / Rate / Taper Parameters (WA, QLD, VIC, NT, SA)
        </h4>
        <RatesTab pack={pack} rates={rates} onAdd={() => setShowNewRate(true)} onEdit={setEditingRate} onDelete={setDeletingRate} />
      </div>
      <div>
        <h4 className="mb-2 text-[11px] font-bold uppercase tracking-wider text-foreground-muted">
          Marginal Bracket Table (NSW, TAS, ACT)
        </h4>
        <SlabsTab pack={pack} slabs={slabs} onAdd={() => setShowNewSlab(true)} onEdit={setEditingSlab} onDelete={setDeletingSlab} />
      </div>

      {(showNewRate || editingRate) && (
        <RateFormModal
          pack={pack} rate={editingRate}
          onClose={() => { setShowNewRate(false); setEditingRate(null); }}
          onSaved={() => { setShowNewRate(false); setEditingRate(null); onReload(); }}
        />
      )}
      {(showNewSlab || editingSlab) && (
        <SlabFormModal
          pack={pack} slab={editingSlab}
          onClose={() => { setShowNewSlab(false); setEditingSlab(null); }}
          onSaved={() => { setShowNewSlab(false); setEditingSlab(null); onReload(); }}
        />
      )}
      {deletingRate && (
        <ConfirmDialog
          title="Delete Rate" message={`Delete "${deletingRate.label}"? This cannot be undone.`}
          onConfirm={async () => {
            try { await deleteCanonicalContributionRate(deletingRate.id); addToast?.("Deleted.", "success"); }
            catch (err) { addToast?.(err.message || "Failed to delete.", "error"); }
            setDeletingRate(null);
            onReload();
          }}
          onClose={() => setDeletingRate(null)}
        />
      )}
      {deletingSlab && (
        <ConfirmDialog
          title="Delete Bracket" message={`Delete the "${deletingSlab.rateLabel}" bracket? This cannot be undone.`}
          onConfirm={async () => {
            try { await deleteCanonicalTaxSlab(deletingSlab.id); addToast?.("Deleted.", "success"); }
            catch (err) { addToast?.(err.message || "Failed to delete.", "error"); }
            setDeletingSlab(null);
            onReload();
          }}
          onClose={() => setDeletingSlab(null)}
        />
      )}
    </div>
  );
}
