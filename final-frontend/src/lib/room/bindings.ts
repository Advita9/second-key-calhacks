// SpacetimeDB bindings for the room. Until bindings are generated this exports null and the app
// uses the kernel memory room (the default).
//
// To use SpacetimeDB: run spacetime/scripts/gen-bindings.sh so src/module_bindings exists, then
// replace the line below with:
//   export { DbConnection } from "@/module_bindings";
export const DbConnection: null = null;
