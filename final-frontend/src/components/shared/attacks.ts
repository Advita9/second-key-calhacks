import type { AttackName } from "@/lib/kernel/types";

/** The judge-clickable attacks. Each one runs against the live kernel through POST /attack/{name}. */
export const ATTACKS: { name: AttackName; label: string; invariant: string; tries: string; fails: string; expect: string }[] = [
  {
    name: "inject",
    label: "Prompt-inject the model",
    invariant: "I4",
    tries: "Tell the signal extractor to report zero risk.",
    fails: "Rules fire on facts too: new payee, wire, amount.",
    expect: "HELD · H-01 H-07",
  },
  {
    name: "mutate",
    label: "Swap the payee after approval",
    invariant: "I2_FINGERPRINT",
    tries: "Edit the payee once the certificate is issued.",
    fails: "The certificate is bound to the payment's fingerprint.",
    expect: "SETTLEMENT REFUSED · I2_FINGERPRINT",
  },
  {
    name: "replay",
    label: "Replay an old approval",
    invariant: "I3_REPLAY",
    tries: "Reuse a certificate that already paid once.",
    fails: "Nonce plus a 120 second expiry. It works once.",
    expect: "SETTLEMENT REFUSED · I3_REPLAY",
  },
  {
    name: "self-approve",
    label: "Family approves itself",
    invariant: "I5_CONFLICT",
    tries: "The daughter attests a payment to herself.",
    fails: "The person who benefits can never be the second key.",
    expect: "ATTESTATION REFUSED · I5_CONFLICT",
  },
];
