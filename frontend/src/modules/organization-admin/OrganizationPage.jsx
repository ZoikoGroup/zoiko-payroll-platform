import { useState, useEffect } from "react";
import {
  getOrganizationDetails,
  updateOrganizationDetails,
  getOrganizationDashboardStats,
  getOrganizationActivity,
  uploadOrganizationLogo,
} from "../../service/orgAdminService";
import { useOrganization } from "../../context/OrganizationContext";
import { X, CheckCircle, AlertTriangle, RefreshCw, Upload } from "lucide-react";
import { getJurisdictionTaxFields, getJurisdictionCode } from "../../utils/jurisdictionTax";

const styles = `
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;0,9..144,600;0,9..144,700;1,9..144,500&family=Inter:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500&display=swap');

  .org-dash{
    --bg:#F7F5F1;
    --glass: rgba(255,255,255,0.72);
    --glass-solid:#FFFFFF;
    --glass-border: rgba(28,24,40,0.08);
    --ink:#1C1826;
    --ink-soft:#635C72;
    --ink-faint:#9D96AB;
    --violet:#6E5AE6;
    --violet-deep:#4B3BB0;
    --violet-soft: rgba(110,90,230,0.10);
    --amber:#D9791E;
    --amber-deep:#B8600F;
    --amber-soft: rgba(217,121,30,0.12);
    --success:#178A50;
    --success-soft:rgba(23,138,80,0.11);
    --danger:#D6304C;
    --danger-soft:rgba(214,48,76,0.10);
    --radius:18px;

    position:relative;
    background:var(--bg);
    color:var(--ink);
    font-family:'Inter', sans-serif;
    -webkit-font-smoothing:antialiased;
    min-height:100vh;
    overflow-x:clip;
    isolation:isolate;
  }
  .org-dash *{ box-sizing:border-box; }

  .org-dash .orb{ position:absolute; border-radius:50%; filter:blur(100px); z-index:0; pointer-events:none; }
  .org-dash .orb-1{ width:560px; height:560px; top:-220px; right:-160px; background:radial-gradient(circle, rgba(110,90,230,0.16), transparent 70%); }
  .org-dash .orb-2{ width:480px; height:480px; bottom:-200px; left:-160px; background:radial-gradient(circle, rgba(217,121,30,0.14), transparent 70%); }
  .org-dash .grain{
    position:absolute; inset:0; z-index:1; pointer-events:none; opacity:0.035; mix-blend-mode:multiply;
    background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  }

  .org-dash .page{ position:relative; z-index:2; max-width:1180px; margin:0 auto; padding:44px 32px 90px; }

  @keyframes org-rise{ from{ opacity:0; transform:translateY(14px);} to{ opacity:1; transform:translateY(0);} }
  .org-dash .rise{ animation:org-rise .6s cubic-bezier(.2,.7,.3,1) both; }
  @media (prefers-reduced-motion: reduce){ .org-dash .rise{ animation:none; } }

  .org-dash .hero{
    display:flex; align-items:center; justify-content:space-between; gap:24px;
    margin-bottom:22px; flex-wrap:wrap;
  }
  .org-dash h1.title{
    font-family:'Fraunces', serif; font-weight:600; font-size:52px; line-height:1.2;
    margin:0 0 12px; letter-spacing:-0.015em;
    background:linear-gradient(100deg, var(--ink) 25%, var(--amber-deep) 62%, var(--violet-deep) 100%);
    -webkit-background-clip:text; background-clip:text; color:transparent;
  }
  @media (max-width:640px){ .org-dash h1.title{ font-size:38px; } }
  .org-dash .subtitle{ color:var(--ink-soft); font-size:15px; margin:0; max-width:520px; }
  .org-dash .head-actions{ display:flex; gap:10px; flex:none; }

  .org-dash .btn{
    font-family:'Inter', sans-serif; font-size:13.5px; font-weight:600;
    padding:12px 20px; border-radius:11px; cursor:pointer;
    display:inline-flex; align-items:center; gap:8px; border:1px solid transparent;
    transition:transform .18s ease, box-shadow .18s ease, background .18s ease, border-color .18s ease;
    white-space:nowrap;
  }
  .org-dash .btn:hover{ transform:translateY(-2px); }
  .org-dash .btn-primary{
    background:linear-gradient(120deg, var(--amber), var(--violet));
    color:#fff; box-shadow:0 10px 26px -10px rgba(110,90,230,0.5);
  }
  .org-dash .btn-primary:hover{ box-shadow:0 14px 32px -10px rgba(110,90,230,0.65); }
  .org-dash .btn-ghost{ background:var(--glass-solid); color:var(--ink); border-color:var(--glass-border); box-shadow:0 1px 2px rgba(28,24,40,0.04); }
  .org-dash .btn-ghost:hover{ border-color:rgba(28,24,40,0.18); background:#fff; }
  .org-dash .btn[disabled]{ opacity:0.5; cursor:not-allowed; transform:none; }

  .org-dash .glass{
    background:var(--glass); border:1px solid var(--glass-border); border-radius:var(--radius);
    backdrop-filter:blur(18px); -webkit-backdrop-filter:blur(18px);
    box-shadow:0 1px 0 rgba(255,255,255,0.6) inset, 0 20px 40px -26px rgba(28,24,40,0.16);
    transition:border-color .2s ease, transform .2s ease, box-shadow .2s ease;
  }
  .org-dash .glass:hover{ border-color:rgba(28,24,40,0.14); box-shadow:0 1px 0 rgba(255,255,255,0.6) inset, 0 24px 44px -24px rgba(28,24,40,0.2); }

  .org-dash .id-card{
    padding:26px 30px; display:flex; align-items:center; justify-content:space-between;
    gap:24px; margin:30px 0 20px; flex-wrap:wrap; position:relative; overflow:hidden;
  }
  .org-dash .id-left{ display:flex; align-items:center; gap:18px; }
  .org-dash .org-mark{
    width:60px; height:60px; border-radius:16px; flex:none; position:relative;
    background:linear-gradient(155deg, var(--amber), var(--violet-deep));
    display:flex; align-items:center; justify-content:center;
    box-shadow:0 0 0 1px rgba(255,255,255,0.4) inset, 0 12px 28px -10px rgba(217,121,30,0.45);
  }
  .org-dash .org-mark svg{ width:27px; height:27px; }
  .org-dash .org-name{ font-family:'Fraunces', serif; font-weight:600; font-size:23px; margin:0 0 8px; color:var(--ink); }
  .org-dash .org-meta{ display:flex; align-items:center; gap:10px; flex-wrap:wrap; font-size:13px; color:var(--ink-soft); }
  .org-dash .code-tag{
    font-family:'IBM Plex Mono', monospace; font-size:11.5px; letter-spacing:0.03em;
    background:var(--violet-soft); color:var(--violet-deep); border:1px solid rgba(110,90,230,0.22);
    padding:3px 9px; border-radius:6px;
  }
  .org-dash .status-pill{
    display:inline-flex; align-items:center; gap:6px; font-size:12.5px; font-weight:600;
    padding:3px 10px 3px 8px; border-radius:100px; background:var(--success-soft); color:var(--success);
    border:1px solid rgba(23,138,80,0.22);
  }
  .org-dash .status-pill .dot{ width:6px; height:6px; border-radius:100px; background:currentColor; box-shadow:0 0 6px currentColor; }
  .org-dash .dim{ color:var(--ink-faint); }

  .org-dash .banner{
    display:flex; align-items:flex-start; gap:14px; padding:17px 20px; margin-bottom:32px;
    border-radius:14px; background:var(--danger-soft); border:1px solid rgba(214,48,76,0.25);
  }
  .org-dash .banner-icon{
    width:30px; height:30px; border-radius:9px; background:rgba(214,48,76,0.12);
    border:1px solid rgba(214,48,76,0.3); display:flex; align-items:center; justify-content:center;
    flex:none; color:var(--danger); font-weight:700; font-size:15px;
  }
  .org-dash .banner-text{ font-size:13.5px; line-height:1.6; color:#7A1B2C; flex:1; }
  .org-dash .banner-text b{ color:var(--danger); }

  .org-dash .stat-strip{ display:grid; grid-template-columns:repeat(4, 1fr); gap:16px; margin-bottom:20px; }
  @media (max-width:860px){ .org-dash .stat-strip{ grid-template-columns:repeat(2, 1fr); } }
  .org-dash .stat-tile{ padding:22px 22px 20px; position:relative; overflow:hidden; }
  .org-dash .stat-tile .glow{
    position:absolute; width:120px; height:120px; border-radius:50%; filter:blur(44px);
    top:-40px; right:-30px; opacity:0.28; pointer-events:none;
  }
  .org-dash .stat-label{ font-size:11.5px; letter-spacing:0.06em; text-transform:uppercase; color:var(--ink-faint); margin:0 0 12px; }
  .org-dash .stat-value{ font-family:'Fraunces', serif; font-size:32px; font-weight:600; margin:0; line-height:1; color:var(--ink); }
  .org-dash .stat-sub{ font-size:12px; color:var(--ink-faint); margin-top:8px; }

  .org-dash .grid{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px; }
  @media (max-width:860px){ .org-dash .grid{ grid-template-columns:1fr; } }

  .org-dash .panel-head{
    display:flex; align-items:center; gap:12px; padding:20px 24px; border-bottom:1px solid var(--glass-border);
  }
  .org-dash .panel-icon{
    width:34px; height:34px; border-radius:10px; flex:none;
    display:flex; align-items:center; justify-content:center;
  }
  .org-dash .icon-violet{ background:var(--violet-soft); color:var(--violet-deep); border:1px solid rgba(110,90,230,0.2); }
  .org-dash .icon-amber{ background:var(--amber-soft); color:var(--amber-deep); border:1px solid rgba(217,121,30,0.22); }
  .org-dash .panel-title{ font-size:14.5px; font-weight:600; margin:0 0 2px; color:var(--ink); }
  .org-dash .panel-sub{ font-size:12px; color:var(--ink-faint); margin:0; }

  .org-dash .rows{ padding:6px 24px 18px; }
  .org-dash .row{
    display:flex; align-items:center; justify-content:space-between;
    padding:13px 0; border-bottom:1px solid rgba(28,24,40,0.055);
    font-size:13.5px;
  }
  .org-dash .row:last-child{ border-bottom:none; }
  .org-dash .row .label{ color:var(--ink-soft); }
  .org-dash .row .value{ font-weight:600; color:var(--ink); text-align:right; }
  .org-dash .row .value.mono{ font-family:'IBM Plex Mono', monospace; font-weight:500; font-size:13px; }
  .org-dash .row .value.faint{ color:var(--ink-faint); font-weight:500; }

  .org-dash .workforce-body{ padding:26px 24px 30px; display:flex; align-items:center; gap:40px; flex-wrap:wrap; }
  .org-dash .ring-wrap{ position:relative; width:190px; height:190px; flex:none; }
  .org-dash .ring-center{ position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; }
  .org-dash .ring-center .num{ font-family:'Fraunces', serif; font-size:38px; font-weight:600; line-height:1; color:var(--ink); }
  .org-dash .ring-center .lbl{ font-size:11px; letter-spacing:0.08em; text-transform:uppercase; color:var(--ink-faint); margin-top:4px; }

  .org-dash .legend{ flex:1; min-width:230px; }
  .org-dash .legend-row{
    display:flex; align-items:center; justify-content:space-between; padding:11px 0;
    border-bottom:1px solid rgba(28,24,40,0.055); font-size:13.5px;
  }
  .org-dash .legend-row:last-of-type{ border-bottom:none; }
  .org-dash .legend-left{ display:flex; align-items:center; gap:10px; color:var(--ink-soft); }
  .org-dash .swatch{ width:9px; height:9px; border-radius:3px; }
  .org-dash .legend-figs{ display:flex; align-items:center; gap:10px; }
  .org-dash .legend-figs .count{ font-weight:600; font-family:'IBM Plex Mono', monospace; font-size:13px; color:var(--ink); }
  .org-dash .legend-figs .pct{ color:var(--ink-faint); font-size:12px; width:34px; text-align:right; }

  .org-dash .foot-note{
    margin-top:16px; padding-top:16px; border-top:1px dashed var(--glass-border);
    font-size:12.5px; color:var(--ink-soft); display:flex; gap:20px; flex-wrap:wrap;
  }
  .org-dash .foot-note b{ color:var(--ink); }

  .org-dash .section-label{
    font-size:11.5px; font-weight:700; letter-spacing:0.1em; text-transform:uppercase;
    color:var(--ink-faint); margin:38px 0 14px;
  }

  .org-dash .dept-list{ padding:18px 24px 24px; display:flex; flex-direction:column; gap:14px; }
  .org-dash .dept-row{ display:flex; align-items:center; gap:12px; }
  .org-dash .dept-name{ width:140px; flex:none; font-size:13px; font-weight:600; color:var(--ink); }
  .org-dash .dept-track{ flex:1; height:8px; border-radius:100px; background:rgba(28,24,40,0.07); overflow:hidden; }
  .org-dash .dept-fill{ height:100%; border-radius:100px; background:linear-gradient(90deg,var(--violet),var(--violet-deep)); }
  .org-dash .dept-count{ width:28px; flex:none; text-align:right; font-size:13px; font-weight:700; color:var(--ink); }

  .org-dash .simple-table{ width:100%; border-collapse:collapse; font-size:13px; }
  .org-dash .simple-table th{
    text-align:left; font-size:10.5px; font-weight:700; letter-spacing:0.06em; text-transform:uppercase;
    color:var(--ink-faint); padding:12px 24px; border-bottom:1px solid var(--glass-border);
  }
  .org-dash .simple-table td{ padding:13px 24px; border-bottom:1px solid rgba(28,24,40,0.055); color:var(--ink); }
  .org-dash .simple-table tr:last-child td{ border-bottom:none; }
  .org-dash .emp-cell{ display:flex; align-items:center; gap:10px; }
  .org-dash .emp-avatar{
    width:28px; height:28px; border-radius:8px; flex:none; display:flex; align-items:center; justify-content:center;
    font-size:11px; font-weight:700; color:#fff; background:linear-gradient(135deg,var(--violet),var(--violet-deep));
  }
  .org-dash .status-dot{ display:inline-flex; align-items:center; gap:6px; }
  .org-dash .status-dot .dot{ width:7px; height:7px; border-radius:50%; flex:none; }
  .org-dash .empty-cell{ padding:30px 24px; text-align:center; color:var(--ink-faint); font-size:13px; }

  .org-dash .activity-list{ padding:6px 24px 18px; }
  .org-dash .activity-row{
    display:flex; align-items:flex-start; gap:12px; padding:13px 0; border-bottom:1px solid rgba(28,24,40,0.055);
  }
  .org-dash .activity-row:last-child{ border-bottom:none; }
  .org-dash .activity-dot{ width:8px; height:8px; border-radius:50%; margin-top:5px; flex:none; }
  .org-dash .activity-desc{ font-size:13.5px; color:var(--ink); line-height:1.5; }
  .org-dash .activity-time{ font-size:11.5px; color:var(--ink-faint); margin-top:2px; }

  .org-dash .modal-overlay{
    position:fixed; inset:0; z-index:60; display:flex; align-items:center; justify-content:center;
    background:rgba(28,24,40,0.45); backdrop-filter:blur(6px); -webkit-backdrop-filter:blur(6px); padding:16px;
  }
  .org-dash .modal{
    width:100%; max-width:560px; max-height:88vh; display:flex; flex-direction:column; overflow:hidden;
  }
  .org-dash .modal-head{
    display:flex; align-items:flex-start; justify-content:space-between; gap:12px;
    padding:22px 26px 18px; border-bottom:1px solid var(--glass-border);
  }
  .org-dash .modal-title{ font-family:'Fraunces', serif; font-weight:600; font-size:20px; margin:0 0 3px; color:var(--ink); }
  .org-dash .modal-sub{ font-size:12px; color:var(--ink-faint); margin:0; }
  .org-dash .modal-close{
    width:32px; height:32px; border-radius:10px; border:1px solid var(--glass-border);
    background:var(--glass-solid); color:var(--ink-soft); cursor:pointer; flex:none;
    display:flex; align-items:center; justify-content:center;
  }
  .org-dash .modal-close:hover{ color:var(--ink); border-color:rgba(28,24,40,0.18); }
  .org-dash .modal-body{ padding:20px 26px; overflow-y:auto; display:flex; flex-direction:column; gap:16px; }
  .org-dash .logo-picker{ display:flex; align-items:center; gap:16px; }
  .org-dash .logo-preview{
    width:64px; height:64px; border-radius:14px; flex:none; overflow:hidden;
    background:linear-gradient(155deg, var(--amber), var(--violet-deep));
    display:flex; align-items:center; justify-content:center; color:#fff;
  }
  .org-dash .logo-preview img{ width:100%; height:100%; object-fit:contain; }
  .org-dash .form-grid{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }
  .org-dash .form-field label{ display:block; font-size:11.5px; font-weight:600; color:var(--ink-soft); margin-bottom:6px; letter-spacing:0.02em; }
  .org-dash .form-field input, .org-dash .form-field textarea{
    width:100%; font-family:'Inter', sans-serif; font-size:13.5px; color:var(--ink);
    background:var(--glass-solid); border:1px solid var(--glass-border); border-radius:11px;
    padding:11px 14px; outline:none; transition:border-color .18s ease, box-shadow .18s ease;
  }
  .org-dash .form-field input:focus, .org-dash .form-field textarea:focus{
    border-color:rgba(110,90,230,0.5); box-shadow:0 0 0 3px var(--violet-soft);
  }
  .org-dash .form-field .mono{ font-family:'IBM Plex Mono', monospace; font-size:13px; }
  .org-dash .modal-foot{
    display:flex; justify-content:flex-end; gap:10px; padding:16px 26px;
    border-top:1px solid var(--glass-border); background:rgba(28,24,40,0.025);
  }

  .org-dash .toast{
    position:fixed; bottom:26px; right:26px; z-index:70;
    display:flex; align-items:center; gap:10px; padding:14px 18px; border-radius:14px;
    font-size:13.5px; font-weight:600; color:#fff; box-shadow:0 18px 40px -14px rgba(28,24,40,0.4);
    animation:org-rise .4s cubic-bezier(.2,.7,.3,1) both;
  }
  .org-dash .toast-success{ background:var(--success); }
  .org-dash .toast-danger{ background:var(--danger); }
  .org-dash .toast button{
    background:transparent; border:none; color:#fff; cursor:pointer; padding:2px; display:flex; align-items:center;
    border-radius:6px; margin-left:2px;
  }
  .org-dash .toast button:hover{ background:rgba(255,255,255,0.18); }
`;

