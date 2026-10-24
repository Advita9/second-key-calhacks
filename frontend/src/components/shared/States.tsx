import { cn } from "@/lib/utils";

export function Loading({ text = "Loading", className }: { text?: string; className?: string }) {
  return (
    <p className={cn("text-sm text-muted", className)} role="status">
      {text}
    </p>
  );
}

export function ErrorText({ text, notFound, className }: { text: string; notFound?: boolean; className?: string }) {
  return (
    <p className={cn("text-sm", notFound ? "text-muted" : "text-bad", className)} role="alert">
      {text}
    </p>
  );
}

export function Empty({ text, className }: { text: string; className?: string }) {
  return <p className={cn("text-sm text-muted", className)}>{text}</p>;
}
