// Real inline SVG flags — not Unicode flag emoji. Windows' default font
// (Segoe UI Emoji) has never shipped color flag glyphs, so emoji flags
// silently fall back to a two-letter code in a box on Windows, regardless
// of browser/refresh. Inline SVG renders identically on every platform.
// Simplified at this size (a 40px card icon) but recognizable — not
// aiming for vexillographic precision.

function India() {
  return (
    <svg viewBox="0 0 24 16" className="h-full w-full" preserveAspectRatio="xMidYMid slice">
      <rect width="24" height="16" fill="#fff" />
      <rect width="24" height="5.33" fill="#FF9933" />
      <rect y="10.67" width="24" height="5.33" fill="#138808" />
      <circle cx="12" cy="8" r="2" fill="none" stroke="#000080" strokeWidth="0.3" />
      <circle cx="12" cy="8" r="0.4" fill="#000080" />
    </svg>
  );
}

function UnitedStates() {
  const stripeH = 16 / 7;
  return (
    <svg viewBox="0 0 24 16" className="h-full w-full" preserveAspectRatio="xMidYMid slice">
      <rect width="24" height="16" fill="#fff" />
      {[0, 2, 4, 6].map((i) => <rect key={i} y={i * stripeH} width="24" height={stripeH} fill="#B22234" />)}
      <rect width="10" height={stripeH * 4} fill="#3C3B6E" />
    </svg>
  );
}

function UnitedKingdom() {
  return (
    <svg viewBox="0 0 24 16" className="h-full w-full" preserveAspectRatio="xMidYMid slice">
      <rect width="24" height="16" fill="#00247D" />
      <path d="M0,0 L24,16 M24,0 L0,16" stroke="#fff" strokeWidth="3.2" />
      <path d="M0,0 L24,16 M24,0 L0,16" stroke="#CF142B" strokeWidth="1.2" />
      <path d="M12,0 V16 M0,8 H24" stroke="#fff" strokeWidth="5.2" />
      <path d="M12,0 V16 M0,8 H24" stroke="#CF142B" strokeWidth="3" />
    </svg>
  );
}

function Australia() {
  return (
    <svg viewBox="0 0 24 16" className="h-full w-full" preserveAspectRatio="xMidYMid slice">
      <rect width="24" height="16" fill="#00247D" />
      <g transform="translate(0,0) scale(0.5)">
        <rect width="24" height="16" fill="#00247D" />
        <path d="M0,0 L24,16 M24,0 L0,16" stroke="#fff" strokeWidth="3.2" />
        <path d="M0,0 L24,16 M24,0 L0,16" stroke="#CF142B" strokeWidth="1.2" />
        <path d="M12,0 V16 M0,8 H24" stroke="#fff" strokeWidth="5.2" />
        <path d="M12,0 V16 M0,8 H24" stroke="#CF142B" strokeWidth="3" />
      </g>
      {[[17, 3], [20, 6], [17, 9], [14, 6.5], [19, 12]].map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r={i === 4 ? 0.9 : 0.6} fill="#fff" />
      ))}
    </svg>
  );
}

function Canada() {
  return (
    <svg viewBox="0 0 24 16" className="h-full w-full" preserveAspectRatio="xMidYMid slice">
      <rect width="24" height="16" fill="#fff" />
      <rect width="6" height="16" fill="#D80621" />
      <rect x="18" width="6" height="16" fill="#D80621" />
      <path
        d="M12 3 L12.7 5 L14.3 4.3 L13.6 6 L15.5 6.3 L13.9 7.5 L15 9 L13 8.6 L13.2 10.5 L12 9.2 L10.8 10.5 L11 8.6 L9 9 L10.1 7.5 L8.5 6.3 L10.4 6 L9.7 4.3 L11.3 5 Z"
        fill="#D80621"
      />
    </svg>
  );
}

function Germany() {
  return (
    <svg viewBox="0 0 24 16" className="h-full w-full" preserveAspectRatio="xMidYMid slice">
      <rect width="24" height="5.33" fill="#000" />
      <rect y="5.33" width="24" height="5.33" fill="#DD0000" />
      <rect y="10.67" width="24" height="5.33" fill="#FFCE00" />
    </svg>
  );
}

// ── Caribbean production jurisdictions (2026-09-21) — simplified, same
// "recognizable, not vexillographically precise" convention as every
// flag above.

function Barbados() {
  return (
    <svg viewBox="0 0 24 16" className="h-full w-full" preserveAspectRatio="xMidYMid slice">
      <rect width="8" height="16" fill="#00267F" />
      <rect x="8" width="8" height="16" fill="#FFC726" />
      <rect x="16" width="8" height="16" fill="#00267F" />
      <path d="M11 3 L13 3 L13 10 L11.7 13 L11 10 Z" fill="#000" />
    </svg>
  );
}

