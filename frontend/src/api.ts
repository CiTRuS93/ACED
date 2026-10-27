export type Run = {
  id: string;
  project_id: string;
  key: string;
  status: string;
  step: string;
  cycle: number;
  blocker: string | null;
  revision: number;
  redacted: boolean;
  data: Record<string, any>;
};
export type Context = {
  csrf: string;
  projects: { id: string; label: string }[];
  demo: boolean;
  approvals: boolean;
  metrics: boolean;
};
export type Approval = {
  id: string;
  run_id: string;
  task_id: string;
  task_fingerprint: string;
  boundary: string;
  summary: string;
  inputs: Record<string, unknown>;
  expires_at: string;
  status: string;
};
export type Snapshot = {
  run_id: string;
  cycle: number;
  phase: string;
  experiment_id: string;
  observed_at: string;
  fresh_until: string;
  exposure: string;
  safety: string;
  allocation_percent: number | null;
  deadline: string | null;
  readout: string;
  provenance: string[];
  series: {
    name: string;
    unit: string;
    guardrail: number | null;
    interpretation: string;
    points: { at: string; value: number | null }[];
  }[];
};
let csrf = "";
export function setCsrf(value: string) {
  csrf = value;
}
export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, {
    credentials: "same-origin",
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json", "X-ACED-CSRF": csrf },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : `Request failed (${response.status})`,
    );
  return data;
}
export const encode = encodeURIComponent;
export function stamp(value: unknown) {
  return typeof value === "string"
    ? new Date(value).toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "medium",
      })
    : "Unavailable";
}
export function reference(value: string) {
  return /^https?:\/\//i.test(value) ? value : undefined;
}
export function exposure(run: Run) {
  return run.redacted
    ? "Restricted"
    : run.data.experiment_zero === true
      ? "Recorded zero"
      : "See host status";
}

// getRandomValues is available on local HTTP as well as secure origins.
export function requestKey(): string {
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}
