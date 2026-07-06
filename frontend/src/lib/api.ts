// Server-side base URL: inside Docker Compose this is http://backend:8000
// (set via the API_URL env var); locally it defaults to localhost.
const API_URL = process.env.API_URL ?? "http://localhost:8000";

export type TaskStatus =
  | "pending"
  | "planning"
  | "coding"
  | "testing"
  | "completed"
  | "failed";

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

export function getProjects(): Promise<Project[]> {
  return get<Project[]>("/api/v1/projects");
}
