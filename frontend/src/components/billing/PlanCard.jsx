import { useState } from "react";
import { Check, CheckCircle2, Sparkles, X } from "lucide-react";

// Shared pricing card used by the registration wizard's plan step and the
// post-login plan selection page. Selectable cards behave like a radio group:
// hovering/focusing lifts the card, and selecting it shows a clear border,
// ring, elevation and check badge before the customer moves on.

export const planCardStyle = (recommended) => ({
  background: "#FFFFFF",
  borderRadius: "16px",
  padding: "28px 24px",
  display: "flex",
  flexDirection: "column",
  gap: "14px",
  border: recommended ? "2px solid #087CC1" : "1.5px solid #E5E7EB",
  boxShadow: recommended ? "0 8px 32px rgba(8,124,193,0.18)" : "0 2px 12px rgba(0,0,0,0.05)",
  position: "relative",
});

export const badgeStyle = {
  position: "absolute", top: "-12px", left: "50%", transform: "translateX(-50%)",
  background: "linear-gradient(135deg, #087CC1, #1596D1)", color: "#FFFFFF",
  fontSize: "11px", fontWeight: "700", padding: "4px 14px", borderRadius: "20px",
  whiteSpace: "nowrap", letterSpacing: "0.03em",
};

export function PlanCapabilityRow({ label, on }) {
  return (
    <li style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "13px", color: on ? "#374151" : "#B0B7C3" }}>
      {on ? (
        <Check size={15} style={{ color: "#10B981", flexShrink: 0 }} />
      ) : (
        <X size={15} style={{ color: "#D1D5DB", flexShrink: 0 }} />
      )}
      <span style={on ? {} : { textDecoration: "line-through" }}>{label}</span>
    </li>
  );
}

function componentLabel(type) {
  return String(type)
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function PlanCard({
  name,
  priceLabel,
  tagline,
  recommended = false,
  badgeLabel = "Recommended plan",
  capabilities,
  features,
  priceComponents,
  scale,
  footer,
  selected = false,
  onSelect,
  disabled = false,
}) {
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const selectable = typeof onSelect === "function" && !disabled;
  const active = selectable && selected;

  const base = planCardStyle(recommended);
  const style = {
    ...base,
    ...(selectable ? { cursor: "pointer", outline: "none", transition: "transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease" } : null),
    border: active ? "2px solid #087CC1" : base.border,
    transform: active
      ? "translateY(-3px) scale(1.01)"
      : hovered && selectable
        ? "translateY(-4px) scale(1.02)"
        : "none",
    boxShadow: active
      ? "0 16px 40px rgba(8,124,193,0.28)"
      : hovered && selectable
        ? "0 14px 34px rgba(15,23,42,0.16)"
        : base.boxShadow,
    ...(focused && selectable ? { outline: "3px solid #93C5FD", outlineOffset: "3px" } : null),
    ...(disabled ? { opacity: 0.7, cursor: "not-allowed" } : null),
  };

  function handleKeyDown(event) {
    if (!selectable) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect();
    }
  }

  return (
    <div
      role={selectable ? "radio" : undefined}
      aria-checked={selectable ? selected : undefined}
      aria-disabled={selectable ? undefined : disabled || undefined}
      tabIndex={selectable ? 0 : undefined}
      onClick={selectable ? onSelect : undefined}
      onKeyDown={handleKeyDown}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      style={style}
    >
      {recommended && (
        <div style={badgeStyle}>
          <Sparkles size={11} style={{ display: "inline", marginRight: 4, marginBottom: -1 }} />
          {badgeLabel}
        </div>
      )}

      {active && (
        <span
          aria-hidden="true"
          title="Selected"
          style={{
            position: "absolute", top: "12px", right: "12px",
            display: "flex", alignItems: "center", justifyContent: "center",
            width: "26px", height: "26px", borderRadius: "999px",
            background: "#087CC1", color: "#FFFFFF",
            boxShadow: "0 4px 12px rgba(8,124,193,0.35)",
          }}
        >
          <CheckCircle2 size={16} />
        </span>
      )}

      <div>
        <div style={{ fontSize: "18px", fontWeight: "700", color: "#111827" }}>{name}</div>
        <div style={{ fontSize: "22px", fontWeight: "800", color: "#087CC1", marginTop: 2 }}>{priceLabel}</div>
        {tagline && (
          <p style={{ fontSize: "12px", color: "#6B7280", marginTop: 6, minHeight: "32px" }}>{tagline}</p>
        )}
      </div>

      {priceComponents && priceComponents.length > 1 && (
        <div style={{ display: "flex", flexDirection: "column", gap: "4px", marginTop: "8px", paddingTop: "8px", borderTop: "1px solid #E2E8F0", fontSize: "13px", color: "#64748B" }}>
          {priceComponents.map((comp) => (
            <div key={comp.component_type} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <span>{componentLabel(comp.component_type)}</span>
              <span style={{ fontWeight: "600", color: "#087CC1" }}>${Number(comp.unit_amount).toFixed(2)}/mo</span>
            </div>
          ))}
        </div>
      )}

      {capabilities && capabilities.length > 0 && (
        <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: "6px" }}>
          {capabilities.map(([label, on]) => (
            <PlanCapabilityRow key={label} label={label} on={on} />
          ))}
        </ul>
      )}

      {features && features.length > 0 && (
        <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: "8px", flexGrow: 1 }}>
          {features.map((feat) => (
            <li key={feat} style={{ display: "flex", alignItems: "center", gap: "8px", fontSize: "14px", color: "#374151" }}>
              <Check size={15} style={{ color: "#10B981", flexShrink: 0 }} />
              {feat}
            </li>
          ))}
        </ul>
      )}

      {scale && scale.length > 0 && (
        <ul style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: "4px", borderTop: "1px solid #F3F4F6", paddingTop: "10px" }}>
          {scale.map((s) => (
            <li key={s} style={{ fontSize: "12px", color: "#4B5563", fontWeight: 500 }}>{s}</li>
          ))}
        </ul>
      )}

      {footer && <div style={{ marginTop: "auto" }}>{footer}</div>}
    </div>
  );
}
