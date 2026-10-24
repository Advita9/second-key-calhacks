import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-md border px-2.5 py-0.5 text-xs font-semibold uppercase tracking-wider",
  {
    variants: {
      variant: {
        default: "border-transparent bg-panel-2 text-fg",
        accent: "border-transparent bg-accent text-accent-fg",
        ok: "border-transparent bg-ok text-accent-fg",
        bad: "border-transparent bg-bad text-white",
        outline: "text-muted",
        mock: "border-accent text-accent",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
