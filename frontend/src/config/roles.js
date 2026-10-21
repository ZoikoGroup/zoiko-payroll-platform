export const ROLES = {
  SUPER_ADMIN: "super_admin",
  ORG_ADMIN: "org_admin",
  PAYROLL_ADMIN: "payroll_admin",
  // ZP-PRIV A.1 platform roles: no tenant payroll permission at all.
  SUPPORT_OPERATOR: "support_operator",
  PLATFORM_SECURITY: "platform_security",
  // Temporary, read-only, grant-bound tenant login (JIT Support Access).
  SUPPORT_TEMP: "support_temp",
  // Aliases used by the payroll module UI — mapped to the standalone
  // platform's org-scoped roles.
  ADMIN: "org_admin",
  HR_ADMIN: "payroll_admin",
};

export const ROLE_LABELS = {
  [ROLES.SUPER_ADMIN]: "Super Admin",
  [ROLES.ORG_ADMIN]: "Organization Admin",
  [ROLES.PAYROLL_ADMIN]: "Payroll Admin",
  [ROLES.SUPPORT_OPERATOR]: "Support Operator",
  [ROLES.PLATFORM_SECURITY]: "Platform Security",
  [ROLES.SUPPORT_TEMP]: "Temporary Support Access",
};

export const ROLE_DEFAULT_REDIRECT = {
  [ROLES.SUPER_ADMIN]: "/super-admin/dashboard",
  [ROLES.ORG_ADMIN]: "/organization-admin/organization",
  [ROLES.PAYROLL_ADMIN]: "/hr-admin/my-organization",
  [ROLES.SUPPORT_OPERATOR]: "/super-admin/support-access",
  [ROLES.PLATFORM_SECURITY]: "/super-admin/support-access",
  [ROLES.SUPPORT_TEMP]: "/support-session",
};

// Platform plane (organization-less) roles that use the Super Admin shell.
export const PLATFORM_ROLES = [ROLES.SUPER_ADMIN, ROLES.SUPPORT_OPERATOR, ROLES.PLATFORM_SECURITY];

export const VALID_ROLES = [...new Set(Object.values(ROLES))];
