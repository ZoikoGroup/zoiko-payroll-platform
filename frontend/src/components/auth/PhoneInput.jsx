import CountrySelect from "../jurisdiction/CountrySelect";
import { authInputClass } from "./authUi";

// Country calling code + number for the registration countries. Codes are the
// ITU international dialling codes; North American Numbering Plan members
// (US, Canada, the Caribbean) all dial +1 and the area code is typed as part
// of the number. Every REGISTRATION_COUNTRIES entry must be listed here:
// a missing one used to fall back to "US +1" whatever country was chosen.
export const DIAL_CODES = {
  "India": ["IN", "+91"], "Germany": ["DE", "+49"], "Canada": ["CA", "+1"], "United States": ["US", "+1"],
  "United Kingdom": ["GB", "+44"], "Australia": ["AU", "+61"], "Barbados": ["BB", "+1"],
  "Cayman Islands": ["KY", "+1"], "Dominican Republic": ["DO", "+1"], "Guyana": ["GY", "+592"],
  "Jamaica": ["JM", "+1"], "Bahamas": ["BS", "+1"], "Trinidad and Tobago": ["TT", "+1"],
  "Puerto Rico": ["PR", "+1"], "France": ["FR", "+33"], "Ireland": ["IE", "+353"], "Sweden": ["SE", "+46"],
  "Brazil": ["BR", "+55"], "Hong Kong": ["HK", "+852"], "Italy": ["IT", "+39"], "Netherlands": ["NL", "+31"],
  "Saudi Arabia": ["SA", "+966"], "Singapore": ["SG", "+65"], "Switzerland": ["CH", "+41"],
  "Mexico": ["MX", "+52"], "United Arab Emirates": ["AE", "+971"], "Spain": ["ES", "+34"],
  "Japan": ["JP", "+81"], "New Zealand": ["NZ", "+64"], "Poland": ["PL", "+48"], "Malaysia": ["MY", "+60"],
  "South Africa": ["ZA", "+27"], "Belgium": ["BE", "+32"],
};

export const DEFAULT_PHONE_COUNTRY = "United States";

/** The calling-code country to use: the given one when we know its code, else the default. */
export function phoneCountryOrDefault(country) {
  return country && DIAL_CODES[country] ? country : DEFAULT_PHONE_COUNTRY;
}

export function dialCodeForCountry(country) {
  return DIAL_CODES[phoneCountryOrDefault(country)][1];
}

// Calling-code options: the country's flag and name in the list, its code
// alongside; the closed selector shows the flag and the code.
const PHONE_OPTIONS = Object.entries(DIAL_CODES).map(([name, [iso, dial]]) => ({
  value: name, label: name, code: iso, hint: dial,
}));
const INVALID = "border-red-400! focus:border-red-500! focus:ring-red-500/15!";

export default function PhoneInput({ id, country, onCountryChange, number, onNumberChange, invalid = false, describedBy }) {
  const selected = phoneCountryOrDefault(country);
  return (
    <div className="flex gap-2">
      <CountrySelect
        variant="auth"
        compact
        className="w-[6.75rem] shrink-0"
        value={selected}
        onChange={onCountryChange}
        options={PHONE_OPTIONS}
        selectedLabel={DIAL_CODES[selected][1]}
        ariaLabel="Country calling code"
        panelMinWidth={280}
      />
      <div className="min-w-0 flex-1">
        <input
          id={id} type="tel" autoComplete="tel-national" inputMode="tel"
          value={number} onChange={(e) => onNumberChange(e.target.value)}
          aria-invalid={invalid || undefined} aria-describedby={describedBy} aria-required="true"
          placeholder="Phone number" className={`${authInputClass()} h-11 ${invalid ? INVALID : ""}`}
        />
      </div>
    </div>
  );
}
