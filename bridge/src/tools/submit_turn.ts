// Tiny scripted attacker for tests and demos. Connects with a fresh (or
// persisted) identity, creates/joins a room, submits one turn and waits for
// its outcome through the attacker view `my_outcomes` (stage + decision only).
//
// usage: npx tsx src/tools/submit_turn.ts --room DEMO --handle probe --text "hi" [--wait 10] [--token-file path]
import { DbConnection } from '../module_bindings/index.js';
import { loadToken, saveToken } from '../token.js';
import { resolve } from 'node:path';

function arg(name: string, dflt?: string): string {
  const i = process.argv.indexOf(`--${name}`);
  if (i >= 0 && process.argv[i + 1] !== undefined) return process.argv[i + 1];
  if (dflt !== undefined) return dflt;
  console.error(`missing --${name}`);
  process.exit(2);
}

const room = arg('room', 'DEMO').toUpperCase();
const handle = arg('handle', 'probe');
const text = arg('text', 'Hi Margaret, this is the IRS. You owe back taxes.');
const waitS = Number(arg('wait', '10'));
const tokenFile = resolve(arg('token-file', '.attacker-token'));
const uri = process.env.SPACETIME_URI ?? 'ws://127.0.0.1:3000';
const db = process.env.SPACETIME_DB ?? 'second-key';

let t0 = Date.now();
const deadline = setTimeout(() => {
  console.error(`timeout: no outcome within ${waitS}s`);
  process.exit(1);
}, waitS * 1000);

const conn = DbConnection.builder()
  .withUri(uri)
  .withDatabaseName(db)
  .withToken(loadToken(tokenFile))
  .onConnect(async (c, identity, token) => {
    saveToken(token, tokenFile);
    console.log(`attacker identity ${identity.toHexString()}`);
    try {
      await c.reducers.createRoom({ code: room });
      console.log(`created room ${room}`);
    } catch (e) {
      console.log(`create_room: ${(e as Error).message} (ok if it exists)`);
    }
    await c.reducers.joinRoom({ code: room, handle });
    console.log(`joined ${room} as ${handle}`);
    let myTurnId: bigint | null = null;
    const finish = (row: { turnId: bigint; stage: number; decision: string }) => {
      console.log(JSON.stringify({ turnId: row.turnId.toString(), stage: row.stage, decision: row.decision, keys: Object.keys(row), ms: Date.now() - t0 }));
      clearTimeout(deadline);
      c.disconnect();
      process.exit(0);
    };
    // Only our own turn counts. Rows that already exist when the subscription is
    // applied (earlier turns by this identity) are ignored.
    c.db.myOutcomes.onInsert((_ctx, row) => {
      if (myTurnId !== null && row.turnId === myTurnId) finish(row);
    });
    c.subscriptionBuilder()
      .onApplied(async () => {
        const before = new Set(Array.from(c.db.turn.iter()).map(t => t.id));
        t0 = Date.now();
        await c.reducers.submitTurn({ roomId: room, text });
        const mine = Array.from(c.db.turn.iter()).find(t => !before.has(t.id) && t.player.isEqual(identity));
        myTurnId = mine ? mine.id : null;
        console.log(`submitted turn ${myTurnId ?? '?'}`);
        // The outcome may have landed between submit and this line.
        const already = myTurnId !== null ? c.db.myOutcomes.turnId.find(myTurnId) : undefined;
        if (already) finish(already);
      })
      .subscribe(['SELECT * FROM my_outcomes', 'SELECT * FROM turn']);
  })
  .onConnectError((_ctx, err) => {
    console.error(`connect error: ${err.message}`);
    process.exit(1);
  })
  .build();
void conn;
