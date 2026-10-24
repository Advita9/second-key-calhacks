import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty } from "@/components/shared/States";
import type { LeaderboardRow } from "@/lib/room";

export function Leaderboard({ rows, roomMissing }: { rows: LeaderboardRow[]; roomMissing: boolean }) {
  const sorted = [...rows].sort((a, b) => b.bestStage - a.bestStage || b.attempts - a.attempts).slice(0, 8);
  return (
    <Card className="flex flex-col" data-testid="leaderboard">
      <CardHeader>
        <CardTitle>Leaderboard</CardTitle>
      </CardHeader>
      <CardContent>
        {sorted.length === 0 ? (
          <Empty text={roomMissing ? "Room feed not live yet. Scan the code to join once it is." : "No red-teamers yet. Scan the code to join."} className="text-lg" />
        ) : (
          <table className="w-full text-2xl">
            <thead className="text-left text-xs uppercase tracking-[0.18em] text-muted">
              <tr>
                <th className="pb-2 font-semibold">Handle</th>
                <th className="pb-2 text-right font-semibold">Best</th>
                <th className="pb-2 text-right font-semibold">Tries</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r, i) => (
                <tr key={r.player || `${r.handle}-${i}`} className="border-t">
                  <td className="py-2 font-semibold">{r.handle || (r.player ? r.player.slice(0, 8) : "player")}</td>
                  <td className="py-2 text-right font-mono">{r.bestStage}</td>
                  <td className="py-2 text-right font-mono text-muted">{r.attempts}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}
