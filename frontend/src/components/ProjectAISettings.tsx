"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  updateProjectSettings,
  type LLMOptions,
  type Project,
} from "@/lib/api";

export function ProjectAISettings({
  project,
  options,
}: {
  project: Project;
  options: LLMOptions;
}) {
  const router = useRouter();
  const [profile, setProfile] = useState(project.preferred_execution_profile ?? "");
  const [provider, setProvider] = useState(project.preferred_provider ?? "");
  const [model, setModel] = useState(project.preferred_model ?? "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const providerInfo = options.providers.find((p) => p.name === provider);

  async function save() {
    setBusy(true);
    setMessage(null);
    try {
      await updateProjectSettings(project.id, {
        preferred_execution_profile: profile || null,
        preferred_provider: provider || null,
        preferred_model: provider ? model || null : null,
      });
      setMessage("Saved — new tasks will default to these settings.");
      router.refresh();
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Save failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-wrap items-end gap-3 px-4 py-3">
      <div className="w-44">
        <label className="mb-1 block text-xs text-slate-500">Execution profile</label>
        <select
          value={profile}
          onChange={(e) => setProfile(e.target.value)}
          className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
        >
          <option value="">(default)</option>
          {options.profiles.map((p) => (
            <option key={p.name} value={p.name}>
              {p.name}
            </option>
          ))}
        </select>
      </div>
      <div className="w-44">
        <label className="mb-1 block text-xs text-slate-500">Provider override</label>
        <select
          value={provider}
          onChange={(e) => {
            setProvider(e.target.value);
            const info = options.providers.find((p) => p.name === e.target.value);
            setModel(info?.models[0] ?? "");
          }}
          className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
        >
          <option value="">(none)</option>
          {options.providers
            .filter((p) => p.implemented)
            .map((p) => (
              <option key={p.name} value={p.name}>
                {p.label}
                {!p.configured ? " (no API key)" : ""}
              </option>
            ))}
        </select>
      </div>
      {provider && (
        <div className="w-44">
          <label className="mb-1 block text-xs text-slate-500">Model</label>
          <select
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
          >
            {(providerInfo?.models ?? []).map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
      )}
      <button
        onClick={save}
        disabled={busy}
        className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
      >
        {busy ? "Saving…" : "Save"}
      </button>
      {message && <span className="text-xs text-slate-500">{message}</span>}
    </div>
  );
}
