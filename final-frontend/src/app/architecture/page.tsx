import { Architecture } from "@/components/arch/Architecture";
import { Logo } from "@/components/brand/Logo";
import { LinkButton } from "@/components/ui";

export const metadata = { title: "Second Key: how it works" };

/** Full-screen architecture for the pitch: put this on the projector before the live board. */
export default function ArchitecturePage() {
  return (
    <main className="mx-auto flex min-h-screen max-w-[1600px] flex-col gap-6 px-6 py-6 md:px-10">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <a href="/" aria-label="Second Key home">
          <Logo sub="How it works" />
        </a>
        <div className="flex items-center gap-3">
          <p className="hidden text-[15px] text-ink-2 md:block">The model proposes. The kernel disposes.</p>
          <LinkButton href="/board">Open live board</LinkButton>
        </div>
      </header>
      <Architecture />
    </main>
  );
}
