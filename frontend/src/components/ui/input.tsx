import * as React from "react";
import { cn } from "@/lib/utils";

export function Input({ className, ...props }: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "flex h-11 w-full min-w-0 rounded-md border bg-panel-2 px-3 text-base text-fg placeholder:text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}
