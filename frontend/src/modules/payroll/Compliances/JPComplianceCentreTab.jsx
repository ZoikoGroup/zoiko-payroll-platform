// Japan Compliance Centre (ZP-JP-ENG-001) - scaffold
export default function JPComplianceCentreTab() {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <h3 className="text-[14px] font-semibold text-foreground">Japan Compliance Centre (scaffold)</h3>
      <p className="mt-1 text-[12px] text-foreground-muted">
        Multi-system: National withholding (NTA), municipality inhabitant tax (special collection),
        social insurance (health/pension/care/child-support), employment insurance, workers compensation.
        Configuration via approved packs; resident tax imported as schedules (not calculated). Year-end adjustment separate.
        Production disabled until certified packs and fixtures are in place.
      </p>
    </div>
  );
}