function CaymanIslands() {
  return (
    <svg viewBox="0 0 24 16" className="h-full w-full" preserveAspectRatio="xMidYMid slice">
      <rect width="24" height="16" fill="#A5C8ED" />
      <rect width="12" height="8" fill="#00247D" />
      <path d="M0,0 L12,8 M12,0 L0,8" stroke="#fff" strokeWidth="1.6" />
      <path d="M0,0 L12,8 M12,0 L0,8" stroke="#CF142B" strokeWidth="0.6" />
      <path d="M6,0 V8 M0,4 H12" stroke="#fff" strokeWidth="2.6" />
      <path d="M6,0 V8 M0,4 H12" stroke="#CF142B" strokeWidth="1.5" />
      <circle cx="17" cy="8" r="3.4" fill="#fff" stroke="#00267F" strokeWidth="0.4" />
    </svg>
  );
}

function DominicanRepublic() {
  return (
    <svg viewBox="0 0 24 16" className="h-full w-full" preserveAspectRatio="xMidYMid slice">
      <rect width="24" height="16" fill="#002D62" />
      <rect x="10" width="4" height="16" fill="#fff" />
      <rect y="6" width="24" height="4" fill="#fff" />
      <rect width="10" height="6" fill="#CE1126" />
      <rect x="14" width="10" height="6" fill="#002D62" />
      <rect width="10" height="6" y="10" fill="#002D62" />
      <rect x="14" width="10" height="6" y="10" fill="#CE1126" />
    </svg>
  );
}

function Guyana() {
  return (
    <svg viewBox="0 0 24 16" className="h-full w-full" preserveAspectRatio="xMidYMid slice">
      <rect width="24" height="16" fill="#009E49" />
      <polygon points="0,0 16,8 0,16" fill="#FCD116" />
      <polygon points="0,0 10,8 0,16" fill="#CE1126" />
      <polygon points="0,3 5,8 0,13" fill="#000" />
    </svg>
  );
}

function Jamaica() {
  return (
    <svg viewBox="0 0 24 16" className="h-full w-full" preserveAspectRatio="xMidYMid slice">
      <rect width="24" height="16" fill="#000" />
      <polygon points="0,0 24,16 24,0" fill="#009B3A" />
      <polygon points="0,0 0,16 24,16" fill="#009B3A" />
      <path d="M0,0 L24,16 M24,0 L0,16" stroke="#FED100" strokeWidth="2.6" />
    </svg>
  );
}

function Bahamas() {
  return (
    <svg viewBox="0 0 24 16" className="h-full w-full" preserveAspectRatio="xMidYMid slice">
      <rect width="24" height="5.33" fill="#00778B" />
      <rect y="5.33" width="24" height="5.33" fill="#FFC72C" />
      <rect y="10.67" width="24" height="5.33" fill="#00778B" />
      <polygon points="0,0 9,8 0,16" fill="#000" />
    </svg>
  );
}

function TrinidadAndTobago() {
  return (
    <svg viewBox="0 0 24 16" className="h-full w-full" preserveAspectRatio="xMidYMid slice">
      <rect width="24" height="16" fill="#CE1126" />
      <path d="M-2,18 L18,-2" stroke="#fff" strokeWidth="4.6" />
      <path d="M-2,18 L18,-2" stroke="#000" strokeWidth="2.8" />
    </svg>
  );
}

function PuertoRico() {
  const stripeH = 16 / 5;
  return (
    <svg viewBox="0 0 24 16" className="h-full w-full" preserveAspectRatio="xMidYMid slice">
      {[0, 1, 2, 3, 4].map((i) => (
        <rect key={i} y={i * stripeH} width="24" height={stripeH} fill={i % 2 === 0 ? "#ED1B34" : "#fff"} />
      ))}
      <path d="M0,0 L10,8 L0,16 Z" fill="#0050A4" />
      <path
        d="M3.6,8 l1.2,-0.9 l1.2,0.9 l-0.46,-1.4 l1.2,-0.9 h-1.48 l-0.46,-1.4 l-0.46,1.4 h-1.48 l1.2,0.9 z"
        fill="#fff"
      />
    </svg>
  );
}

function France() {
  return (
    <svg viewBox="0 0 24 16" className="h-full w-full" preserveAspectRatio="xMidYMid slice">
      <rect width="8" height="16" fill="#002395" />
      <rect x="8" width="8" height="16" fill="#fff" />
      <rect x="16" width="8" height="16" fill="#ED2939" />
    </svg>
  );
}

function Ireland() {
  return (
    <svg viewBox="0 0 24 16" className="h-full w-full" preserveAspectRatio="xMidYMid slice">
      <rect width="8" height="16" fill="#169B62" />
      <rect x="8" width="8" height="16" fill="#fff" />
      <rect x="16" width="8" height="16" fill="#FF883E" />
    </svg>
  );
}

const FLAGS = {
  IN: India, US: UnitedStates, UK: UnitedKingdom, AU: Australia, CA: Canada, DE: Germany,
  BB: Barbados, KY: CaymanIslands, DO: DominicanRepublic, GY: Guyana, JM: Jamaica, BS: Bahamas, TT: TrinidadAndTobago,
  PR: PuertoRico, FR: France, IE: Ireland,
};

export default function CountryFlag({ code, className = "", fallback = null }) {
  const Flag = FLAGS[code];
  if (!Flag) return fallback;
  return (
    <span className={`inline-flex overflow-hidden rounded ${className}`}>
      <Flag />
    </span>
  );
}
