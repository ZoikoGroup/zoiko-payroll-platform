// Full US state/territory name -> 2-letter postal abbreviation. Needed
// because JurisdictionPack.jurisdictionState stores the full name (e.g.
// "California") while EmployerTaxProfile.jurisdictionId and
// ReciprocityRule's resident/workJurisdiction use "US-CA"-style codes —
// this is the only place that bridges the two formats.
export const US_STATE_ABBREVIATIONS = {
  Alabama: "AL", Alaska: "AK", Arizona: "AZ", Arkansas: "AR", California: "CA",
  Colorado: "CO", Connecticut: "CT", Delaware: "DE", "District of Columbia": "DC",
  Florida: "FL", Georgia: "GA", Hawaii: "HI", Idaho: "ID", Illinois: "IL",
  Indiana: "IN", Iowa: "IA", Kansas: "KS", Kentucky: "KY", Louisiana: "LA",
  Maine: "ME", Maryland: "MD", Massachusetts: "MA", Michigan: "MI", Minnesota: "MN",
  Mississippi: "MS", Missouri: "MO", Montana: "MT", Nebraska: "NE", Nevada: "NV",
  "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
  "North Carolina": "NC", "North Dakota": "ND", Ohio: "OH", Oklahoma: "OK",
  Oregon: "OR", Pennsylvania: "PA", "Rhode Island": "RI", "South Carolina": "SC",
  "South Dakota": "SD", Tennessee: "TN", Texas: "TX", Utah: "UT", Vermont: "VT",
  Virginia: "VA", Washington: "WA", "West Virginia": "WV", Wisconsin: "WI",
  Wyoming: "WY", "Puerto Rico": "PR",
};

// Returns "US-CA" for "California", or null if the state has no known code
// (e.g. an unusual/custom jurisdictionState value entered as free text).
export function toUsJurisdictionCode(stateName) {
  const code = US_STATE_ABBREVIATIONS[stateName];
  return code ? `US-${code}` : null;
}
