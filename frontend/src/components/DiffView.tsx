function lineClass(line: string): string {
  if (line.startsWith("+++") || line.startsWith("---")) {
    return "text-slate-400";
  }
  if (line.startsWith("@@")) {
    return "bg-sky-950/60 text-sky-300";
  }
  if (line.startsWith("+")) {
    return "bg-emerald-950/60 text-emerald-300";
  }
  if (line.startsWith("-")) {
    return "bg-red-950/60 text-red-300";
  }
  return "text-slate-300";
}

export function DiffView({ diff }: { diff: string }) {
  if (!diff.trim()) {
    return <p className="px-4 py-3 text-xs text-slate-400">No diff available.</p>;
  }
  return (
    <pre className="overflow-x-auto bg-slate-900 p-0 text-xs leading-5">
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
