import type { RepoMapNode } from "@/lib/api";

function Node({ node, depth }: { node: RepoMapNode; depth: number }) {
  return (
    <li>
      <span
        className={
          depth === 0
            ? "text-sm font-semibold text-ink"
            : "font-mono text-xs text-ink-mid"
        }
      >
        {node.name}
      </span>
      {node.children && node.children.length > 0 && (
        <ul className="ml-4 mt-1 space-y-0.5 border-l border-line pl-3">
          {node.children.map((child, i) => (
            <Node key={`${child.name}-${i}`} node={child} depth={depth + 1} />
          ))}
        </ul>
      )}
    </li>
  );
}

export function RepoMapTree({ nodes }: { nodes: RepoMapNode[] }) {
  return (
    <ul className="space-y-3 px-5 py-4">
      {nodes.map((node, i) => (
        <Node key={`${node.name}-${i}`} node={node} depth={0} />
      ))}
    </ul>
  );
}
