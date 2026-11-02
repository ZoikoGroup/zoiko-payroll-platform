import { ChevronDown, Phone } from "lucide-react";

import { authInputClass } from "./authUi";

// Country calling code + number for the registration countries. Codes are the
// ITU international dialling codes; North American Numbering Plan members
// (US, Canada, the Caribbean) all dial +1 and the area code is typed as part
// of the number.
const DIAL_CODES = {
  "India": ["IN", "+91"], "Germany": ["DE", "+49"], "Canada": ["CA", "+1"], "United States": ["US", "+1"],
  "United Kingdom": ["GB", "+44"], "Australia": ["AU", "+61"], "Barbados": ["BB", "+1"],
  "Cayman Islands": ["KY", "+1"], "Dominican Republic": ["DO", "+1"], "Guyana": ["GY", "+592"],
  "Jamaica": ["JM", "+1"], "Bahamas": ["BS", "+1"], "Trinidad and Tobago": ["TT", "+1"],
  "Puerto Rico": ["PR", "+1"], "France": ["FR", "+33"], "Ireland": ["IE", "+353"], "Sweden": ["SE", "+46"],
  "Brazil": ["BR", "+55"], "Hong Kong": ["HK", "+852"], "Italy": ["IT", "+39"], "Netherlands": ["NL", "+31"],
  "Saudi Arabia": ["SA", "+966"], "Singapore": ["SG", "+65"], "Switzerland": ["CH", "+41"],
};

export function dialCodeForCountry(country) {
  return (DIAL_CODES[country] || ["US", "+1"])[1];
}

const SELECT_CLASS = authInputClass({ withTrailing: true }).replace("pl-4", "pl-3") + " appearance-none";

export default function PhoneInput({ id, country, onCountryChange, number, onNumberChange }) {
  return (
    <div className="flex gap-2">
      <div className="relative w-[7.5rem] shrink-0">
        <select
          aria-label="Country calling code"
          value={country}
          onChange={(e) => onCountryChange(e.target.value)}
          className={SELECT_CLASS}
        >
          {Object.entries(DIAL_CODES).map(([name, [iso, code]]) => (
            <option key={name} value={name}>{`${iso} ${code}`}</option>
          ))}
        </select>
        <ChevronDown size={16} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
      </div>
      <div className="relative min-w-0 flex-1">
        <Phone size={17} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-500" />
        <input
          id={id} type="tel" required autoComplete="tel-national"
          value={number} onChange={(e) => onNumberChange(e.target.value)}
          placeholder="e.g. 212 555 0123" className={authInputClass({ withIcon: true })}
        />
      </div>
    </div>
  );
}
