import { projects } from "./data/projects";

function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <div className="pointer-events-none absolute inset-0 -z-10 bg-grid [background-size:28px_28px]" />
      <div className="pointer-events-none absolute left-1/2 top-0 -z-10 h-[32rem] w-[32rem] -translate-x-1/2 rounded-full bg-cyan-500/20 blur-3xl" />

      <main className="mx-auto max-w-7xl px-6 py-14 lg:px-10">
        <section className="mb-14 rounded-3xl border border-slate-800/90 bg-slate-900/60 p-8 shadow-glow backdrop-blur md:p-12">
          <span className="inline-flex rounded-full border border-cyan-400/40 bg-cyan-500/10 px-3 py-1 text-xs font-semibold tracking-wide text-cyan-300">
            BCI 2026 CLASS PORTFOLIO
          </span>
          <h1 className="mt-5 text-4xl font-black tracking-tight text-white md:text-6xl">
            Brain-Computer Interface Projects
          </h1>
          <p className="mt-4 max-w-3xl text-lg text-slate-300">
            A curated showcase of our class work across EEG, EOG, EMG, real-time control, and
            embedded systems. Each team card links directly to source code, implementation method,
            and demo media.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Metric label="Teams" value="7" />
            <Metric label="Projects" value="7" />
            <Metric label="Domains" value="EEG · EOG · EMG · SSVEP" />
          </div>
        </section>

        <section className="grid gap-6 md:grid-cols-2 xl:grid-cols-3">
          {projects.map((project) => (
            <article
              key={project.team}
              className="group rounded-2xl border border-slate-800 bg-slate-900/65 p-6 shadow-glow transition duration-300 hover:-translate-y-1 hover:border-cyan-400/40"
            >
              <p className="text-sm font-semibold uppercase tracking-widest text-cyan-300">
                {project.team}
              </p>
              <h2 className="mt-2 text-2xl font-bold text-white">{project.title}</h2>
              <p className="mt-3 text-sm leading-6 text-slate-300">{project.summary}</p>

              <div className="mt-4">
                <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">
                  Team Members
                </p>
                <p className="mt-1 text-sm text-slate-200">{project.members.join(" · ")}</p>
              </div>

              <div className="mt-4 flex flex-wrap gap-2">
                {project.tags.map((tag) => (
                  <span
                    key={tag}
                    className="rounded-full border border-slate-700/80 bg-slate-800/80 px-2.5 py-1 text-xs text-slate-200"
                  >
                    {tag}
                  </span>
                ))}
              </div>

              <div className="mt-6 flex flex-wrap gap-2">
                <Action href={project.code} label="Code" />
                <Action href={project.method} label="Method" />
                <Action href={project.video} label="Video" />
              </div>
            </article>
          ))}
        </section>
      </main>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="rounded-xl border border-slate-700/80 bg-slate-800/70 px-4 py-3">
      <p className="text-xs uppercase tracking-wider text-slate-400">{label}</p>
      <p className="text-sm font-semibold text-slate-100">{value}</p>
    </div>
  );
}

function Action({ href, label }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="rounded-lg border border-cyan-400/30 bg-cyan-400/10 px-3 py-1.5 text-sm font-semibold text-cyan-200 transition hover:border-cyan-300 hover:bg-cyan-300/15 hover:text-white"
    >
      {label}
    </a>
  );
}

export default App;
