import React, { lazy, Suspense, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
const MetricChart = lazy(() => import("./MetricChart"));
import {
  api,
  Approval,
  Context,
  encode,
  exposure,
  reference,
  requestKey,
  Run,
  setCsrf,
  Snapshot,
  stamp,
} from "./api";
import { usePoll } from "./usePoll";
import "./style.css";

export function Badge({ children }: { children: React.ReactNode }) {
  return <span className="badge">{children}</span>;
}
export function Facts({
  value,
  title = "Details",
}: {
  value: unknown;
  title?: string;
}) {
  return (
    <details>
      <summary>{title}</summary>
      <pre>{JSON.stringify(value, null, 2)}</pre>
    </details>
  );
}
function Ref({ value }: { value: string }) {
  const href = reference(value);
  return href ? (
    <a href={href} target="_blank" rel="noreferrer">
      {value}
    </a>
  ) : (
    <span className="reference">{value}</span>
  );
}
function ErrorNote({ error }: { error: string }) {
  return error ? (
    <p className="notice error" role="alert">
      {error} Last-known data may be stale. Refresh before acting.
    </p>
  ) : null;
}

export function App() {
  const [context, setContext] = useState<Context>();
  const [error, setError] = useState("");
  const [token, setToken] = useState("");
  const initialized = useRef(false);
  const connect = async (value?: string) => {
    try {
      if (value) await api("/session", { token: value });
      const result = await api<Context>("/context");
      setCsrf(result.csrf);
      setContext(result);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    }
  };
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    const bootstrap = new URLSearchParams(location.hash.slice(1)).get("token");
    if (bootstrap) history.replaceState(null, "", location.pathname);
    void connect(bootstrap || undefined);
  }, []);
  return (
    <>
      <header className="masthead">
        <a href="/" className="brand">
          <span aria-hidden="true">◉</span> ACED
        </a>
        <span>Cycle manager</span>
        <span className="preview">Development preview</span>
      </header>
      {context ? (
        <Console context={context} />
      ) : (
        <main className="login">
          <h1>Connect to your local runtime</h1>
          <p>
            Enter the one-time token provided by your host. Your host determines
            which projects and actions you can access.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void connect(token);
            }}
          >
            <label>
              Bootstrap token
              <input
                type="password"
                value={token}
                onChange={(e) => setToken(e.target.value)}
                required
                minLength={32}
                autoComplete="off"
              />
            </label>
            <button>Connect</button>
          </form>
          <ErrorNote error={error} />
        </main>
      )}
    </>
  );
}

