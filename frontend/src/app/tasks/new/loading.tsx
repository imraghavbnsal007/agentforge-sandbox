import { Skeleton } from "@/components/ui/Skeleton";

export default function Loading() {
  return (
    <div className="mx-auto max-w-2xl space-y-5">
      <Skeleton className="h-4 w-36" />
      <Skeleton className="h-7 w-40" />
      <Skeleton className="h-4 w-80 max-w-full" />
      <Skeleton className="h-[28rem] w-full rounded-2xl" />
    </div>
  );
}
