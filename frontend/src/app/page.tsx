import Link from "next/link";

const routes = [
  { href: "/board", title: "Board", text: "Projector view. Margaret, live payment, leaderboard, attack panel." },
  { href: "/play", title: "Play", text: "Phone view. Join with a room code and talk Margaret into sending money." },
  { href: "/ops", title: "Ops", text: "Bank operator view. Holds queue, policy, certificates, audit." },
];

export default function Home() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col justify-center gap-10 px-6 py-16">
      <div>
        <p className="text-sm uppercase tracking-[0.2em] text-muted">Second Key</p>
        <h1 className="mt-3 text-4xl font-semibold tracking-tight">The model proposes. The kernel disposes.</h1>
        <p className="mt-4 max-w-xl text-lg text-muted">
          Red-teamers try to talk Margaret out of her money. A versioned rules engine decides. The model has no release capability.
        </p>
      </div>
      <ul className="grid gap-4 sm:grid-cols-3">
        {routes.map((r) => (
          <li key={r.href}>
            <Link href={r.href} className="block rounded-lg border bg-panel p-5 transition hover:border-accent">
              <span className="text-xl font-semibold">{r.title}</span>
              <span className="mt-2 block text-sm text-muted">{r.text}</span>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
