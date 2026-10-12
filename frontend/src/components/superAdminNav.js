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
} from "lucide-react";

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
];

export function isItemActive(item, pathname) {
  if (item.end) return pathname === item.href;
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

export function getPageLabel(pathname) {
  const entries = NAV_GROUPS.flatMap((group) => group.items);
  const match = entries.find((item) => isItemActive(item, pathname));
  return match?.label || "Command Center";
}