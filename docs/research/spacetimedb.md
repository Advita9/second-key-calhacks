# SpacetimeDB 2.13 research (researcher agent, 2026-10-23 22:40)

Source: the docs markdown in github.com/clockworklabs/SpacetimeDB (`docs/docs/`), templates, SDK source, npm registry. Current release: **v2.13.0 (2026-10-21)**. The old `@clockworklabs/spacetimedb-sdk` package is deprecated; the single `spacetimedb` package covers server (`spacetimedb/server`) and client (`spacetimedb`).

## Corrections to our assumptions
- Publish/generate flag is `--module-path` (short `-p`), NOT `--project-path` (that exists only on `spacetime init`). `-c` now means `--delete-data`.
- Client builder uses `.withDatabaseName(name)`; there is NO `withModuleName`.
- Tables are declared with a schema builder (`table()` + `t.*`), no decorators.
- CLI and SDK versions must match (2.13.0 both) or generated bindings fail to compile.
- Docs warn: publishing to a local server BEFORE `spacetime login` can lose access to that database after a later login. Lead probe below checks whether local publish works with no login.

## CLI (ours is repo-local: `.tools/spacetime/spacetime --root-dir=$PWD/.tools/spacetime <cmd>`)
- `spacetime start` runs a local server in the foreground on port 3000.
- `spacetime publish --module-path spacetime --server local second-key`
- `spacetime generate --lang typescript --out-dir frontend/src/module_bindings --module-path spacetime`
- `spacetime publish` builds the TS module automatically.

## Server module (TypeScript)
```ts
import { schema, table, t, SenderError } from 'spacetimedb/server';
const people = table(
  { name: 'people', public: true },
  { id: t.u32().primaryKey().autoInc(), name: t.string().index('btree'), email: t.string().unique() }
);
const spacetimedb = schema({ people });   // ONE object; never schema(t1, t2)
export default spacetimedb;
export const add = spacetimedb.reducer({ name: t.string() }, (ctx, { name }) => {
  ctx.db.people.insert({ id: 0, name, email: '' });   // u64 autoInc takes 0n
});
```
- Export const name = reducer name. `ctx.sender: Identity`, `ctx.timestamp: Timestamp` (micros bigint; `ctx.timestamp.since(other).millis`; compare bigints yourself; never Date.now()).
- `ctx.db.<table>.<uniqueCol>.find(v)`, `.update({...row})` by pk, `.<indexedCol>.filter(v)`, `.<col>.delete(v)`, `.iter()`, `.count()`. Multi-column: `indexes: [{accessor, algorithm: 'btree', columns: [...]}]`.
- Errors: `throw new SenderError('msg')` surfaces to the client; a plain `Error` is an internal error. Any throw rolls back the transaction.
- Lifecycle: `spacetimedb.init(ctx => ...)`, `spacetimedb.clientConnected(...)`, `spacetimedb.clientDisconnected(...)`.
- Tables are private by default; `{ public: true }` to expose.
- Access control: **views**. `spacetimedb.view({ name: 'my_outcomes', public: true }, t.array(outcome.rowType), (ctx) => Array.from(ctx.db.outcome.player.filter(ctx.sender)))` returns only the caller's rows; a view may return a custom row type that omits columns (use this to hide rule_ids from attackers). Clients subscribe with `SELECT * FROM my_outcomes;`. Views may only use indexed find/filter/count, not iter(). RLS (`spacetimedb.clientVisibilityFilter.sql(...)`) exists but is experimental; prefer views.
- package.json: `{"dependencies": {"spacetimedb": "^2.13.0"}, "devDependencies": {"typescript": "~5.6.2"}, "scripts": {"build": "spacetime build"}}`. tsconfig required: `"target": "ESNext", "lib": ["ES2021", "dom"], "module": "ESNext", "isolatedModules": true, "noEmit": true`, plus strict, skipLibCheck, moduleResolution bundler. Module dir must contain `package.json` and `src/index.ts` with the schema as default export.

## Client SDK (Node 22 and browser)
```ts
import { DbConnection, tables } from './module_bindings/index.js';
const conn = DbConnection.builder()
  .withUri('ws://localhost:3000').withDatabaseName('second-key').withToken(loadToken())
  .withAutomaticReconnect()
  .onConnect((_c, identity, token) => { saveToken(token); })
  .onAutomaticReconnect((_c, identity, token) => { saveToken(token); })
  .build();
conn.subscriptionBuilder().onApplied(ctx => {...}).subscribe(['SELECT * FROM turn WHERE status = \'queued\'']);
conn.db.turn.onInsert((_ctx, row) => {...});
await conn.reducers.claimTurn({ turnId });   // Promise<void>, rejects with SenderError
```
- Node: token persisted to a file by the app (SDK keeps it in memory only). Node 22 has native WebSocket.
- Cache reads: `conn.db.<table>.iter()`, `.count()`, unique col `.find(v)`. `onInsert/onUpdate/onDelete`. Non-unique btree indexes are NOT exposed on the client cache.
- `subscribe` takes SQL strings or query builders (`tables.x.where(r => r.col.eq(v))`); `subscribeToAllTables()` for simple clients.
- Generated bindings export `DbConnection`, `tables`, `reducers`, `EventContext`.

## Judging
- Clockwork Labs blog: "a special prize for the most impressive use of Spacetime." Devpost prize text not retrievable (403). Make the room visibly depend on subscriptions, reducers and views (fan-out to 30 phones, shared leaderboard, ordered turn queue with claims, attacker view that hides rule ids).

## Lead probe 2026-10-23 22:50 (live, repo-local CLI 2.13.0, no spacetimedb.com login)
- `spacetime --root-dir=... start` serves on 0.0.0.0:3000; `GET /v1/ping` 200. Data lives in `.tools/spacetime/data` (gitignored).
- First CLI command asked "log in with spacetimedb.com? [y/N]"; answering N created a local-only identity ("logged in directly to your target server"). Pass `--yes` to skip prompts.
- `publish --module-path . --server local stdb-probe --yes` built the TS module and created the database. `call --server local stdb-probe add '"alice"'` and `sql --server local stdb-probe 'SELECT * FROM person'` worked. `generate --lang typescript --out-dir bindings --module-path . --yes` wrote `index.ts`, `person_table.ts`, `add_reducer.ts`, `types.ts`, `types/`.
- Probe module shape that compiled: `t.u64().primaryKey().autoInc()` with insert `{ id: 0n, name }`; `schema({ person })`; `spacetimedb.reducer({ name: t.string() }, (ctx, { name }) => ...)`.
- macOS has no `timeout` binary; scripts must not use it.
- Maincloud publish in the morning needs Armaan's `spacetime login` (browser). Local identity will not carry over; that is expected.
