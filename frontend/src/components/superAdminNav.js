import {
  LayoutDashboard,
  Building2,
  Users,
  Settings,
  Wallet,
  FileBarChart,
  ShieldCheck,
  Landmark,
  ScrollText,
  Layers,
  CreditCard,
  PlayCircle,
  FileText,
  AlertTriangle,
  Activity,
  Plug,
  ShieldAlert,
  FileSignature,
  CircleDollarSign,
  Bell,
  LifeBuoy,
  ScanSearch,
  Fingerprint,
  Bot,
  ClipboardCheck,
  Siren,
} from "lucide-react";

// ZP-PRIV E: security readers (server: get_current_security_reader).
const SECURITY_READERS = ["platform_security"];  // removed from Super Admin (owner request)

// Same grouped enterprise-nav format as the Organization Admin sidebar
// (components/PayrollShell.jsx) — short section labels, few items each.
// Shared by SuperAdminShell (sidebar) and CommandPalette (quick search).
export const NAV_GROUPS = [
  {
    title: "Overview",
    items: [
      { label: "Command Center", href: "/super-admin/dashboard", icon: LayoutDashboard, end: true },
      { label: "Alerts & Incidents", href: "/super-admin/alerts", icon: Bell },
    ],
  },
  {
    title: "Organizations",
    items: [
      { label: "Organizations", href: "/super-admin/organizations", icon: Building2 },
      { label: "Users", href: "/super-admin/users", icon: Users },
    ],
  },
  {
    title: "Compliance",
    items: [
      { label: "Jurisdictions", href: "/super-admin/compliance", icon: ShieldCheck },
      { label: "Rules & Rates", href: "/super-admin/statutory-rates", icon: Landmark },
    ],
  },
  {
    title: "Reporting",
    items: [
      { label: "Reports", href: "/super-admin/reports", icon: FileBarChart },
      { label: "Report Templates", href: "/super-admin/report-templates", icon: ScrollText },
    ],
  },
  {
    title: "System",
    items: [{ label: "Settings", href: "/super-admin/settings", icon: Settings }],
  },
  {
    title: "Zoiko Commercial",
    items: [
      { label: "Plans & Entitlements", href: "/super-admin/plans-entitlements", icon: Layers },
      { label: "Revenue & Collections", href: "/super-admin/revenue-collections", icon: CircleDollarSign },
      { label: "Subscriptions & Billing", href: "/super-admin/subscriptions-billing", icon: CreditCard },
      { label: "Order Forms", href: "/super-admin/order-forms", icon: FileSignature },
    ],
  },
  {
    title: "Payroll Operations",
    items: [
      { label: "Funding & Payments", href: "/super-admin/finance", icon: Wallet },
      { label: "Payroll Runs", href: "/super-admin/payroll-runs", icon: PlayCircle },
      { label: "Filings & Remittances", href: "/super-admin/filings-remittances", icon: FileText },
      { label: "Exceptions & Reconciliation", href: "/super-admin/exceptions-reconciliation", icon: AlertTriangle },
    ],
  },
  {
    title: "Platform",
    items: [
      { label: "Service Health", href: "/super-admin/service-health", icon: Activity },
      { label: "Integrations", href: "/super-admin/integrations", icon: Plug },
      { label: "Security & Audit", href: "/super-admin/security-audit", icon: ShieldAlert },
    ],
  },
  {
    title: "Security & privacy",
    items: [
      { label: "Audit Explorer", href: "/super-admin/audit-explorer", icon: ScanSearch, roles: SECURITY_READERS },
      // Super Admin reaches the same tabs through "Alerts & Incidents" above.
      { label: "Security Alerts", href: "/super-admin/alerts", icon: Siren, roles: ["platform_security"] },
      { label: "Privileged Inventory", href: "/super-admin/privileged-inventory", icon: Fingerprint, roles: SECURITY_READERS },
      { label: "Machine Clients", href: "/super-admin/machine-clients", icon: Bot, roles: SECURITY_READERS },
      { label: "Privacy Assurance", href: "/super-admin/privacy-assurance", icon: ClipboardCheck, roles: SECURITY_READERS },
    ],
  },
  {
    title: "Access",
    items: [
      // ZP-PRIV Part D: the only route to worker data for any Zoiko staff role.
      { label: "Support Access", href: "/super-admin/support-access", icon: LifeBuoy, roles: ["super_admin", "support_operator", "platform_security"] },
    ],
  },
];

// Nav items a role may use. Items without `roles` are Super Admin only; the
// server enforces the same rule (route policy), this just hides dead links.
export function navGroupsFor(role) {
  return NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => (item.roles ? item.roles.includes(role) : role === "super_admin")),
  })).filter((group) => group.items.length > 0);
}

export function isItemActive(item, pathname) {
  if (item.end) return pathname === item.href;
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

export function getPageLabel(pathname) {
  const entries = NAV_GROUPS.flatMap((group) => group.items);
  const match = entries.find((item) => isItemActive(item, pathname));
  return match?.label || "Command Center";
}