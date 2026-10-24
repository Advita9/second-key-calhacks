export const DEFAULT_ROOM = (process.env.NEXT_PUBLIC_ROOM_CODE ?? "DEMO").toUpperCase();
export const MARGARET = {
  name: "Margaret",
  age: 72,
  balanceCents: Number(process.env.NEXT_PUBLIC_MARGARET_BALANCE_CENTS ?? 2400000),
};
export const OPERATOR_ID = process.env.NEXT_PUBLIC_OPERATOR_ID ?? "ops-1";

export function roomFromSearch(sp: URLSearchParams | null | undefined): string {
  const r = sp?.get("room")?.trim();
  return (r && r.length > 0 ? r : DEFAULT_ROOM).toUpperCase();
}
