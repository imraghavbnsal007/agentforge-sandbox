import type { RepositoryList } from "@/lib/repositories";

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
  | "failed"
  | "cancelled"
  | "publish_failed";

export type RunStage =
  | "queued"
  | "preparing"
  | "cloning"
  | "analysing"
  | "planning"
  | "generating"
  | "testing"
  | "summarising"
  | "awaiting_review"
  | "pushing"
  | "creating_pr"
  | "completed"
  | "failed"
  | "cancelled";

export interface TaskEvent {
  id: number;
  task_id: number;
  run_id: number | null;
  sequence_number: number;
  event_type: string;
  stage: RunStage | null;
  message: string | null;
  progress: number | null;
  error_code: string | null;
  safe_metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface TaskEventPage {
  events: TaskEvent[];
  next_cursor: number | null;
}

export type ChangeType = "create" | "modify" | "delete";

export interface Task {
  id: number;
  project_id: number;
  title: string;
  request: string;
  status: TaskStatus;
  llm_provider: string | null;
  llm_model: string | null;
  execution_profile: string | null;
  created_at: string;
  updated_at: string;
  latest_run_mode: "mock" | "llm" | null;
  latest_run_pr_url: string | null;
}

export interface AppConfig {
  agent_mode: "mock" | "llm";
  llm_provider: string;
  default_model: string;
  anthropic_model: string;
  api_key_configured: boolean;
  github_token_configured: boolean;
  providers_configured: Record<string, boolean>;
}

export interface ProviderInfo {
  name: string;
  label: string;
  configured: boolean;
  implemented: boolean;
  models: string[];
}

export interface ProfileInfo {
  name: string;
  phases: Record<string, string>;
  estimated_cost_usd: number | null;
  estimated_latency_seconds: number;
}

export interface LLMOptions {
  default_provider: string;
  default_model: string;
  providers: ProviderInfo[];
  profiles: ProfileInfo[];
}

export interface UsageBucket {
  key: string;
  requests: number;
  tokens_in: number;
  tokens_out: number;
  cost_usd: number;
  avg_latency_ms: number;
  success_rate: number;
}

export interface UsageReport {
  total_requests: number;
  total_tokens_in: number;
  total_tokens_out: number;
  total_cost_usd: number;
  avg_latency_ms: number;
  success_rate: number;
  by_provider: UsageBucket[];
  by_model: UsageBucket[];
  by_project: UsageBucket[];
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
  preferred_provider: string | null;
  preferred_model: string | null;
  preferred_execution_profile: string | null;
  created_at: string;
  analysis_status: AnalysisStatus | null;
  last_analyzed_at: string | null;
  primary_language: string | null;
  framework: string | null;
  test_command: string | null;
  health_score: number | null;
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
  confidence: string;
  reasoning: string;
  effort: string;
}

export interface RepoMapNode {
  name: string;
  children?: RepoMapNode[];
}

export interface SqlTableInfo {
  name: string;
  file: string;
  columns: { name: string; type: string }[];
  primary_key: string[];
  foreign_keys: {
    name: string;
    columns: string[];
    ref_table: string;
    ref_columns: string[];
  }[];
  checks: { name: string; expression: string }[];
  uniques: string[];
}

export interface SqlSchemaInfo {
  tables: SqlTableInfo[];
  views: { name: string; file: string }[];
  procedures: { name: string; file: string }[];
  functions: { name: string; file: string }[];
  triggers: { name: string; file: string }[];
  indexes: { name: string; table: string; file: string }[];
  dropped_views_not_created: string[];
}

export interface HealthPart {
  score: number;
  reason: string;
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
  project_type: string | null;
  entry_points: string[] | null;
  api_routes: { method: string; path: string; file: string }[] | null;
  repo_map: RepoMapNode[] | null;
  sql_schema: SqlSchemaInfo | null;
  schema_summary: string | null;
  health_score: number | null;
  health_breakdown: Record<string, HealthPart> | null;
  analysis_logs: string | null;
  error: string | null;
  enrichment_warning: string | null;
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
  is_binary: boolean;
  size_bytes: number | null;
  content_hash: string | null;
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
  /** Set when the agent stopped early; the run still succeeded. */
  incomplete_reason: string | null;
  branch_name: string | null;
  commit_sha: string | null;
  pr_url: string | null;
  // The provider/model this run actually used (from its llm_runs rows) —
  // not the global default. Null for mock runs or runs with no recorded calls.
  llm_provider: string | null;
  llm_model: string | null;
  started_at: string;
  finished_at: string | null;
  file_changes: FileChange[];
  test_results: TestResult[];
}

export interface TaskDetail extends Task {
  latest_run: AgentRun | null;
  runs: AgentRun[];
}

/** Thrown when the API rejects a request for lack of a session. */
export class UnauthenticatedError extends Error {
  constructor(path: string) {
    super(`Not authenticated: ${path}`);
    this.name = "UnauthenticatedError";
  }
}

/**
 * Server-side read. Forwards the caller's cookies so the backend sees the
 * same session the browser has — without this every server component would
 * look anonymous to the API.
 */
async function get<T>(path: string): Promise<T> {
  const { cookies } = await import("next/headers");
  const cookieHeader = (await cookies()).toString();
  const res = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
    headers: cookieHeader ? { cookie: cookieHeader } : undefined,
  });
  if (res.status === 401) {
    throw new UnauthenticatedError(path);
  }
  if (!res.ok) {
    throw new Error(`API request failed: ${res.status} ${path}`);
  }
  return res.json();
}

