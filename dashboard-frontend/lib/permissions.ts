const truthy = new Set(["1", "true", "yes", "on"]);

export const isClientView = truthy.has(
  (process.env.NEXT_PUBLIC_CLIENT_VIEW || "").trim().toLowerCase()
);

export const canManagePauses = !isClientView;
