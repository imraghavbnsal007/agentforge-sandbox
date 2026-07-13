function lineClass(line: string): string {
  if (line.startsWith("+++") || line.startsWith("---")) {
    return "text-ink-dim";
  }
  if (line.startsWith("@@")) {
    return "bg-sky-500/10 text-sky-300";
  }
  if (line.startsWith("+")) {
    return "bg-emerald-500/10 text-emerald-300";
  }
  if (line.startsWith("-")) {
    return "bg-red-500/10 text-red-300";
  }
  return "text-ink-mid";
}

export function DiffView({ diff }: { diff: string }) {
  if (!diff.trim()) {
    return <p className="px-4 py-3 text-xs text-ink-dim">No diff available.</p>;
  }
  return (
    <pre className="overflow-x-auto bg-[#07070c] p-0 text-xs leading-5">
      <code>
        {diff.replace(/\n$/, "").split("\n").map((line, i) => (
          <span key={i} className={`block px-4 ${lineClass(line)}`}>
            {line || " "}
          </span>
        ))}
      </code>
    </pre>
  );
}
