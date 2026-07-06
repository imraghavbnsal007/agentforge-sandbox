// Server-side base URL: inside Docker Compose this is http://backend:8000
// (set via the API_URL env var); locally it defaults to localhost.
const API_URL = process.env.API_URL ?? "http://localhost:8000";

// Browser-side base URL (used by client components like the New Task form).
export const PUBLIC_API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type TaskStatus =
  | "pending"
  | "planning"
  | "coding"
  | "testing"
  | "completed"
  | "failed";

export type ChangeType = "create" | "modify" | "delete";

export interface Task {
  id: number;
  project_id: number;
  title: string;
  request: string;
  status: TaskStatus;
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: number;
  name: string;
  description: string;
  repo_path: string;
  created_at: string;
}

export interface FileChange {
  id: number;
  path: string;
  change_type: ChangeType;
  diff: string;
}

export interface TestResult {
  id: number;
  suite: string;
  passed: number;
  failed: number;
  errored: number;
  duration: number;
  output: string;
  stderr: string;
}

export interface AgentRun {
  id: number;
  task_id: number;
  mode: "mock" | "llm";
  status: "running" | "completed" | "failed";
  plan: string[] | null;
  summary: string | null;
  log: string | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
  file_changes: FileChange[];
  test_results: TestResult[];
}

export interface TaskDetail extends Task {
  latest_run: AgentRun | null;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`API request failed: ${res.status} ${path}`);
  }
  return res.json();
}

export function getTasks(): Promise<Task[]> {
  return get<Task[]>("/api/v1/tasks");
}

export function getTask(id: string | number): Promise<TaskDetail> {
  return get<TaskDetail>(`/api/v1/tasks/${id}`);
}

export function getProjects(): Promise<Project[]> {
  return get<Project[]>("/api/v1/projects");
}

/** Browser-side: create a task and enqueue its agent run. */
export async function createTask(input: {
  project_id: number;
  title: string;
  request: string;
}): Promise<Task> {
  const res = await fetch(`${PUBLIC_API_URL}/api/v1/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Request failed with ${res.status}`);
  }
  return res.json();
}
