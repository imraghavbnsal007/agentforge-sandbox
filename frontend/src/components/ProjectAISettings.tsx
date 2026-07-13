"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { Button } from "@/components/ui/Button";
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
    <div className="flex flex-wrap items-end gap-3 px-5 py-4">
      <div className="w-full sm:w-44">
        <label
          htmlFor="ai-profile"
          className="mb-1 block text-xs text-ink-dim"
        >
          Execution profile
        </label>
        <select
          id="ai-profile"
          value={profile}
          onChange={(e) => setProfile(e.target.value)}
          className="field"
        >
          <option value="">(default)</option>
          {options.profiles.map((p) => (
            <option key={p.name} value={p.name}>
              {p.name}
            </option>
          ))}
        </select>
      </div>
      <div className="w-full sm:w-44">
        <label
          htmlFor="ai-provider"
          className="mb-1 block text-xs text-ink-dim"
        >
          Provider override
        </label>
        <select
          id="ai-provider"
          value={provider}
          onChange={(e) => {
            setProvider(e.target.value);
            const info = options.providers.find((p) => p.name === e.target.value);
            setModel(info?.models[0] ?? "");
          }}
          className="field"
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
        <div className="w-full sm:w-44">
          <label htmlFor="ai-model" className="mb-1 block text-xs text-ink-dim">
            Model
          </label>
          <select
            id="ai-model"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            className="field"
          >
            {(providerInfo?.models ?? []).map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </div>
      )}
      <Button onClick={save} loading={busy}>
        {busy ? "Saving…" : "Save"}
      </Button>
      {message && <span className="text-xs text-ink-dim">{message}</span>}
    </div>
  );
}
