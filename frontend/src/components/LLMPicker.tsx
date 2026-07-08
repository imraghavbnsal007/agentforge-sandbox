"use client";

import type { LLMOptions } from "@/lib/api";

export interface LLMSelection {
  profile: string; // "cheap" | "balanced" | "premium" | "custom"
  provider: string;
  model: string;
}

const PROFILE_LABELS: Record<string, string> = {
  cheap: "Cheap",
  balanced: "Balanced",
  premium: "Premium",
};

export function LLMPicker({
  options,
  value,
  onChange,
}: {
  options: LLMOptions;
  value: LLMSelection;
  onChange: (next: LLMSelection) => void;
}) {
  const selectedProvider = options.providers.find((p) => p.name === value.provider);
  const activeProfile = options.profiles.find((p) => p.name === value.profile);

  return (
    <div className="space-y-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
      <div>
        <label className="mb-1.5 block text-sm font-medium text-slate-700">
          Execution Profile
        </label>
        <div className="flex flex-wrap gap-2">
          {options.profiles.map((profile) => (
            <label
              key={profile.name}
              className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
                value.profile === profile.name
                  ? "border-slate-900 bg-white font-medium"
                  : "border-slate-300 bg-white text-slate-600"
              }`}
            >
              <input
                type="radio"
                name="profile"
                className="accent-slate-900"
                checked={value.profile === profile.name}
                onChange={() => onChange({ ...value, profile: profile.name })}
              />
              {PROFILE_LABELS[profile.name] ?? profile.name}
            </label>
          ))}
          <label
            className={`flex cursor-pointer items-center gap-2 rounded-lg border px-3 py-2 text-sm ${
              value.profile === "custom"
                ? "border-slate-900 bg-white font-medium"
                : "border-slate-300 bg-white text-slate-600"
            }`}
          >
            <input
              type="radio"
              name="profile"
              className="accent-slate-900"
              checked={value.profile === "custom"}
              onChange={() => onChange({ ...value, profile: "custom" })}
            />
            Custom
          </label>
        </div>
      </div>

      {value.profile === "custom" ? (
        <div className="flex flex-wrap gap-3">
          <div className="w-52">
            <label className="mb-1 block text-xs text-slate-500">AI Provider</label>
            <select
              value={value.provider}
              onChange={(e) => {
                const provider = options.providers.find(
                  (p) => p.name === e.target.value,
                );
                onChange({
                  ...value,
                  provider: e.target.value,
                  model: provider?.models[0] ?? "",
                });
              }}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
            >
              {options.providers.map((p) => (
                <option
                  key={p.name}
                  value={p.name}
                  disabled={!p.implemented || !p.configured}
                >
                  {p.label}
                  {!p.implemented
                    ? " (coming soon)"
                    : !p.configured
                      ? " (no API key)"
                      : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="w-52">
            <label className="mb-1 block text-xs text-slate-500">Model</label>
            <select
              value={value.model}
              onChange={(e) => onChange({ ...value, model: e.target.value })}
              className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
            >
              {(selectedProvider?.models ?? []).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
        </div>
      ) : (
        activeProfile && (
          <p className="text-xs text-slate-500">
            {Object.entries(activeProfile.phases)
              .filter(([phase]) => ["planning", "coding", "summarize"].includes(phase))
              .map(([phase, spec]) => `${phase}: ${spec}`)
              .join(" · ")}
          </p>
        )
      )}

      <div className="flex gap-6 text-sm">
        <span>
          <span className="text-slate-400">Estimated Cost:</span>{" "}
          <span className="font-medium text-slate-800">
            {value.profile === "custom"
              ? "varies by usage"
              : activeProfile?.estimated_cost_usd != null
                ? `~$${activeProfile.estimated_cost_usd.toFixed(2)}`
                : "unknown"}
          </span>
        </span>
        <span>
          <span className="text-slate-400">Estimated Latency:</span>{" "}
          <span className="font-medium text-slate-800">
            {value.profile === "custom"
              ? "—"
              : activeProfile
                ? `~${Math.round(activeProfile.estimated_latency_seconds)}s`
                : "—"}
          </span>
        </span>
      </div>
    </div>
  );
}
