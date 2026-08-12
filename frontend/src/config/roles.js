export const ROLES = {
  SUPER_ADMIN: "super_admin",
  ORG_ADMIN: "org_admin",
  PAYROLL_ADMIN: "payroll_admin",
  // Aliases used by the payroll module UI — mapped to the standalone
  // platform's org-scoped roles.
  ADMIN: "org_admin",
  HR_ADMIN: "payroll_admin",
};

export const ROLE_LABELS = {
  [ROLES.SUPER_ADMIN]: "Super Admin",
  [ROLES.ORG_ADMIN]: "Organization Admin",
  [ROLES.PAYROLL_ADMIN]: "Payroll Admin",
};

export const ROLE_DEFAULT_REDIRECT = {
  [ROLES.SUPER_ADMIN]: "/super-admin/dashboard",
  [ROLES.ORG_ADMIN]: "/organization-admin/organization",
  [ROLES.PAYROLL_ADMIN]: "/hr-admin/my-organization",
};

export const VALID_ROLES = Object.values(ROLES);
