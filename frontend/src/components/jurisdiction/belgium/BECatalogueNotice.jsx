import Notice from "../Notice";

// Shown instead of the per-row reports for a Belgian pack that holds no
// catalogue rows yet (e.g. a pack created with "New Tax"): a calm explanation,
// never a developer message.
export default function BECatalogueNotice({ pack, children = null }) {
  return (
    <Notice tone="info" title="This pack has no Belgian statutory rows yet." testId="be-no-catalogue">
      <p>
        {pack?.packId} v{pack?.version} holds none of the Belgian catalogue rows. Once the standard catalogue is set
        up (every row empty and unsigned), values can be added row by row or imported from a file, and a second Super
        Admin signs them.
      </p>
      {children}
    </Notice>
  );
}