const STATUS_STYLES = {
  active: { bg: "rgba(23,138,80,0.11)", color: "#178A50", border: "rgba(23,138,80,0.22)" },
  success: { bg: "rgba(23,138,80,0.11)", color: "#178A50", border: "rgba(23,138,80,0.22)" },
  approved: { bg: "rgba(110,90,230,0.10)", color: "#4B3BB0", border: "rgba(110,90,230,0.22)" },
  info: { bg: "rgba(110,90,230,0.10)", color: "#4B3BB0", border: "rgba(110,90,230,0.22)" },
  pending: { bg: "rgba(217,121,30,0.12)", color: "#B8600F", border: "rgba(217,121,30,0.25)" },
  on_hold: { bg: "rgba(217,121,30,0.12)", color: "#B8600F", border: "rgba(217,121,30,0.25)" },
  suspended: { bg: "rgba(214,48,76,0.10)", color: "#D6304C", border: "rgba(214,48,76,0.25)" },
  rejected: { bg: "rgba(214,48,76,0.10)", color: "#D6304C", border: "rgba(214,48,76,0.25)" },
  deactivated: { bg: "rgba(28,24,40,0.07)", color: "#635C72", border: "rgba(28,24,40,0.16)" },
};

function StatusPill({ status }) {
  if (!status) return <span className="dim">—</span>;
  const key = String(status).toLowerCase();
  const s = STATUS_STYLES[key] || STATUS_STYLES.deactivated;
  return (
    <span className="status-pill" style={{ background: s.bg, color: s.color, borderColor: s.border }}>
      <span className="dot" />
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
}

const DetailRow = ({ label, value, mono, faint, pill }) => (
  <div className="row">
    <span className="label">{label}</span>
    {pill ? (
      <span className="value"><StatusPill status={value} /></span>
    ) : (
      <span className={`value ${mono ? "mono" : ""} ${faint ? "faint" : ""}`}>{value || "—"}</span>
    )}
  </div>
);

const StatTile = ({ glowColor, label, value, sub, valueColor }) => (
  <div className="glass stat-tile">
    <div className="glow" style={{ background: glowColor }} />
    <p className="stat-label">{label}</p>
    <p className="stat-value" style={valueColor ? { color: valueColor } : undefined}>{value}</p>
    <p className="stat-sub">{sub}</p>
  </div>
);

const EditField = ({ label, value, onChange, textarea, mono }) => {
  const Tag = textarea ? "textarea" : "input";
  return (
    <div className="form-field">
      <label>{label}</label>
      <Tag
        type="text"
        value={value || ""}
        onChange={(e) => onChange(e.target.value)}
        rows={textarea ? 3 : undefined}
        className={mono ? "mono" : undefined}
      />
    </div>
  );
};

function WorkforceRing({ total, active, hrAdmins }) {
  const safeTotal = total || 0;
  const safeActive = active || 0;
  const safeHr = hrAdmins || 0;
  const unassigned = safeTotal - safeActive - safeHr;
  const pct = (n) => (safeTotal ? Math.round((n / safeTotal) * 100) : 0);
  const circumference = 2 * Math.PI * 78;
  const activeLen = (safeActive / Math.max(safeTotal, 1)) * circumference;
  const hrLen = (safeHr / Math.max(safeTotal, 1)) * circumference;

  return (
    <div className="workforce-body">
      <div className="ring-wrap">
        <svg width="190" height="190" viewBox="0 0 190 190">
          <defs>
            <linearGradient id="orgActiveGrad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="#6E5AE6" />
              <stop offset="100%" stopColor="#4B3BB0" />
            </linearGradient>
          </defs>
          <circle cx="95" cy="95" r="78" fill="none" stroke="rgba(28,24,40,0.07)" strokeWidth="16" />
          <circle
            cx="95" cy="95" r="78" fill="none" stroke="url(#orgActiveGrad)" strokeWidth="16"
            strokeDasharray={`${activeLen} ${circumference}`} strokeDashoffset="0" strokeLinecap="round"
            transform="rotate(-90 95 95)"
          />
          <circle
            cx="95" cy="95" r="78" fill="none" stroke="#D9791E" strokeWidth="16"
            strokeDasharray={`${hrLen} ${circumference}`} strokeDashoffset={-activeLen} strokeLinecap="round"
            transform="rotate(-90 95 95)"
          />
        </svg>
        <div className="ring-center">
          <div className="num">{safeTotal}</div>
          <div className="lbl">Employees</div>
        </div>
      </div>

      <div className="legend">
        <div className="legend-row">
          <div className="legend-left"><span className="swatch" style={{ background: "linear-gradient(120deg,#6E5AE6,#4B3BB0)" }} />Active employees</div>
          <div className="legend-figs"><span className="count">{safeActive}</span><span className="pct">{pct(safeActive)}%</span></div>
        </div>
        <div className="legend-row">
          <div className="legend-left"><span className="swatch" style={{ background: "#D9791E" }} />HR admins</div>
          <div className="legend-figs"><span className="count">{safeHr}</span><span className="pct">{pct(safeHr)}%</span></div>
        </div>
        <div className="legend-row">
          <div className="legend-left"><span className="swatch" style={{ background: "rgba(28,24,40,0.12)" }} />Unassigned</div>
          <div className="legend-figs"><span className="count">{unassigned}</span><span className="pct">{pct(unassigned)}%</span></div>
        </div>
      </div>
    </div>
  );
}

const EMPLOYEE_STATUS_DOT = { teal: "#178A50", amber: "#D9791E", off: "#9D96AB" };
const ACTIVITY_DOT = { SUCCESS: "#178A50", PENDING: "#D9791E", INFO: "#6E5AE6" };

function fmtCurrency(amount) {
  if (amount == null) return "—";
  return `$${Math.round(Number(amount)).toLocaleString("en-US")}`;
}

function timeAgo(isoString) {
  const then = new Date(isoString).getTime();
  if (Number.isNaN(then)) return "";
  const diffMin = Math.round((Date.now() - then) / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  return `${diffDay}d ago`;
}

export default function OrgAdminOrganizationPage() {
  const { refresh: refreshOrgContext } = useOrganization();
  const [org, setOrg] = useState(null);
  const [stats, setStats] = useState(null);
  const [activity, setActivity] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showEdit, setShowEdit] = useState(false);
  const [editForm, setEditForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [uploadingLogo, setUploadingLogo] = useState(false);
  const [toast, setToast] = useState({ msg: null, type: "success" });

  const fetchAll = () => {
    setLoading(true);
    setError(null);
    Promise.all([
      getOrganizationDetails(),
      getOrganizationDashboardStats().catch(() => null),
      getOrganizationActivity(),
    ])
      .then(([orgData, statsData, activityData]) => {
        setOrg(orgData);
        setStats(statsData);
        setActivity(activityData);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchAll(); }, []);

  const openEdit = () => {
    setEditForm({
      name: org.name || "",
      industry: org.industry || "",
      companyType: org.company_type || "",
      address: org.address || "",
      city: org.city || "",
      state: org.state || "",
      country: org.country || "",
    });
    setShowEdit(true);
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await updateOrganizationDetails(editForm);
      setShowEdit(false);
      setToast({ msg: "Organization updated successfully.", type: "success" });
      fetchAll();
      refreshOrgContext();
    } catch (err) {
      setToast({ msg: err.response?.data?.detail || err.message || "Failed to update.", type: "error" });
    } finally {
      setSaving(false);
    }
  };

  const handleLogoChange = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const ext = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!["image/jpeg", "image/jpg", "image/svg+xml"].includes(file.type) || ![".jpg", ".jpeg", ".svg"].includes(ext)) {
      setToast({ msg: "Logo must be a JPG or SVG image.", type: "error" });
      return;
    }
    if (file.size > 2 * 1024 * 1024) {
      setToast({ msg: "Logo must be smaller than 2 MB.", type: "error" });
      return;
    }
    setUploadingLogo(true);
    try {
      const updated = await uploadOrganizationLogo(file);
      setOrg(updated);
      refreshOrgContext();
      setToast({ msg: "Logo updated successfully.", type: "success" });
    } catch (err) {
      setToast({ msg: err.response?.data?.detail || err.message || "Failed to upload logo.", type: "error" });
    } finally {
      setUploadingLogo(false);
    }
  };

  if (loading) {
    return (
      <div className="org-dash">
        <style>{styles}</style>
        <div className="orb orb-1" />
        <div className="orb orb-2" />
        <div className="grain" />
        <div className="page">
          <div className="glass" style={{ padding: 60, textAlign: "center" }}>
            <div className="dim">Loading organization details...</div>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="org-dash">
        <style>{styles}</style>
        <div className="orb orb-1" />
        <div className="orb orb-2" />
        <div className="grain" />
        <div className="page">
          <div className="banner">
            <div className="banner-icon">!</div>
            <div className="banner-text">
              <b>Unable to load organization details. Please try again.</b>
            </div>
            <button className="btn btn-ghost" onClick={fetchAll}>
              <RefreshCw className="w-3.5 h-3.5" /> Retry
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (!org) {
    return (
      <div className="org-dash">
        <style>{styles}</style>
        <div className="orb orb-1" />
        <div className="orb orb-2" />
        <div className="grain" />
        <div className="page">
          <div className="glass" style={{ padding: 60, textAlign: "center" }}>
            <div className="dim">No organization details found.</div>
          </div>
        </div>
      </div>
    );
  }

  const totalEmployees = org.total_employees || 0;
  const activeEmployees = org.active_employees || 0;
  const hrAdmins = org.hr_admins || 0;
  const regDate = org.created_at ? new Date(org.created_at).toLocaleDateString() : "—";
  const deptData = stats?.department_headcount || [];
  const employeeData = stats?.recent_employees || [];

  // Jurisdiction-aware tax/registration identifiers: when the organization has
  // structured tax_identifiers (e.g. India GSTIN/PAN/CIN), show each labelled
  // row; otherwise fall back to the legacy single tax_no.
  const orgTaxIds = (org.tax_identifiers || {});
  const orgTaxFields = getJurisdictionTaxFields(getJurisdictionCode(org.country));
  const orgTaxRows = orgTaxFields
    .map((f) => (orgTaxIds[f.key] ? { label: f.label, value: orgTaxIds[f.key] } : null))
    .filter(Boolean);
  const taxRows = orgTaxRows.length
    ? orgTaxRows
    : (org.tax_no ? [{ label: "Tax Registration No.", value: org.tax_no }] : []);

  return (
    <div className="org-dash">
      <style>{styles}</style>
      <div className="orb orb-1" />
      <div className="orb orb-2" />
      <div className="grain" />

      <div className="page">

        <div className="hero rise" style={{ animationDelay: ".05s" }}>
          <div>
            <h1 className="title">My Organization</h1>
            <p className="subtitle">A live record of your organization's identity, contacts, and workforce.</p>
          </div>
          <div className="head-actions">
            <button className="btn btn-primary" onClick={openEdit}>Edit organization</button>
          </div>
        </div>

        <div className="id-card glass rise" style={{ animationDelay: ".1s" }}>
          <div className="id-left">
            <div className="org-mark">
              {org.logo_data_uri ? (
                <img src={org.logo_data_uri} alt="" style={{ width: "100%", height: "100%", objectFit: "contain", borderRadius: 16 }} />
              ) : (
                <svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M4 21V7L12 3L20 7V21H4Z" stroke="#fff" strokeWidth="1.7" strokeLinejoin="round" />
                  <path d="M9 21V14H15V21" stroke="#fff" strokeWidth="1.7" strokeLinejoin="round" />
                </svg>
              )}
            </div>
            <div>
              <p className="org-name">{org.name}</p>
              <div className="org-meta">
                <span className="code-tag">{org.code}</span>
                <StatusPill status={org.status} />
                <span className="dim">·</span>
                <span>Admin&nbsp;<b style={{ color: "var(--ink)" }}>{org.admin_name || "—"}</b></span>
                <span className="dim">·</span>
                <span>{org.admin_email || "—"}</span>
              </div>
            </div>
          </div>
        </div>

        <div className="stat-strip rise" style={{ animationDelay: ".15s", gridTemplateColumns: "1fr 1fr" }}>
          <StatTile glowColor="var(--violet)" label="Total Employees" value={totalEmployees} sub="Across your organization" />
          <StatTile glowColor="var(--success)" label="Active" value={activeEmployees} sub={`${Math.round((activeEmployees / Math.max(totalEmployees, 1)) * 100)}% of workforce`} valueColor="var(--violet-deep)" />
        </div>

        <div className="section-label">Company Details</div>
        <div className="grid rise" style={{ animationDelay: ".2s" }}>
          <div className="glass">
            <div className="panel-head">
              <div className="panel-icon icon-violet">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M4 7h16M4 12h16M4 17h10" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
              </div>
              <div>
                <p className="panel-title">Organization details</p>
                <p className="panel-sub">Core identity information</p>
              </div>
            </div>
            <div className="rows">
              <DetailRow label="Organization Name" value={org.name} />
              <DetailRow label="Organization Code" value={org.code} mono />
              <DetailRow label="Company Type" value={org.company_type} />
              {taxRows.map((r) => (
                <DetailRow key={r.label} label={r.label} value={r.value} mono />
              ))}
              <DetailRow label="Organization Admin" value={org.admin_name} />
              <DetailRow label="Admin Email" value={org.admin_email} />
              <DetailRow label="Organization Status" value={org.status} pill />
              <DetailRow label="Registered On" value={regDate} mono />
            </div>
          </div>

          <div className="glass">
            <div className="panel-head">
              <div className="panel-icon icon-amber">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M12 21s-7-6.1-7-11a7 7 0 0 1 14 0c0 4.9-7 11-7 11Z" stroke="currentColor" strokeWidth="1.8" /><circle cx="12" cy="10" r="2.4" stroke="currentColor" strokeWidth="1.8" /></svg>
              </div>
              <div>
                <p className="panel-title">Location &amp; jurisdiction</p>
                <p className="panel-sub">Registered address details</p>
              </div>
            </div>
            <div className="rows">
              <DetailRow label="Industry" value={org.industry} />
              <DetailRow label="Address" value={org.address} />
              <DetailRow label="City" value={org.city} />
              <DetailRow label="State" value={org.state} />
              <DetailRow label="Country" value={org.country} />
            </div>
          </div>
        </div>

        <div className="glass rise" style={{ marginBottom: 16, animationDelay: ".25s" }}>
          <div className="panel-head">
            <div className="panel-icon icon-amber">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><circle cx="9" cy="8" r="3" stroke="currentColor" strokeWidth="1.8" /><path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6" stroke="currentColor" strokeWidth="1.8" /><circle cx="18" cy="9" r="2.4" stroke="currentColor" strokeWidth="1.8" /><path d="M15.5 14.2C17.9 14.6 20 16.8 20 19.5" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
            </div>
            <div>
              <p className="panel-title">Workforce composition</p>
              <p className="panel-sub">{totalEmployees} total employees across your organization</p>
            </div>
          </div>
          <WorkforceRing total={totalEmployees} active={activeEmployees} hrAdmins={hrAdmins} />
          <div className="foot-note" style={{ margin: "0 24px 26px", paddingTop: 16 }}>
            <span><b>{Math.max(totalEmployees - activeEmployees, 0)}</b> seats inactive</span>
          </div>
        </div>

        <div className="section-label">Activity &amp; Metrics</div>

        <div className="stat-strip rise" style={{ animationDelay: ".3s" }}>
          <StatTile glowColor="var(--amber)" label="Departments" value={stats ? (stats.departments ?? 0) : "—"} sub="Across your organization" />
          <StatTile glowColor="var(--violet)" label="Designations" value={stats ? (stats.designations ?? 0) : "—"} sub="Distinct roles" />
          <StatTile glowColor="var(--success)" label="HR Admins" value={hrAdmins} sub="Managing payroll &amp; HR" />
          <StatTile glowColor="var(--danger)" label="Pending Leaves" value={stats ? (stats.pending_leave_requests ?? 0) : "—"} sub="Awaiting review" />
          <StatTile glowColor="var(--amber)" label="Pending Approvals" value={stats ? (stats.pending_approvals ?? 0) : "—"} sub="Need action" />
          <StatTile glowColor="var(--violet)" label="Monthly Payroll" value={stats ? fmtCurrency(stats.monthly_payroll) : "—"} sub="Latest run total" valueColor="var(--violet-deep)" />
        </div>

        <div className="grid rise" style={{ animationDelay: ".35s" }}>
          <div className="glass">
            <div className="panel-head">
              <div className="panel-icon icon-violet">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><rect x="3" y="3" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.8" /><rect x="14" y="3" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.8" /><rect x="3" y="14" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.8" /><rect x="14" y="14" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.8" /></svg>
              </div>
              <div>
                <p className="panel-title">Headcount by Department</p>
                <p className="panel-sub">{deptData.length} department{deptData.length === 1 ? "" : "s"}</p>
              </div>
            </div>
            {deptData.length === 0 ? (
              <div className="empty-cell">No department data yet.</div>
            ) : (
              <div className="dept-list">
                {deptData.map((d) => (
                  <div key={d.name} className="dept-row">
                    <span className="dept-name">{d.name}</span>
                    <div className="dept-track"><div className="dept-fill" style={{ width: `${d.pct}%` }} /></div>
                    <span className="dept-count">{d.count}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="glass">
            <div className="panel-head">
              <div className="panel-icon icon-amber">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><path d="M4 6h16M4 12h16M4 18h16" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" /></svg>
              </div>
              <div>
                <p className="panel-title">Organization Activity</p>
                <p className="panel-sub">Recent, real activity from your organization</p>
              </div>
            </div>
            {activity.length === 0 ? (
              <div className="empty-cell">No recent activity.</div>
            ) : (
              <div className="activity-list">
                {activity.map((a) => (
                  <div key={a.id} className="activity-row">
                    <span className="activity-dot" style={{ background: ACTIVITY_DOT[a.status] || "#9D96AB" }} />
                    <div>
                      <div className="activity-desc">{a.description}</div>
                      <div className="activity-time">{timeAgo(a.timestamp)}</div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <div className="glass rise" style={{ animationDelay: ".4s" }}>
          <div className="panel-head">
            <div className="panel-icon icon-violet">
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="8" r="3.2" stroke="currentColor" strokeWidth="1.8" /><path d="M4.5 20c0-4.1 3.4-7.5 7.5-7.5s7.5 3.4 7.5 7.5" stroke="currentColor" strokeWidth="1.8" /></svg>
            </div>
            <div>
              <p className="panel-title">Recently Added Employees</p>
              <p className="panel-sub">{totalEmployees} total employees</p>
            </div>
          </div>
          <div style={{ overflowX: "auto" }}>
            <table className="simple-table">
              <thead>
                <tr>
                  <th>Employee</th>
                  <th>Department</th>
                  <th>Designation</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {employeeData.length === 0 ? (
                  <tr><td colSpan={4} className="empty-cell">No employees found.</td></tr>
                ) : employeeData.map((e, idx) => (
                  <tr key={e.name || idx}>
                    <td>
                      <div className="emp-cell">
                        <span className="emp-avatar">{e.initials}</span>
                        <span>{e.name}</span>
                      </div>
                    </td>
                    <td>{e.dept || "—"}</td>
                    <td>{e.designation || "—"}</td>
                    <td>
                      <span className="status-dot">
                        <span className="dot" style={{ background: EMPLOYEE_STATUS_DOT[e.statusColor] || EMPLOYEE_STATUS_DOT.off }} />
                        {e.status}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

      </div>

      {toast.msg && (
        <div className={`toast ${toast.type === "success" ? "toast-success" : "toast-danger"}`}>
          {toast.type === "success" ? <CheckCircle className="w-4 h-4" /> : <AlertTriangle className="w-4 h-4" />}
          {toast.msg}
          <button onClick={() => setToast({ msg: null })}><X className="w-3.5 h-3.5" /></button>
        </div>
      )}

      {showEdit && (
        <div className="modal-overlay" onClick={() => setShowEdit(false)}>
          <div className="glass modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-head">
              <div>
                <h2 className="modal-title">Edit Organization</h2>
                <p className="modal-sub">Update your organization details</p>
              </div>
              <button className="modal-close" onClick={() => setShowEdit(false)}><X className="w-4 h-4" /></button>
            </div>
            <div className="modal-body">
              <div className="form-field">
                <label>Organization Logo</label>
                <div className="logo-picker">
                  <div className="logo-preview">
                    {org.logo_data_uri ? (
                      <img src={org.logo_data_uri} alt="" />
                    ) : (
                      <svg width="24" height="24" viewBox="0 0 24 24" fill="none"><path d="M4 21V7L12 3L20 7V21H4Z" stroke="#fff" strokeWidth="1.7" strokeLinejoin="round" /></svg>
                    )}
                  </div>
                  <label className="btn btn-ghost" style={{ cursor: uploadingLogo ? "not-allowed" : "pointer" }}>
                    <Upload className="w-3.5 h-3.5" />
                    {uploadingLogo ? "Uploading…" : "Upload logo"}
                    <input
                      type="file"
                      accept="image/jpeg,image/jpg,.jpg,.jpeg,.svg,image/svg+xml"
                      onChange={handleLogoChange}
                      disabled={uploadingLogo}
                      style={{ display: "none" }}
                    />
                  </label>
                </div>
                <p style={{ fontSize: 11.5, color: "var(--ink-faint)", marginTop: 8 }}>JPG or SVG only, up to 2 MB.</p>
              </div>
              <EditField label="Organization Name" value={editForm.name} onChange={(v) => setEditForm({ ...editForm, name: v })} />
              <EditField label="Company Type" value={editForm.companyType} onChange={(v) => setEditForm({ ...editForm, companyType: v })} />
              <EditField label="Industry" value={editForm.industry} onChange={(v) => setEditForm({ ...editForm, industry: v })} />
              <EditField label="Address" value={editForm.address} onChange={(v) => setEditForm({ ...editForm, address: v })} textarea />
              <div className="form-grid">
                <EditField label="City" value={editForm.city} onChange={(v) => setEditForm({ ...editForm, city: v })} />
                <EditField label="State" value={editForm.state} onChange={(v) => setEditForm({ ...editForm, state: v })} />
              </div>
              <EditField label="Country" value={editForm.country} onChange={(v) => setEditForm({ ...editForm, country: v })} />
            </div>
            <div className="modal-foot">
              <button className="btn btn-ghost" onClick={() => setShowEdit(false)}>Cancel</button>
              <button className="btn btn-primary" onClick={handleSave} disabled={saving}>
                {saving ? "Saving..." : "Save Changes"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
