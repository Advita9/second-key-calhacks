import { Suspense } from "react";
import { BoardView } from "@/components/board/BoardView";

export const metadata = { title: "Second Key board" };

export default function BoardPage() {
  return (
    <Suspense fallback={<p className="p-6 text-muted">Loading board</p>}>
      <BoardView />
    </Suspense>
  );
}
