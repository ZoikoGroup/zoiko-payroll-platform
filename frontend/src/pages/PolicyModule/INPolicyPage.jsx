import PolicyLayout from "./shared/PolicyLayout";

// India's Policy authoring page. No India-specific policy fields exist
// yet — this is the extension point (categoryFields/overtimeFields/
// payTypeChoices/extraSections props on PolicyLayout) for when they do,
// without touching any other country's file. Mirrors INCompliancePage.jsx
// on the Tax side.
export default function INPolicyPage() {
  return <PolicyLayout country="IN" countryName="India" />;
}
