const PROVIDER_LABELS: Record<string, string> = {
  anthropic: "Anthropic",
  google: "Google Gemini",
  openai: "OpenAI",
  openrouter: "OpenRouter",
  ollama: "Ollama",
};

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
    const label = provider ? (PROVIDER_LABELS[provider] ?? provider) : "llm";
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-violet-100 px-2.5 py-0.5 text-xs font-medium text-violet-700">
        ✦ {label}
        {model ? ` · ${model}` : ""}
      </span>
    );
  }
  return (
    <span className="inline-flex items-center rounded-full bg-slate-100 px-2.5 py-0.5 text-xs font-medium text-slate-600">
      mock
    </span>
  );
}
