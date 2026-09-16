/**
 * modules/organization-admin/SubscriptionPage.jsx
 * ------------------------------------------------
 * Organization Admin subscription dashboard — shows current plan,
 * billing status, Stripe integration, and upgrade options.
 *
 * Route: /organization-admin/subscription (org_admin)
 *        /hr-admin/subscription (payroll_admin)
 */

import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../../context/AuthContext";
import { ROLES } from "../../config/roles";
import {
  getMySubscription,
  listPublishedPlans,
  createCheckoutSession,
} from "../../service/billingService";
import {
  X,
  CheckCircle,
  AlertTriangle,
  RefreshCw,
  CreditCard,
  Calendar,
  ArrowRight,
  Zap,
  ShieldCheck,
  Loader2,
  ExternalLink,
  Package,
  FileText,
} from "lucide-react";

const styles = `
  @import url('https://fonts.googleapis.com/css2?family=Fraunces:ital,opsz,wght@0,9..144,400;0,9..144,500;0,9..144,600;0,9..144,700;1,9..144,500&family=Inter:wght@400;500;600;700;800&family=IBM+Plex+Mono:wght@400;500&display=swap');

  .sub-page{
    --bg:#F7F5F1;
    --glass: rgba(255,255,255,0.72);
    --glass-solid:#FFFFFF;
    --glass-border: rgba(28,24,40,0.08);
    --ink:#1C1826;
    --ink-soft:#635C72;
    --ink-faint:#9D96AB;
    --accent:#087CC1;
    --accent-deep:#0B3554;
    --accent-soft: rgba(8,124,193,0.10);
    --amber:#D9791E;
    --amber-deep:#B8600F;
    --amber-soft: rgba(217,121,30,0.12);
    --success:#178A50;
    --success-soft:rgba(23,138,80,0.11);
    --danger:#D6304C;
    --danger-soft:rgba(214,48,76,0.10);
    --muted:#635C72;
    --muted-soft:rgba(28,24,40,0.07);
    --muted-border:rgba(28,24,40,0.16);
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
  .sub-page *{ box-sizing:border-box; }

  .dark .sub-page{
    --bg:#1A1816;
    --glass: rgba(34,29,26,0.72);
    --glass-solid:#221D1A;
    --glass-border:#38312D;
    --ink:#F0EDE8;
    --ink-soft:#A69B93;
    --ink-faint:#756B64;
    --muted:#A69B93;
    --muted-soft:rgba(240,237,232,0.08);
    --muted-border:rgba(240,237,232,0.14);
  }
  .dark .sub-page .btn-ghost:hover{ background:var(--glass-solid); }
  .dark .sub-page .glass{
    box-shadow:0 1px 0 rgba(255,255,255,0.05) inset, 0 20px 40px -26px rgba(0,0,0,0.4);
  }
  .dark .sub-page .glass:hover{
    box-shadow:0 1px 0 rgba(255,255,255,0.05) inset, 0 24px 44px -24px rgba(0,0,0,0.5);
  }

  .sub-page .orb{ position:absolute; border-radius:50%; filter:blur(100px); z-index:0; pointer-events:none; }
  .sub-page .orb-1{ width:560px; height:560px; top:-220px; right:-160px; background:radial-gradient(circle, rgba(8,124,193,0.16), transparent 70%); }
  .sub-page .orb-2{ width:480px; height:480px; bottom:-200px; left:-160px; background:radial-gradient(circle, rgba(217,121,30,0.14), transparent 70%); }
  .sub-page .grain{
    position:absolute; inset:0; z-index:1; pointer-events:none; opacity:0.035; mix-blend-mode:multiply;
    background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='2' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
  }

  .sub-page .page{ position:relative; z-index:2; max-width:1180px; margin:0 auto; padding:44px 32px 90px; }

  @keyframes sub-rise{ from{ opacity:0; transform:translateY(14px);} to{ opacity:1; transform:translateY(0);} }
  .sub-page .rise{ animation:sub-rise .6s cubic-bezier(.2,.7,.3,1) both; }
  @media (prefers-reduced-motion: reduce){ .sub-page .rise{ animation:none; } }

  .sub-page .hero{
    display:flex; align-items:center; justify-content:space-between; gap:24px;
    margin-bottom:22px; flex-wrap:wrap;
  }
  .sub-page h1.title{
    font-family:'Fraunces', serif; font-weight:600; font-size:52px; line-height:1.2;
    margin:0 0 12px; letter-spacing:-0.015em;
    background:linear-gradient(100deg, var(--ink) 25%, var(--amber-deep) 62%, var(--accent-deep) 100%);
    -webkit-background-clip:text; background-clip:text; color:transparent;
  }
  @media (max-width:640px){ .sub-page h1.title{ font-size:38px; } }
  .sub-page .subtitle{ color:var(--ink-soft); font-size:15px; margin:0; max-width:520px; }
  .sub-page .head-actions{ display:flex; gap:10px; flex:none; }

  .sub-page .btn{
    font-family:'Inter', sans-serif; font-size:13.5px; font-weight:600;
    padding:12px 20px; border-radius:11px; cursor:pointer;
    display:inline-flex; align-items:center; gap:8px; border:1px solid transparent;
    transition:transform .18s ease, box-shadow .18s ease, background .18s ease, border-color .18s ease;
    white-space:nowrap;
  }
  .sub-page .btn:hover{ transform:translateY(-2px); }
  .sub-page .btn-primary{
    background:linear-gradient(120deg, var(--amber), var(--accent));
    color:#fff; box-shadow:0 10px 26px -10px rgba(8,124,193,0.5);
  }
  .sub-page .btn-primary:hover{ box-shadow:0 14px 32px -10px rgba(8,124,193,0.65); }
  .sub-page .btn-ghost{ background:var(--glass-solid); color:var(--ink); border-color:var(--glass-border); box-shadow:0 1px 2px rgba(28,24,40,0.04); }
  .sub-page .btn-ghost:hover{ border-color:rgba(28,24,40,0.18); background:#fff; }
  .sub-page .btn[disabled]{ opacity:0.5; cursor:not-allowed; transform:none; }
  .sub-page .btn-danger{
    background:var(--danger-soft); color:var(--danger); border-color:rgba(214,48,76,0.25);
  }
  .sub-page .btn-danger:hover{ background:rgba(214,48,76,0.18); }

  .sub-page .glass{
    background:var(--glass); border:1px solid var(--glass-border); border-radius:var(--radius);
    backdrop-filter:blur(18px); -webkit-backdrop-filter:blur(18px);
    box-shadow:0 1px 0 rgba(255,255,255,0.6) inset, 0 20px 40px -26px rgba(28,24,40,0.16);
    transition:border-color .2s ease, transform .2s ease, box-shadow .2s ease;
  }
  .sub-page .glass:hover{ border-color:rgba(28,24,40,0.14); box-shadow:0 1px 0 rgba(255,255,255,0.6) inset, 0 24px 44px -24px rgba(28,24,40,0.2); }

  .sub-page .panel-head{
    display:flex; align-items:center; gap:12px; padding:20px 24px; border-bottom:1px solid var(--glass-border);
  }
  .sub-page .panel-icon{
    width:34px; height:34px; border-radius:10px; flex:none;
    display:flex; align-items:center; justify-content:center;
  }
  .sub-page .icon-violet{ background:var(--accent-soft); color:var(--accent-deep); border:1px solid rgba(8,124,193,0.2); }
  .sub-page .icon-amber{ background:var(--amber-soft); color:var(--amber-deep); border:1px solid rgba(217,121,30,0.22); }
  .sub-page .icon-success{ background:var(--success-soft); color:var(--success); border:1px solid rgba(23,138,80,0.22); }
  .sub-page .icon-danger{ background:var(--danger-soft); color:var(--danger); border:1px solid rgba(214,48,76,0.25); }
  .sub-page .panel-title{ font-size:14.5px; font-weight:600; margin:0 0 2px; color:var(--ink); }
  .sub-page .panel-sub{ font-size:12px; color:var(--ink-faint); margin:0; }

  .sub-page .rows{ padding:6px 24px 18px; }
  .sub-page .row{
    display:flex; align-items:center; justify-content:space-between;
    padding:13px 0; border-bottom:1px solid rgba(28,24,40,0.055);
    font-size:13.5px;
  }
  .sub-page .row:last-child{ border-bottom:none; }
  .sub-page .row .label{ color:var(--ink-soft); }
  .sub-page .row .value{ font-weight:600; color:var(--ink); text-align:right; }
  .sub-page .row .value.mono{ font-family:'IBM Plex Mono', monospace; font-weight:500; font-size:13px; }
  .sub-page .row .value.faint{ color:var(--ink-faint); font-weight:500; }

  .sub-page .status-pill{
    display:inline-flex; align-items:center; gap:6px; font-size:12.5px; font-weight:600;
    padding:3px 10px 3px 8px; border-radius:100px; background:var(--success-soft); color:var(--success);
    border:1px solid rgba(23,138,80,0.22);
  }
  .sub-page .status-pill .dot{ width:6px; height:6px; border-radius:100px; background:currentColor; box-shadow:0 0 6px currentColor; }

  .sub-page .plan-card{
    padding:26px 30px; position:relative; overflow:hidden;
  }
  .sub-page .plan-badge{
    display:inline-flex; align-items:center; gap:6px; font-size:11px; font-weight:700;
    padding:4px 12px; border-radius:100px; background:linear-gradient(135deg, var(--accent), var(--accent-deep));
    color:#fff; margin-bottom:16px; letter-spacing:0.04em; text-transform:uppercase;
  }
  .sub-page .plan-name{
    font-family:'Fraunces', serif; font-weight:600; font-size:28px; margin:0 0 8px; color:var(--ink);
  }
  .sub-page .plan-price{
    font-family:'Fraunces', serif; font-size:36px; font-weight:700; color:var(--accent-deep); margin:0 0 4px;
  }
  .sub-page .plan-price span{ font-size:16px; font-weight:500; color:var(--ink-faint); }
  .sub-page .plan-period{ font-size:13px; color:var(--ink-faint); margin:0 0 20px; }

  .sub-page .feature-grid{
    display:grid; grid-template-columns:repeat(auto-fill, minmax(200px, 1fr)); gap:12px;
    padding:0 24px 24px;
  }
  .sub-page .feature-item{
    display:flex; align-items:center; gap:10px; padding:12px 14px;
    background:var(--glass-solid); border:1px solid var(--glass-border); border-radius:12px;
    font-size:13px; color:var(--ink);
  }
  .sub-page .feature-item .icon{
    width:28px; height:28px; border-radius:8px; flex:none;
    display:flex; align-items:center; justify-content:center;
    background:var(--success-soft); color:var(--success);
  }

  .sub-page .grid{ display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px; }
  @media (max-width:860px){ .sub-page .grid{ grid-template-columns:1fr; } }

  .sub-page .stat-strip{ display:grid; grid-template-columns:repeat(3, 1fr); gap:16px; margin-bottom:20px; }
  @media (max-width:860px){ .sub-page .stat-strip{ grid-template-columns:repeat(2, 1fr); } }
  .sub-page .stat-tile{ padding:22px 22px 20px; position:relative; overflow:hidden; }
  .sub-page .stat-tile .glow{
    position:absolute; width:120px; height:120px; border-radius:50%; filter:blur(44px);
    top:-40px; right:-30px; opacity:0.28; pointer-events:none;
  }
  .sub-page .stat-label{ font-size:11.5px; letter-spacing:0.06em; text-transform:uppercase; color:var(--ink-faint); margin:0 0 12px; }
  .sub-page .stat-value{ font-family:'Fraunces', serif; font-size:32px; font-weight:600; margin:0; line-height:1; color:var(--ink); }
  .sub-page .stat-sub{ font-size:12px; color:var(--ink-faint); margin-top:8px; }

  .sub-page .plans-grid{
    display:grid; grid-template-columns:repeat(auto-fill, minmax(260px, 1fr)); gap:16px;
    padding:20px 24px 24px;
  }
  .sub-page .plan-option{
    padding:20px; border-radius:14px; border:2px solid var(--glass-border);
    background:var(--glass-solid); cursor:pointer; transition:all .2s ease;
    display:flex; flex-direction:column; gap:12px;
  }
  .sub-page .plan-option:hover{ border-color:var(--accent); transform:translateY(-2px); }
  .sub-page .plan-option.current{ border-color:var(--success); background:var(--success-soft); }
  .sub-page .plan-option .plan-opt-name{ font-weight:700; font-size:16px; color:var(--ink); }
  .sub-page .plan-option .plan-opt-price{ font-family:'Fraunces', serif; font-size:24px; font-weight:700; color:var(--accent-deep); }
  .sub-page .plan-option .plan-opt-price span{ font-size:13px; font-weight:500; color:var(--ink-faint); }
  .sub-page .plan-option .plan-opt-features{ font-size:12px; color:var(--ink-soft); line-height:1.6; }

  .sub-page .empty-state{
    padding:60px 24px; text-align:center;
  }
  .sub-page .empty-state .icon-wrap{
    width:64px; height:64px; border-radius:16px; margin:0 auto 20px;
    display:flex; align-items:center; justify-content:center;
    background:var(--accent-soft); color:var(--accent);
  }
  .sub-page .empty-state h3{ font-family:'Fraunces', serif; font-size:20px; font-weight:600; margin:0 0 8px; color:var(--ink); }
  .sub-page .empty-state p{ font-size:14px; color:var(--ink-soft); margin:0 0 24px; max-width:400px; margin-left:auto; margin-right:auto; }

  .sub-page .toast{
    position:fixed; bottom:26px; right:26px; z-index:70;
    display:flex; align-items:center; gap:10px; padding:14px 18px; border-radius:14px;
    font-size:13.5px; font-weight:600; color:#fff; box-shadow:0 18px 40px -14px rgba(28,24,40,0.4);
    animation:sub-rise .4s cubic-bezier(.2,.7,.3,1) both;
  }
  .sub-page .toast-success{ background:var(--success); }
  .sub-page .toast-danger{ background:var(--danger); }
  .sub-page .toast button{
    background:transparent; border:none; color:#fff; cursor:pointer; padding:2px; display:flex; align-items:center;
    border-radius:6px; margin-left:2px;
  }
  .sub-page .toast button:hover{ background:rgba(255,255,255,0.18); }

  .sub-page .banner{
    display:flex; align-items:flex-start; gap:14px; padding:17px 20px; margin-bottom:32px;
    border-radius:14px; background:var(--danger-soft); border:1px solid rgba(214,48,76,0.25);
  }
  .sub-page .banner-icon{
    width:30px; height:30px; border-radius:9px; background:rgba(214,48,76,0.12);
    border:1px solid rgba(214,48,76,0.3); display:flex; align-items:center; justify-content:center;
    flex:none; color:var(--danger); font-weight:700; font-size:15px;
  }
  .sub-page .banner-text{ font-size:13.5px; line-height:1.6; color:#7A1B2C; flex:1; }
  .sub-page .banner-text b{ color:var(--danger); }
`;