/** Read the CSRF token the backend mirrored into a readable cookie. */
function csrfToken(): string {
  if (typeof document === "undefined") return "";
  const match = document.cookie.match(/(?:^|;\s*)agentforge_csrf=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : "";
}

/**
 * Browser-side write. Sends the session cookie and echoes the CSRF token,
 * which the backend requires on every cookie-authenticated mutation.
 */
async function mutate<T>(
  path: string,
  init: { method: string; body?: unknown },
): Promise<T> {
  const token = csrfToken();
  const headers: Record<string, string> = {};
  if (init.body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["X-CSRF-Token"] = token;

  const res = await fetch(`${PUBLIC_API_URL}${path}`, {
    method: init.method,
    credentials: "include",
    headers,
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `Request failed with ${res.status}`);
  }
  return res.status === 204 ? (undefined as T) : res.json();
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
export function registerProject(input: {
  repo_url: string;
  default_branch: string;
}): Promise<Project> {
  return mutate<Project>("/api/v1/projects/register", {
    method: "POST",
    body: input,
  });
}

/** Browser-side: enqueue a repository analysis. */
export function analyzeProject(id: number): Promise<Analysis> {
  return mutate<Analysis>(`/api/v1/projects/${id}/analyze`, { method: "POST" });
}

function postAction(id: number, action: string): Promise<Task> {
  return mutate<Task>(`/api/v1/tasks/${id}/${action}`, { method: "POST" });
}

/** Browser-side: end the current session. */
export function logout(): Promise<void> {
  return mutate<void>("/api/v1/auth/logout", { method: "POST" });
}

/** Server-side: repositories the caller's GitHub App installations grant. */
export function getRepositories(): Promise<RepositoryList> {
  return get<RepositoryList>("/api/v1/repositories");
}

/** Browser-side: re-read the grant list from GitHub. */
export function refreshRepositories(): Promise<RepositoryList> {
  return mutate<RepositoryList>("/api/v1/repositories/refresh", {
    method: "POST",
  });
}

/**
 * Browser-side: register a granted repository.
 *
 * Identified by GitHub's numeric repository id — never a user-supplied URL —
 * so the backend can check it against the caller's own installation grants.
 */
export function registerRepository(
  githubRepositoryId: number,
): Promise<Project> {
  return mutate<Project>("/api/v1/repositories/register", {
    method: "POST",
    body: { github_repository_id: githubRepositoryId },
  });
}

/** Browser-side: re-enqueue an agent run for an existing task. */
export const retryTask = (id: number) => postAction(id, "retry");
/** Browser-side: ask the worker to stop at its next safe checkpoint. */
export const cancelTask = (id: number) => postAction(id, "cancel");
/**
 * Browser-side: run a finished task again as a NEW task.
 *
 * Completed tasks are terminal, so this is how the work is repeated without
 * the finished result becoming ambiguous. The original is untouched.
 */
export const duplicateTask = (id: number) => postAction(id, "duplicate");

/**
 * Browser-side: delete a task and its runs.
 *
 * Removes only AgentForge's record. The repository, its commits and any pull
 * request this task opened are untouched.
 */
export async function deleteTask(id: number): Promise<void> {
  await mutate<void>(`/api/v1/tasks/${id}`, { method: "DELETE" });
}

/** Browser-side: event history after a cursor — the replay source. */
export async function getTaskEvents(
  id: number,
  afterId = 0,
): Promise<TaskEventPage> {
  const res = await fetch(
    `${PUBLIC_API_URL}/api/v1/tasks/${id}/events?after_id=${afterId}`,
    { credentials: "include", cache: "no-store" },
  );
  if (!res.ok) throw new Error(`Could not load events (${res.status})`);
  return res.json();
}

/** URL of the live event stream for a task. */
export function taskStreamUrl(id: number, afterId = 0): string {
  return `${PUBLIC_API_URL}/api/v1/tasks/${id}/stream?last_event_id=${afterId}`;
}
/** Browser-side: approve a reviewed task — publishes branch + PR. */
export const approveTask = (id: number) => postAction(id, "approve");
/** Browser-side: reject a reviewed task. */
export const rejectTask = (id: number) => postAction(id, "reject");

export function getLLMOptions(): Promise<LLMOptions> {
  return get<LLMOptions>("/api/v1/llm/options");
}

export function getUsage(): Promise<UsageReport> {
  return get<UsageReport>("/api/v1/usage");
}

/** Browser-side: save a project's preferred LLM settings. */
export function updateProjectSettings(
  id: number,
  input: {
    preferred_provider: string | null;
    preferred_model: string | null;
    preferred_execution_profile: string | null;
  },
): Promise<Project> {
  return mutate<Project>(`/api/v1/projects/${id}/settings`, {
    method: "PATCH",
    body: input,
  });
}

/** Browser-side: create a task and enqueue its agent run. */
export function createTask(input: {
  project_id: number;
  title: string;
  request: string;
  llm_provider?: string | null;
  llm_model?: string | null;
  execution_profile?: string | null;
}): Promise<Task> {
  return mutate<Task>("/api/v1/tasks", { method: "POST", body: input });
}
