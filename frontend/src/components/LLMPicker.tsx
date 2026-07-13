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

const PROFILE_HINTS: Record<string, string> = {
  cheap: "Fastest & lowest cost",
  balanced: "Good quality / cost balance",
  premium: "Highest quality",
};

function ProfileChip({
  name,
  label,
  hint,
  selected,
  onSelect,
}: {
  name: string;
  label: string;
  hint?: string;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <label
      className={`flex cursor-pointer flex-col gap-0.5 rounded-xl border px-3.5 py-2.5 text-sm transition-all duration-150 ${
        selected
          ? "border-indigo-400/60 bg-accent-soft text-ink shadow-[0_0_0_1px_rgba(129,140,248,0.25)]"
          : "border-line-strong bg-surface-2 text-ink-mid hover:border-[rgba(255,255,255,0.24)] hover:text-ink"
      }`}
    >
      <span className="flex items-center gap-2 font-medium">
        <input
          type="radio"
          name="profile"
          className="sr-only"
          checked={selected}
          onChange={onSelect}
          aria-label={`${label} execution profile`}
        />
        <span
          aria-hidden
          className={`h-2 w-2 rounded-full ${selected ? "bg-accent" : "bg-line-strong"}`}
        />
        {label}
      </span>
      {hint && <span className="pl-4 text-[11px] text-ink-dim">{hint}</span>}
    </label>
  );
}

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
    <fieldset className="space-y-4 rounded-xl border border-line bg-surface-2/50 p-4">
      <legend className="sr-only">Model selection</legend>
      <div>
        <p className="mb-2 block text-sm font-medium text-ink-mid">
          Execution Profile
        </p>
        <div
          className="grid grid-cols-2 gap-2 sm:grid-cols-4"
          role="radiogroup"
          aria-label="Execution profile"
        >
          {options.profiles.map((profile) => (
            <ProfileChip
              key={profile.name}
              name={profile.name}
              label={PROFILE_LABELS[profile.name] ?? profile.name}
              hint={PROFILE_HINTS[profile.name]}
              selected={value.profile === profile.name}
              onSelect={() => onChange({ ...value, profile: profile.name })}
            />
          ))}
          <ProfileChip
            name="custom"
            label="Custom"
            hint="Pick provider & model"
            selected={value.profile === "custom"}
            onSelect={() => onChange({ ...value, profile: "custom" })}
          />
        </div>
      </div>

      {value.profile === "custom" ? (
        <div className="flex flex-wrap gap-3">
          <div className="w-full sm:w-52">
            <label
              htmlFor="llm-provider"
              className="mb-1 block text-xs text-ink-dim"
            >
              AI Provider
            </label>
            <select
              id="llm-provider"
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
              className="field"
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
          <div className="w-full sm:w-52">
            <label htmlFor="llm-model" className="mb-1 block text-xs text-ink-dim">
              Model
            </label>
            <select
              id="llm-model"
              value={value.model}
              onChange={(e) => onChange({ ...value, model: e.target.value })}
              className="field"
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
          <p className="text-xs text-ink-dim">
            {Object.entries(activeProfile.phases)
              .filter(([phase]) => ["planning", "coding", "summarize"].includes(phase))
              .map(([phase, spec]) => `${phase}: ${spec}`)
              .join(" · ")}
          </p>
        )
      )}

      <div className="flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <span>
          <span className="text-ink-dim">Estimated Cost:</span>{" "}
          <span className="font-medium text-ink">
            {value.profile === "custom"
              ? "varies by usage"
              : activeProfile?.estimated_cost_usd != null
                ? `~$${activeProfile.estimated_cost_usd.toFixed(2)}`
                : "unknown"}
          </span>
        </span>
        <span>
          <span className="text-ink-dim">Estimated Latency:</span>{" "}
          <span className="font-medium text-ink">
            {value.profile === "custom"
              ? "—"
              : activeProfile
                ? `~${Math.round(activeProfile.estimated_latency_seconds)}s`
                : "—"}
          </span>
        </span>
      </div>
    </fieldset>
  );
}
