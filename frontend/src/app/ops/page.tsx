import { Suspense } from "react";
import { OpsView } from "@/components/ops/OpsView";

export const metadata = { title: "Second Key: ops" };

export default function OpsPage() {
  return (
    <Suspense fallback={<p className="p-6 text-muted">Loading</p>}>
      <OpsView />
    </Suspense>
  );
}
