/* Provider identity colors: Anthropic=purple · Google=blue · OpenAI=green ·
   Ollama=orange · OpenRouter=cyan. */

const PROVIDER_STYLES: Record<string, string> = {
  anthropic: "bg-purple-500/12 text-purple-300 ring-purple-400/25",
  google: "bg-blue-500/12 text-blue-300 ring-blue-400/25",
  openai: "bg-green-500/12 text-green-300 ring-green-400/25",
  ollama: "bg-orange-500/12 text-orange-300 ring-orange-400/25",
  openrouter: "bg-cyan-500/12 text-cyan-300 ring-cyan-400/25",
};

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: "Anthropic",
  google: "Google",
  openai: "OpenAI",
  openrouter: "OpenRouter",
  ollama: "Ollama",
};

const FALLBACK = "bg-slate-500/12 text-slate-300 ring-slate-400/20";

export function providerLabel(provider: string): string {
  return PROVIDER_LABELS[provider] ?? provider;
}

export function ProviderBadge({
  provider,
  model,
}: {
  provider: string;
  model?: string | null;
}) {
  return (
    <span
      className={`inline-flex max-w-full items-center gap-1 truncate rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${PROVIDER_STYLES[provider] ?? FALLBACK}`}
      title={model ? `${providerLabel(provider)} · ${model}` : providerLabel(provider)}
    >
      {providerLabel(provider)}
      {model && <span className="truncate font-normal opacity-75">· {model}</span>}
    </span>
  );
}
