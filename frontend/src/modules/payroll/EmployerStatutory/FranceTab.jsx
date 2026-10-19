import { useState } from "react";
import FranceProfileSection from "./FranceProfileSection";
import FranceEstablishmentsSection from "./FranceEstablishmentsSection";
import FranceReadinessSection from "./FranceReadinessSection";

const SECTIONS = [
  { key: "profile", label: "Employer profile & effectif" },
  { key: "establishments", label: "Establishments & rates" },
  { key: "readiness", label: "Readiness & go-live" },
];

export default function FranceTab({ readOnly }) {
  const [section, setSection] = useState("profile");
  return (
    <div className="space-y-4">
      <div className="flex w-full flex-wrap gap-1 rounded-[12px] border border-border p-1 sm:w-fit" role="tablist" aria-label="France sections">
        {SECTIONS.map((s) => (
          <button key={s.key} type="button" role="tab" aria-selected={section === s.key} onClick={() => setSection(s.key)}
            className={`rounded-[10px] px-3 py-1.5 text-[12px] font-semibold transition-all duration-200 ${
              section === s.key ? "bg-primary/10 text-primary dark:bg-primary/20" : "text-foreground-muted hover:text-foreground"
            }`}>
            {s.label}
          </button>
        ))}
      </div>
      {section === "profile" && <FranceProfileSection readOnly={readOnly} />}
      {section === "establishments" && <FranceEstablishmentsSection readOnly={readOnly} />}
      {section === "readiness" && <FranceReadinessSection readOnly={readOnly} />}
    </div>
  );
}
