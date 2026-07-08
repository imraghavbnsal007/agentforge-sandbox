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
  | "ready_for_review"
  | "publishing"
  | "rejected"
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
  latest_run_mode: "mock" | "llm" | null;
  latest_run_pr_url: string | null;
}

export interface AppConfig {
  agent_mode: "mock" | "llm";
  anthropic_model: string;
  api_key_configured: boolean;
  github_token_configured: boolean;
}

export type AnalysisStatus = "pending" | "running" | "completed" | "failed";

export interface Project {
  id: number;
  name: string;
  description: string;
  repo_path: string;
  repo_url: string | null;
  default_branch: string;
  github_owner: string | null;
  github_repo: string | null;
  created_at: string;
  analysis_status: AnalysisStatus | null;
  last_analyzed_at: string | null;
  primary_language: string | null;
  framework: string | null;
  test_command: string | null;
}

export interface FileSummary {
  id: number;
  file_path: string;
  file_type: string;
  purpose: string;
  importance_score: number;
}

export interface Suggestion {
  id: number;
  title: string;
  description: string;
  category: string;
  priority: string;
  related_files: string[] | null;
}

export interface Analysis {
  id: number;
  project_id: number;
  status: AnalysisStatus;
  summary: string | null;
  languages: string[] | null;
  frameworks: string[] | null;
  dependencies: string[] | null;
  package_manager: string | null;
  build_command: string | null;
  test_command: string | null;
  architecture_notes: string | null;
  risk_areas: string | null;
  analysis_logs: string | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
  file_summaries: FileSummary[];
  suggestions: Suggestion[];
}

export interface ProjectDetail extends Project {
  latest_analysis: Analysis | null;
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
  branch_name: string | null;
  commit_sha: string | null;
  pr_url: string | null;
  started_at: string;
  finished_at: string | null;
  file_changes: FileChange[];
  test_results: TestResult[];
}

export interface TaskDetail extends Task {
  latest_run: AgentRun | null;
  runs: AgentRun[];
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

export function getConfig(): Promise<AppConfig> {
  return get<AppConfig>("/api/v1/config");
}

export function getProject(id: string | number): Promise<ProjectDetail> {
  return get<ProjectDetail>(`/api/v1/projects/${id}`);
}

/** Browser-side: register a GitHub repo as a project (validation only, no analysis). */
export async function registerProject(input: {
  repo_url: string;
  default_branch: string;
}): Promise<Project> {
  const res = await fetch(`${PUBLIC_API_URL}/api/v1/projects/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Registration failed with ${res.status}`);
  }
  return res.json();
}

/** Browser-side: enqueue a repository analysis. */
export async function analyzeProject(id: number): Promise<Analysis> {
  const res = await fetch(`${PUBLIC_API_URL}/api/v1/projects/${id}/analyze`, {
    method: "POST",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Analyze failed with ${res.status}`);
  }
  return res.json();
}

async function postAction(id: number, action: string): Promise<Task> {
  const res = await fetch(`${PUBLIC_API_URL}/api/v1/tasks/${id}/${action}`, {
    method: "POST",
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `${action} failed with ${res.status}`);
  }
  return res.json();
}

/** Browser-side: re-enqueue an agent run for an existing task. */
export const retryTask = (id: number) => postAction(id, "retry");
/** Browser-side: approve a reviewed task — publishes branch + PR. */
export const approveTask = (id: number) => postAction(id, "approve");
/** Browser-side: reject a reviewed task. */
export const rejectTask = (id: number) => postAction(id, "reject");

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