export function Console({ context }: { context: Context }) {
  const [project, setProject] = useState(context.projects[0]?.id || "");
  const [selected, setSelected] = useState<string>();
  const [create, setCreate] = useState(false);
  const [continuation, setContinuation] = useState<Run>();
  const [filter, setFilter] = useState("all");
  const [cursor, setCursor] = useState(0);
  const [previousPages, setPreviousPages] = useState<number[]>([]);
  const runs = usePoll(
    `runs:${project}:${cursor}`,
    () =>
      project
        ? api<{ items: { seq: number; run: Run }[]; next: number | null }>(
            `/runs?project_id=${encode(project)}&after=${cursor}`,
          )
        : Promise.resolve({ items: [], next: null }),
    5000,
  );
  const items = runs.data?.items || [];
  const filtered = items.filter(
    ({ run }) =>
      filter === "all" ||
      (filter === "open"
        ? !["completed", "stopped"].includes(run.status)
        : run.status === filter),
  );
  return (
    <div className="shell">
      <aside>
        <label>
          Project
          <select
            value={project}
            onChange={(e) => {
              setProject(e.target.value);
              setSelected(undefined);
              setPreviousPages([]);
              setCursor(0);
              setCreate(false);
            }}
          >
            {context.projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        <nav>
          <button
            className={!selected ? "nav-active" : ""}
            onClick={() => setSelected(undefined)}
          >
            Cycles & experiments
          </button>
        </nav>
        <div className="aside-note">
          <strong>One durable loop.</strong>
          <p>Hypothesize, implement, experiment, decide.</p>
          <p>Host permissions and independent stopping remain in force.</p>
        </div>
      </aside>
      <main>
        {context.demo && (
          <p className="notice fixture">
            Offline lab · Synthetic metrics and deterministic agents. Nothing is
            deployed. State resets when this demo exits.
          </p>
        )}
        {!selected ? (
          <>
            <div className="page-heading">
              <div>
                <h1>Cycles & experiments</h1>
                <p>
                  Follow the work. Review the evidence. Choose when to
                  intervene.
                </p>
              </div>
              <button
                disabled={!project}
                onClick={() => {
                  setContinuation(undefined);
                  setCreate(true);
                }}
              >
                New goal
              </button>
            </div>
            <div className="toolbar">
              <label>
                Show on this page
                <select
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                >
                  <option value="all">All runs</option>
                  <option value="open">Ongoing</option>
                  <option value="held">Held</option>
                  <option value="stopping">Stopping</option>
                  <option value="completed">Completed</option>
                  <option value="stopped">Stopped</option>
                </select>
              </label>
              <span>
                {runs.at
                  ? `Updated ${runs.at.toLocaleTimeString()}`
                  : "Loading…"}
              </span>
              <button className="secondary" onClick={runs.refresh}>
                Refresh
              </button>
            </div>
            <ErrorNote error={runs.error} />
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Goal</th>
                    <th>Cycle / stage</th>
                    <th>Scheduling</th>
                    <th>Exposure</th>
                    <th>Needs attention</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map(({ run }) => (
                    <tr key={run.id}>
                      <td>
                        <button
                          className="link"
                          onClick={() => setSelected(run.id)}
                        >
                          {run.data.goal?.objective || run.key}
                        </button>
                        <small>{run.id.slice(0, 8)}</small>
                      </td>
                      <td>
                        {run.cycle} / {run.step}
                      </td>
                      <td>
                        <Badge>{run.status}</Badge>
                      </td>
                      <td>{exposure(run)}</td>
                      <td>{run.blocker || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {runs.data && !filtered.length && (
              <div className="empty">
                <h2>No runs in this view</h2>
                <p>
                  Start a goal for this project or choose a different filter.
                </p>
              </div>
            )}
            <div className="actions">
              {previousPages.length > 0 && (
                <button
                  className="secondary"
                  onClick={() => {
                    setCursor(previousPages[previousPages.length - 1]);
                    setPreviousPages(previousPages.slice(0, -1));
                  }}
                >
                  Previous page
                </button>
              )}
              {runs.data?.next != null && (
                <button
                  className="secondary"
                  onClick={() => {
                    setPreviousPages([...previousPages, cursor]);
                    setCursor(runs.data!.next!);
                  }}
                >
                  Next page
                </button>
              )}
            </div>
          </>
        ) : (
          <RunDetail
            key={selected}
            id={selected}
            context={context}
            back={() => {
              setSelected(undefined);
              runs.refresh();
            }}
            continueRun={(run) => {
              setContinuation(run);
              setCreate(true);
            }}
          />
        )}
        {create && (
          <StartForm
            project={project}
            previous={continuation}
            close={() => setCreate(false)}
            created={(run) => {
              setCreate(false);
              setSelected(run.id);
              runs.refresh();
            }}
          />
        )}
        <footer>
          Development preview. Offline fixtures do not qualify live or
          unattended operation.
        </footer>
      </main>
    </div>
  );
}

function StartForm({
  project,
  previous,
  close,
  created,
}: {
  project: string;
  previous?: Run;
  close: () => void;
  created: (run: Run) => void;
}) {
  const [objective, setObjective] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [learning, setLearning] = useState<string[]>([]);
  const [candidates, setCandidates] = useState<string[]>([]);
  const [key] = useState(() => requestKey());
  const frozen = useRef<
    | {
        project_id: string;
        objective: string;
        key: string;
        continuation?: unknown;
      }
    | undefined
  >(undefined);
  const toggle = (value: string, all: string[], set: (v: string[]) => void) =>
    set(all.includes(value) ? all.filter((x) => x !== value) : [...all, value]);
  const submit = async () => {
    frozen.current ||= {
      project_id: project,
      objective,
      key,
      ...(previous
        ? {
            continuation: {
              previous_run_id: previous.id,
              accepted_source: previous.data.retained_source,
              learning_references: learning,
              candidate_ids: candidates,
            },
          }
        : {}),
    };
    setBusy(true);
    try {
      created(await api<Run>("/runs", frozen.current));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title={previous ? "Continue from retained learning" : "Start a new goal"}
      close={close}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <p>
          Uses the host’s frozen plan, runner configuration, and budgets for{" "}
          <strong>{project}</strong>.
        </p>
        <label>
          Measurable goal
          <textarea
            autoFocus
            required
            maxLength={10000}
            value={objective}
            disabled={!!frozen.current}
            onChange={(e) => setObjective(e.target.value)}
          />
        </label>
        {previous && (
          <>
            <p>
              Accepted source: <strong>{previous.data.retained_source}</strong>
            </p>
            <fieldset disabled={!!frozen.current}>
              <legend>Retained learning</legend>
              {(previous.data.learning || []).map((item: any) => (
                <label className="check" key={item.reference}>
                  <input
                    type="checkbox"
                    checked={learning.includes(item.reference)}
                    onChange={() =>
                      toggle(item.reference, learning, setLearning)
                    }
                  />
                  {item.learning}
                </label>
              ))}
            </fieldset>
            <fieldset disabled={!!frozen.current}>
              <legend>Retained candidates</legend>
              {(previous.data.research_candidates || []).map((item: any) => (
                <label className="check" key={item.id}>
                  <input
                    type="checkbox"
                    checked={candidates.includes(item.id)}
                    onChange={() => toggle(item.id, candidates, setCandidates)}
                  />
                  {item.claim} ({item.id})
                </label>
              ))}
            </fieldset>
          </>
        )}
        <ErrorNote error={error} />
        {error && (
          <p>
            The request identity is retained. Retry checks the same named goal.
          </p>
        )}
        <div className="actions">
          <button disabled={busy || !objective.trim()}>
            {busy ? "Submitting…" : error ? "Retry same request" : "Start run"}
          </button>
          <button type="button" className="secondary" onClick={close}>
            Close
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Modal({
  title,
  close,
  children,
}: {
  title: string;
  close: () => void;
  children: React.ReactNode;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    dialog.current?.showModal();
  }, []);
  return (
    <dialog ref={dialog} onCancel={close} onClose={close}>
      <div className="modal-heading">
        <h2>{title}</h2>
        <button className="secondary" aria-label="Close dialog" onClick={close}>
          ×
        </button>
      </div>
      {children}
    </dialog>
  );
}

function RunDetail({
  id,
  context,
  back,
  continueRun,
}: {
  id: string;
  context: Context;
  back: () => void;
  continueRun: (r: Run) => void;
}) {
  const view = usePoll(
    `run:${id}`,
    () => api<Run>(`/runs/${encode(id)}`),
    5000,
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState<string>();
  const [tab, setTab] = useState("Experiment");
  const [phase, setPhase] = useState("canary");
  const run = view.data;
  const d = run?.data || {};
  const act = async (action: string) => {
    setBusy(true);
    setError("");
    setConfirm(undefined);
    try {
      await api(`/runs/${encode(id)}/actions/${action}`, {});
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      view.refresh();
    }
  };
  if (!run)
    return (
      <>
        <button className="link" onClick={back}>
          Back to all runs
        </button>
        <ErrorNote error={view.error} />
        <p>Loading run…</p>
      </>
    );
  const terminal = ["completed", "stopped"].includes(run.status);
  return (
    <>
      <button className="link breadcrumb" onClick={back}>
        All runs / {run.id.slice(0, 8)}
      </button>
      <div className="page-heading">
        <div>
          <h1>{d.goal?.objective || run.key}</h1>
          <p>
            Cycle {run.cycle} <span className="dot">·</span>{" "}
            <Badge>{run.status}</Badge> <span className="dot">·</span> Revision{" "}
            {run.revision}
          </p>
        </div>
        <div className="actions">
          {!terminal && (
            <>
              <button
                className="secondary"
                disabled={busy || !!view.error || run.status === "stopping"}
                onClick={() =>
                  run.status === "held"
                    ? void act("resume")
                    : setConfirm("hold")
                }
              >
                {run.status === "held"
                  ? "Resume scheduling"
                  : "Hold scheduling"}
              </button>
              <button
                className="danger"
                disabled={busy}
                onClick={() => setConfirm("stop")}
              >
                Request stop
              </button>
            </>
          )}
          {terminal && !run.redacted && d.retained_source && (
            <button onClick={() => continueRun(run)}>
              Continue with new goal
            </button>
          )}
        </div>
      </div>
      <ErrorNote error={error || view.error} />
      {run.redacted ? (
        <p className="notice">
          Evidence is restricted. Ask your host for access.
        </p>
      ) : (
        <>
          <ol className="stages">
            {["hypothesize", "implement", "experiment", "decide"].map(
              (step, i) => (
                <li
                  key={step}
                  className={run.step === step ? "current" : ""}
                  aria-current={run.step === step ? "step" : undefined}
                >
                  <span>{i + 1}</span>
                  {step}
                </li>
              ),
            )}
          </ol>
          {run.blocker && (
            <p className="notice">
              <strong>Waiting:</strong> {run.blocker}
            </p>
          )}
          {run.status === "held" && (
            <p className="notice">
              Scheduling is held. Existing exposure may continue; safety
              monitoring and stop reconciliation remain active.
            </p>
          )}
          {run.status === "stopping" && (
            <p className="notice error">
              Stop requested. Delivery acknowledgment is not confirmed zero.
              Reconciliation is still in progress.
            </p>
          )}
          <div className="summary-grid">
            <section>
              <h2>Working hypothesis</h2>
              <p>
                {d.hypothesis || "Awaiting research and a selected candidate."}
              </p>
              <small>
                {d.selected_candidate_id || "No candidate selected"}
              </small>
            </section>
            <section>
              <h2>Task budget</h2>
              <p className="budget">
                {d.task_count || 0} <span>/ {d.config?.max_tasks ?? "—"}</span>
              </p>
              <small>
                {d.reserved_tasks || 0} budget slots committed ·{" "}
                {d.cleanup_count || 0} cleanup tasks
              </small>
            </section>
            <section>
              <h2>Current authority</h2>
              <p>{(d.scope || "Unavailable").replaceAll("_", " ")}</p>
              <small>{d.task?.task?.runner || "No prepared agent task"}</small>
            </section>
          </div>
          <div role="tablist" aria-label="Run detail" className="tabs">
            {[
              "Experiment",
              "Approvals",
              "Cycle history",
              "Tasks & audit",
              "Plan & evidence",
            ].map((name) => (
              <button
                role="tab"
                aria-selected={tab === name}
                key={name}
                onClick={() => setTab(name)}
              >
                {name}
              </button>
            ))}
          </div>
          {tab === "Experiment" && (
            <>
              <div className="toolbar">
                <h2>Experiment observation</h2>
                <label>
                  Phase
                  <select
                    value={phase}
                    onChange={(e) => setPhase(e.target.value)}
                  >
                    <option value="canary">Canary · operational safety</option>
                    <option value="main">Main · product benefit</option>
                  </select>
                </label>
              </div>
              <Experiment
                key={`${run.id}:${run.cycle}:${phase}`}
                run={run}
                phase={phase}
                enabled={context.metrics}
              />
            </>
          )}
          {tab === "Approvals" && (
            <Approvals
              run={run}
              enabled={context.approvals}
              changed={view.refresh}
            />
          )}
          {tab === "Cycle history" && (
            <section>
              <h2>Retained learning</h2>
              {!(d.learning || []).length && (
                <p>No completed learning records yet.</p>
              )}
              {(d.learning || []).map((entry: any, i: number) => (
                <article className="learning" key={i}>
                  <h3>
                    Cycle {entry.cycle}: {entry.outcome || entry.action}
                  </h3>
                  <p>{entry.learning}</p>
                  <p>Goal assessment: {entry.assessment || "Unavailable"}</p>
                  <Ref value={entry.reference} />
                  <Facts value={entry} title="Decision and source lineage" />
                </article>
              ))}
            </section>
          )}
          {tab === "Tasks & audit" && (
            <>
              <RecordPage id={id} kind="tasks" />
              <RecordPage id={id} kind="history" />
            </>
          )}
          {tab === "Plan & evidence" && (
            <section>
              <h2>Frozen plan and evidence</h2>
              <Facts
                value={d.cycle_plan || d.config?.plan}
                title="Accepted experiment plan"
              />
              <Facts
                value={d.research_candidates || []}
                title="Retained candidates"
              />
              <Facts value={d.verification || {}} title="Verified handoff" />
              <Facts
                value={{
                  stop_request_id: d.stop_request_id,
                  delivery: d.stop_delivery,
                  experiment_zero: d.experiment_zero,
                  effects_settled: d.effects_settled,
                  cleanup_confirmed: d.cleanup_confirmed,
                }}
                title="Stop and settlement records"
              />
              <Facts value={d} title="Authorized runtime projection" />
              {d.current && d.task?.status === "prepared" && (
                <button
                  className="secondary"
                  disabled={busy || !!view.error}
                  onClick={() => setConfirm("repropose")}
                >
                  Replace unlaunched proposal
                </button>
              )}
            </section>
          )}
        </>
      )}
      {confirm && (
        <Modal
          title={
            confirm === "stop"
              ? "Request product stop"
              : confirm === "hold"
                ? "Hold ordinary scheduling"
                : "Replace unlaunched proposal"
          }
          close={() => setConfirm(undefined)}
        >
          <p>
            <strong>{d.goal?.objective || run.key}</strong>
          </p>
          <p>
            {confirm === "stop"
              ? "Persist a stop request and ask the independent host executor to stop effects. The run remains stopping until authoritative settlement; closing this browser does not cancel the request."
              : confirm === "hold"
                ? "Prevent ordinary new task launches. This does not stop product exposure. Safety work continues."
                : "The previous proposal will be cancelled. Its approval cannot authorize the replacement; new approval is required."}
          </p>
          <button
            className={confirm === "stop" ? "danger" : ""}
            onClick={() => void act(confirm)}
          >
            Confirm {confirm}
          </button>
        </Modal>
      )}
    </>
  );
}

function Experiment({
  run,
  phase,
  enabled,
}: {
  run: Run;
  phase: string;
  enabled: boolean;
}) {
  const [hours, setHours] = useState("1");
  const experimentId =
    run.data[phase === "canary" ? "canary_id" : "experiment_id"];
  const result = usePoll(
    `metrics:${run.id}:${run.cycle}:${phase}:${hours}`,
    async () => {
      if (!enabled || !experimentId) return null;
      const end = new Date();
      const start = new Date(end.getTime() - Number(hours) * 3600000);
      return api<Snapshot>(
        `/experiments/${encode(run.id)}?${new URLSearchParams({ cycle: String(run.cycle), phase, experiment_id: experimentId, start: start.toISOString(), end: end.toISOString(), max_points: "240" })}`,
      );
    },
    15000,
  );
  if (!enabled)
    return (
      <p className="empty">
        Live metrics unavailable. Connect a host metrics adapter to show
        experiment observations.
      </p>
    );
  const data = result.data;
  const stale =
    !!result.error ||
    (data ? Date.parse(data.fresh_until) < Date.now() : false);
  return (
    <section>
      <div className="toolbar">
        <p>Host records determine safety, closure, and statistical validity.</p>
        <label>
          Window
          <select value={hours} onChange={(e) => setHours(e.target.value)}>
            <option value="1">Last hour</option>
            <option value="24">Last day</option>
            <option value="168">Last week</option>
          </select>
        </label>
        <button className="secondary" onClick={result.refresh}>
          Refresh metrics
        </button>
      </div>
      <ErrorNote error={result.error} />
      {!data ? (
        <p>No observation available yet.</p>
      ) : (
        <>
          {stale && (
            <p className="notice error">
              Stale observation. Current exposure and safety are unknown.
            </p>
          )}
          <div className="experiment-facts">
            <div>
              <small>Exposure</small>
              <strong>{stale ? "Unknown" : data.exposure}</strong>
            </div>
            <div>
              <small>Fixed allocation</small>
              <strong>
                {data.allocation_percent === null
                  ? "Unavailable"
                  : `${data.allocation_percent}%`}
              </strong>
            </div>
            <div>
              <small>Native deadline</small>
              <strong>{stamp(data.deadline)}</strong>
            </div>
            <div>
              <small>Last host observation</small>
              <strong>{stamp(data.observed_at)}</strong>
            </div>
          </div>
          <p>{data.safety}</p>
          {!data.series.length && (
            <p className="empty">
              No metric series available. Missing telemetry does not establish
              health.
            </p>
          )}
          <div className="charts">
            {data.series.map((series) => (
              <article key={series.name}>
                <h3>
                  {series.name} <small>({series.unit})</small>
                </h3>
                <Suspense fallback={<p>Loading chart…</p>}>
                  <MetricChart series={series} />
                </Suspense>
                <p>{series.interpretation}</p>
                <details>
                  <summary>
                    Accessible data table · {series.points.length} observations
                  </summary>
                  <div className="metric-table">
                    <table>
                      <thead>
                        <tr>
                          <th>Time</th>
                          <th>Value ({series.unit})</th>
                        </tr>
                      </thead>
                      <tbody>
                        {series.points.map((point, i) => (
                          <tr key={i}>
                            <td>{stamp(point.at)}</td>
                            <td>{point.value ?? "Missing"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              </article>
            ))}
          </div>
          <div className="readout">
            <h3>Host readout</h3>
            <p>{data.readout}</p>
            {data.provenance.map((value) => (
              <div key={value}>
                <Ref value={value} />
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function Approvals({
  run,
  enabled,
  changed,
}: {
  run: Run;
  enabled: boolean;
  changed: () => void;
}) {
  const inbox = usePoll(
    `approvals:${run.id}`,
    () =>
      enabled
        ? api<{ items: Approval[] }>(`/approvals/${encode(run.id)}`)
        : Promise.resolve({ items: [] }),
    5000,
  );
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pending = useRef<
    | { id: string; task_fingerprint: string; decision: string; key: string }
    | undefined
  >(undefined);
  const decide = async (item: Approval, decision: string) => {
    if (
      pending.current &&
      (pending.current.id !== item.id || pending.current.decision !== decision)
    ) {
      setError(
        "Refresh the host outcome before choosing a different decision.",
      );
      return;
    }
    pending.current ||= {
      id: item.id,
      task_fingerprint: item.task_fingerprint,
      decision,
      key: requestKey(),
    };
    setBusy(true);
    setError("");
    try {
      const { id, ...body } = pending.current;
      await api(`/approvals/${encode(run.id)}/${encode(id)}`, body);
      pending.current = undefined;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      inbox.refresh();
      changed();
    }
  };
  return (
    <section>
      <h2>Approval inbox</h2>
      {!enabled ? (
        <p>
          Host approval connection unavailable. Use your host’s existing
          approval tools.
        </p>
      ) : (
        <>
          <ErrorNote error={error || inbox.error} />
          {inbox.data?.items.length === 0 && (
            <p>No approval requests for the current task.</p>
          )}
          {inbox.data?.items.map((item) => (
            <article className="approval" key={item.id}>
              <div className="toolbar">
                <h3>{item.summary}</h3>
                <Badge>
                  {Date.parse(item.expires_at) < Date.now()
                    ? "expired"
                    : item.status}
                </Badge>
              </div>
              <p>
                Authority: {item.boundary} · Expires {stamp(item.expires_at)}
              </p>
              <Facts
                value={{
                  task_id: item.task_id,
                  fingerprint: item.task_fingerprint,
                  inputs: item.inputs,
                }}
                title="Review exact task and frozen inputs"
              />
              <div className="actions">
                <button
                  disabled={
                    busy ||
                    !!inbox.error ||
                    item.status !== "pending" ||
                    Date.parse(item.expires_at) < Date.now()
                  }
                  onClick={() => void decide(item, "approve")}
                >
                  Approve task
                </button>
                <button
                  className="secondary"
                  disabled={
                    busy ||
                    !!inbox.error ||
                    item.status !== "pending" ||
                    Date.parse(item.expires_at) < Date.now()
                  }
                  onClick={() => void decide(item, "deny")}
                >
                  Deny task
                </button>
              </div>
            </article>
          ))}
        </>
      )}
    </section>
  );
}

function RecordPage({ id, kind }: { id: string; kind: "tasks" | "history" }) {
  const [items, setItems] = useState<any[]>([]);
  const [cursor, setCursor] = useState<number | null>(0);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const load = async (reset = false) => {
    setBusy(true);
    try {
      const result = await api<{ items: any[]; next: number | null }>(
        `/runs/${encode(id)}/${kind}?after=${reset ? 0 : cursor || 0}`,
      );
      setItems((old) => (reset ? result.items : [...old, ...result.items]));
      setCursor(result.next);
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  useEffect(() => {
    void load(true);
  }, [id, kind]);
  return (
    <section>
      <div className="toolbar">
        <h2>{kind === "tasks" ? "Agent tasks" : "Audit history"}</h2>
        <button
          className="secondary"
          disabled={busy}
          onClick={() => void load(true)}
        >
          Refresh {kind}
        </button>
      </div>
      <ErrorNote error={error} />
      {items.map((item) => (
        <Facts
          key={item.seq}
          value={item}
          title={
            kind === "tasks"
              ? `Task ${item.seq}: ${item.status || item.id}`
              : `Event ${item.seq}: ${item.event || item.revision}`
          }
        />
      ))}
      {!items.length && !busy && <p>No retained records yet.</p>}
      {cursor !== null && (
        <button
          className="secondary"
          disabled={busy}
          onClick={() => void load()}
        >
          Load more {kind}
        </button>
      )}
    </section>
  );
}

if (document.getElementById("root"))
  createRoot(document.getElementById("root")!).render(<App />);
