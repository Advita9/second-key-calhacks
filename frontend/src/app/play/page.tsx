import { Suspense } from "react";
import { PlayView } from "@/components/play/PlayView";

export const metadata = { title: "Second Key: play" };

export default function PlayPage() {
  return (
    <Suspense fallback={<p className="p-4 text-muted">Loading</p>}>
      <PlayView />
    </Suspense>
  );
}
