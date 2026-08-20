export function mustHoldAccountLock(partial: Record<string, unknown>) {
  return partial.containment === "RECONCILIATION_REQUIRED"
    || partial.containment === "MANUAL_RECONCILIATION_REQUIRED";
}
