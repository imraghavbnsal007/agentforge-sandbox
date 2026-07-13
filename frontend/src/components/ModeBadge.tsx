import { ProviderBadge } from "@/components/ProviderBadge";

export function ModeBadge({
  mode,
  model,
  provider,
}: {
  mode: "mock" | "llm";
  model?: string;
  provider?: string;
}) {
  if (mode === "llm") {
    if (provider) return <ProviderBadge provider={provider} model={model} />;
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-violet-500/12 px-2.5 py-0.5 text-xs font-medium text-violet-300 ring-1 ring-inset ring-violet-400/25">
        ✦ llm{model ? ` · ${model}` : ""}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full bg-slate-500/12 px-2.5 py-0.5 text-xs font-medium text-slate-400 ring-1 ring-inset ring-slate-400/20">
      mock
    </span>
  );
}
