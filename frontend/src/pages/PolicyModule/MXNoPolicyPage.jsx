import { useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

// Mexico has no pay-structure policy pack (completion W5-4, gap register A7 /
// OOS-6). Before this, "+ New Policy" for Mexico fell back to India's form and
// would have authored an India-shaped pack nothing in Mexico reads. Mexican
// statutory content is the national and state tax packs; each employer's
// labour policy is recorded by the organisation and floor-checked against them.
export default function MXNoPolicyPage() {
  const navigate = useNavigate();
  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4 p-6" data-testid="mx-no-policy-page">
      <button type="button" onClick={() => navigate("/super-admin/compliance/mexico")}
              className="flex w-fit items-center gap-1 text-[13px] text-foreground-muted hover:text-foreground">
        <ArrowLeft size={14} /> Back to Mexico Compliance
      </button>
      <div className="rounded-xl border border-border bg-surface p-5">
        <h1 className="text-[18px] font-semibold text-foreground">Mexico has no policy pack</h1>
        <p className="mt-2 text-[13px] text-foreground-secondary">
          No Mexican calculation reads a Super Admin policy pack, so none can be authored here.
        </p>
        <ul className="mt-3 flex list-disc flex-col gap-1 pl-5 text-[13px] text-foreground-secondary">
          <li>Statutory content (ISR, IMSS, INFONAVIT, minimum wages, benefit floors, state ISN) is in the Mexico
            tax packs, seeded from saved, cited sources — see Compliance → Mexico → Statutory rules.</li>
          <li>Each employer&apos;s labour policy (vacation, vacation premium, aguinaldo, working week) is recorded by
            the organisation in its Mexico Compliance Centre and floor-checked against the national pack.</li>
        </ul>
      </div>
    </div>
  );
}