const STATUS_STYLES = {
  ACTIVE: { bg: "rgba(23,138,80,0.11)", color: "#178A50", border: "rgba(23,138,80,0.22)" },
  TRIALING: { bg: "rgba(8,124,193,0.10)", color: "#0B3554", border: "rgba(8,124,193,0.22)" },
  PAST_DUE: { bg: "rgba(217,121,30,0.12)", color: "#B8600F", border: "rgba(217,121,30,0.25)" },
  SUSPENDED: { bg: "rgba(214,48,76,0.10)", color: "#D6304C", border: "rgba(214,48,76,0.25)" },
  CANCELLED: { bg: "var(--muted-soft)", color: "var(--muted)", border: "var(--muted-border)" },
};

function StatusPill({ status }) {
  if (!status) return <span style={{ color: "var(--ink-faint)" }}>—</span>;
  const key = String(status).toUpperCase();
  const s = STATUS_STYLES[key] || STATUS_STYLES.CANCELLED;
  return (
    <span className="status-pill" style={{ background: s.bg, color: s.color, borderColor: s.border }}>
      <span className="dot" />
      {status.charAt(0).toUpperCase() + status.slice(1).toLowerCase()}
    </span>
  );
}

const DetailRow = ({ label, value, mono, faint }) => (
  <div className="row">
    <span className="label">{label}</span>
    <span className={`value ${mono ? "mono" : ""} ${faint ? "faint" : ""}`}>{value || "—"}</span>
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

function formatDate(iso) {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function daysUntil(iso) {
  if (!iso) return null;
  const diff = new Date(iso).getTime() - Date.now();
  return Math.ceil(diff / 86400000);
}

function getPriceLabel(plan) {
  if (plan.monthly_price_usd === 0) return "Free";
  if (plan.monthly_price_usd > 0) return `$${plan.monthly_price_usd}`;
  return "Contact";
}

const PLAN_ICONS = {
  CORE: Package,
  PROFESSIONAL: Zap,
  BUSINESS: ShieldCheck,
  ENTERPRISE: FileText,
};

export default function SubscriptionPage() {
  const navigate = useNavigate();
  const { role } = useAuth();
  const canManage = role === ROLES.ORG_ADMIN;
  const [subscription, setSubscription] = useState(null);
  const [entitlements, setEntitlements] = useState({});
  const [plans, setPlans] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [checkoutLoading, setCheckoutLoading] = useState(null);
  const [toast, setToast] = useState({ msg: null, type: "success" });

  const fetchAll = () => {
    setLoading(true);
    setError(null);
    Promise.all([
      getMySubscription()
        .then((d) => d, (e) => (e.status === 404 ? null : Promise.reject(e))),
      listPublishedPlans()
        .then((d) => d, (e) => (e.status === 404 ? [] : Promise.reject(e))),
    ])
      .then(([subData, plansData]) => {
        if (subData?.subscription) {
          setSubscription(subData.subscription);
          setEntitlements(subData.entitlement_flags || {});
        }
        setPlans(plansData || []);
      })
      .catch((err) => setError(err.message || "Failed to load subscription data."))
      .finally(() => setLoading(false));
  };

  useEffect(() => { fetchAll(); }, []);

  const handleUpgrade = async (planCode) => {
    setCheckoutLoading(planCode);
    try {
      const { checkout_url } = await createCheckoutSession(planCode);
      window.location.href = checkout_url;
    } catch (err) {
      setToast({
        msg: err.response?.data?.detail || err.message || "Could not start checkout.",
        type: "error",
      });
      setCheckoutLoading(null);
    }
  };

  if (loading) {
    return (
      <div className="sub-page">
        <style>{styles}</style>
        <div className="orb orb-1" />
        <div className="orb orb-2" />
        <div className="grain" />
        <div className="page">
          <div className="glass" style={{ padding: 60, textAlign: "center" }}>
            <div style={{ color: "var(--ink-faint)" }}>Loading subscription details...</div>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="sub-page">
        <style>{styles}</style>
        <div className="orb orb-1" />
        <div className="orb orb-2" />
        <div className="grain" />
        <div className="page">
          <div className="banner">
            <div className="banner-icon">!</div>
            <div className="banner-text">
              <b>Unable to load subscription details. Please try again.</b>
            </div>
            <button className="btn btn-ghost" onClick={fetchAll}>
              <RefreshCw className="w-3.5 h-3.5" /> Retry
            </button>
          </div>
        </div>
      </div>
    );
  }

  const hasSubscription = !!subscription;
  const isCancelled = subscription?.status === "CANCELLED";

  const currentPlan = hasSubscription
    ? plans.find((p) => p.plan_version_id === subscription.plan_version_id) || null
    : null;
  const currentPlanCode = currentPlan?.code || null;
  const daysLeft = daysUntil(subscription?.current_period_end);
  const entitlementList = Object.entries(entitlements).filter(
    ([key, val]) => key !== "plan_code" && val !== undefined && val !== null && val !== 0
  );

  return (
    <div className="sub-page">
      <style>{styles}</style>
      <div className="orb orb-1" />
      <div className="orb orb-2" />
      <div className="grain" />

      <div className="page">
        {/* Hero */}
        <div className="hero rise" style={{ animationDelay: ".05s" }}>
          <div>
            <h1 className="title">Subscription</h1>
            <p className="subtitle">
              {hasSubscription
                ? "Manage your plan, billing, and Stripe subscription."
                : "No active subscription. Choose a plan to get started."}
            </p>
          </div>
          <div className="head-actions">
            {canManage && (
            <button className="btn btn-ghost" onClick={() => navigate("/billing/plans")}>
              <ExternalLink className="w-3.5 h-3.5" /> View All Plans
            </button>
          )}
          </div>
        </div>

        {/* Current Subscription Status */}
        {hasSubscription ? (
          <>
            {/* Status + Period Stats */}
            <div className="stat-strip rise" style={{ animationDelay: ".1s" }}>
              <StatTile
                glowColor="var(--accent)"
                label="Status"
                value={<StatusPill status={subscription.status} />}
                sub="Current subscription status"
              />
              <StatTile
                glowColor="var(--success)"
                label="Days Remaining"
                value={daysLeft !== null ? Math.max(0, daysLeft) : "—"}
                sub={subscription.current_period_end ? `Until ${formatDate(subscription.current_period_end)}` : "No end date"}
              />
              <StatTile
                glowColor="var(--amber)"
                label="Billing Period"
                value={subscription.billing_authority === "STANDALONE" ? "Monthly" : subscription.billing_authority}
                sub="Subscription interval"
              />
            </div>

            {/* Plan Details Card */}
            <div className="glass plan-card rise" style={{ animationDelay: ".15s", marginBottom: 16 }}>
              <div className="panel-head" style={{ borderBottom: "none", paddingBottom: 0 }}>
                <div className="panel-icon icon-violet">
                  <CreditCard size={16} />
                </div>
                <div>
                  <p className="panel-title">Current Plan</p>
                  <p className="panel-sub">Your active subscription details</p>
                </div>
              </div>

              <div style={{ padding: "0 24px 24px" }}>
                <div className="plan-badge">
                  <Zap size={12} />
                  {currentPlanCode || "UNKNOWN"} Plan
                </div>
                <h2 className="plan-name">
                  {currentPlan?.name || currentPlanCode || "No Plan"}
                </h2>
                <p className="plan-price">
                  {currentPlan ? getPriceLabel(currentPlan) : "—"}
                  <span>/month</span>
                </p>
                <p className="plan-period">
                  {subscription.current_period_start && subscription.current_period_end
                    ? `${formatDate(subscription.current_period_start)} — ${formatDate(subscription.current_period_end)}`
                    : "Billing period details unavailable"}
                </p>
              </div>

              {/* Feature Grid */}
              {entitlementList.length > 0 && (
                <div className="feature-grid">
                  {entitlementList.slice(0, 8).map(([key, val]) => (
                    <div key={key} className="feature-item">
                      <div className="icon">
                        <CheckCircle size={14} />
                      </div>
                      <span>
                        {key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                        {typeof val === "number" && val > 0 ? `: ${val}` : ""}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Subscription Details Grid */}
            <div className="grid rise" style={{ animationDelay: ".2s" }}>
              <div className="glass">
                <div className="panel-head">
                  <div className="panel-icon icon-amber">
                    <Calendar size={16} />
                  </div>
                  <div>
                    <p className="panel-title">Billing Details</p>
                    <p className="panel-sub">Subscription timeline and identifiers</p>
                  </div>
                </div>
                <div className="rows">
                  <DetailRow label="Subscription ID" value={`#${subscription.id}`} mono />
                  <DetailRow label="Organization ID" value={subscription.organization_id} mono />
                  <DetailRow label="Status" value={subscription.status} />
                  <DetailRow label="Billing Authority" value={subscription.billing_authority} />
                  <DetailRow label="Period Start" value={formatDate(subscription.current_period_start)} mono />
                  <DetailRow label="Period End" value={formatDate(subscription.current_period_end)} mono />
                </div>
              </div>

              <div className="glass">
                <div className="panel-head">
                  <div className="panel-icon icon-success">
                    <ShieldCheck size={16} />
                  </div>
                  <div>
                    <p className="panel-title">Stripe Integration</p>
                    <p className="panel-sub">Payment processor details</p>
                  </div>
                </div>
                <div className="rows">
                  <DetailRow
                    label="Stripe Subscription"
                    value={subscription.stripe_subscription_id || "—"}
                    mono
                  />
                  <DetailRow label="Plan Version ID" value={subscription.plan_version_id} mono />
                  <DetailRow label="Created" value={formatDate(subscription.created_at)} mono />
                  <DetailRow label="Last Updated" value={formatDate(subscription.updated_at)} mono />
                </div>
              </div>
            </div>

            {/* Upgrade CTA — org_admin only */}
            {canManage && !isCancelled && (
              <div className="glass rise" style={{ animationDelay: ".25s", marginBottom: 16 }}>
                <div className="panel-head">
                  <div className="panel-icon icon-amber">
                    <ArrowRight size={16} />
                  </div>
                  <div>
                    <p className="panel-title">Need more power?</p>
                    <p className="panel-sub">Upgrade your plan to unlock additional features</p>
                  </div>
                </div>
                <div style={{ padding: "16px 24px 20px" }}>
                  <button className="btn btn-primary" onClick={() => navigate("/billing/plans")}>
                    <Zap className="w-3.5 h-3.5" /> Upgrade Plan
                  </button>
                </div>
              </div>
            )}

            {/* Read-only note for non-org-admins */}
            {!canManage && !isCancelled && (
              <div className="glass rise" style={{ animationDelay: ".25s", marginBottom: 16 }}>
                <div className="panel-head">
                  <div className="panel-icon icon-amber">
                    <ArrowRight size={16} />
                  </div>
                  <div>
                    <p className="panel-title">View only</p>
                    <p className="panel-sub">Only your organization admin can change plans</p>
                  </div>
                </div>
              </div>
            )}
          </>
        ) : (
          /* No Subscription — Empty State */
          <div className="glass rise" style={{ animationDelay: ".1s", marginBottom: 16 }}>
            <div className="empty-state">
              <div className="icon-wrap">
                <CreditCard size={28} />
              </div>
              <h3>No Active Subscription</h3>
              <p>
                You don't have an active subscription yet. Choose a plan to unlock
                full payroll features for your organization.
              </p>
              {canManage ? (
                <button className="btn btn-primary" onClick={() => navigate("/billing/plans")}>
                  <Zap className="w-3.5 h-3.5" /> Choose a Plan
                </button>
              ) : (
                <p style={{ fontSize: 13, color: "var(--ink-faint)" }}>
                  Your organization admin can set up a plan for you.
                </p>
              )}
            </div>
          </div>
        )}

        {/* Available Plans Preview */}
        {plans.length > 0 && (
          <div className="glass rise" style={{ animationDelay: ".3s" }}>
            <div className="panel-head">
              <div className="panel-icon icon-violet">
                <Package size={16} />
              </div>
              <div>
                <p className="panel-title">Available Plans</p>
                <p className="panel-sub">{plans.length} plan{plans.length === 1 ? "" : "s"} available</p>
              </div>
            </div>
            <div className="plans-grid">
              {plans.map((plan) => {
                const isCurrent = plan.code === currentPlanCode;
                const Icon = PLAN_ICONS[plan.code] || Package;
                const isLoading = checkoutLoading === plan.code;

                return (
                  <div
                    key={plan.plan_id}
                    className={`plan-option ${isCurrent ? "current" : ""}`}
                  >
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <div
                        style={{
                          width: 32,
                          height: 32,
                          borderRadius: 8,
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          background: isCurrent ? "var(--success-soft)" : "var(--accent-soft)",
                          color: isCurrent ? "var(--success)" : "var(--accent)",
                        }}
                      >
                        <Icon size={16} />
                      </div>
                      <div>
                        <div className="plan-opt-name">{plan.name || plan.code}</div>
                        {isCurrent && (
                          <span style={{ fontSize: 10, fontWeight: 700, color: "var(--success)", textTransform: "uppercase", letterSpacing: "0.06em" }}>
                            Current Plan
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="plan-opt-price">
                      {getPriceLabel(plan)}<span>/mo</span>
                    </div>
                    <div className="plan-opt-features">
                      {(() => {
                        const flags = plan.entitlement_flags || {};
                        const list = Array.isArray(flags)
                          ? flags
                          : Object.entries(flags).map(([feature_key, limit_value]) => ({ feature_key, limit_value }));
                        return list
                          .filter((f) => f.limit_value !== 0)
                          .slice(0, 3)
                          .map((f) => f.feature_key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()))
                          .join(" · ") || "Contact us for details";
                      })()}
                    </div>
                    {canManage && !isCurrent && (
                      <button
                        className="btn btn-primary"
                        style={{ width: "100%", marginTop: 8, padding: "10px 16px" }}
                        onClick={() => handleUpgrade(plan.code)}
                        disabled={checkoutLoading !== null}
                      >
                        {isLoading ? (
                          <>
                            <Loader2 size={14} className="animate-spin" />
                            Redirecting...
                          </>
                        ) : (
                          <>
                            Choose {plan.name || plan.code}
                            <ArrowRight size={14} />
                          </>
                        )}
                      </button>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {toast.msg && (
        <div className={`toast ${toast.type === "success" ? "toast-success" : "toast-danger"}`}>
          {toast.type === "success" ? <CheckCircle className="w-4 h-4" /> : <AlertTriangle className="w-4 h-4" />}
          {toast.msg}
          <button onClick={() => setToast({ msg: null })}><X className="w-3.5 h-3.5" /></button>
        </div>
      )}
    </div>
  );
}
