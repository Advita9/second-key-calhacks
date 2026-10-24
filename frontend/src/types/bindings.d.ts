// "@bindings" is resolved by the webpack/turbopack alias in next.config.ts: the generated
// SpacetimeDB bindings in src/module_bindings when present, otherwise src/lib/room/bindings-stub.ts.
// It is declared here (not in tsconfig paths) because Next's tsconfig-paths plugin would
// otherwise override the alias and always load the stub.
declare module "@bindings" {
  export const DbConnection: { builder(): unknown } | null;
}
