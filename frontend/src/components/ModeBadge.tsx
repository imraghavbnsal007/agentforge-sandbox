export function ModeBadge({
  mode,
  model,
}: {
  mode: "mock" | "llm";
  model?: string;
}) {
  if (mode === "llm") {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-violet-100 px-2.5 py-0.5 text-xs font-medium text-violet-700">
        ✦ llm{model ? ` · ${model}` : ""}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600">
      mock
    </span>
  );
}
