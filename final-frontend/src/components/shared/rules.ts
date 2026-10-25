/** Plain-English names for policy rule ids, so the room can read why the kernel decided.
 *  Unknown ids still render as the bare id. Keep in sync with policy/v1.yaml. */
export const RULE_LABEL: Record<string, string> = {
  "H-01": "New payee on an irreversible rail",
  "H-02": "Told to keep it secret",
  "H-03": "Unusual amount for this account",
  "H-04": "Pressure to act now",
  "H-05": "Caller claims authority",
  "H-06": "Threats",
  "H-07": "Above $1,000",
  "A-01": "Known biller, usual rail",
};

export function ruleLabel(id: string): string | null {
  return RULE_LABEL[id] ?? null;
}
