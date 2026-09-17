// Скелетоны повторяют геометрию будущего контента (DESIGN_SPEC 4.3).

function Bar({ w, h = 14, className = '' }: { w: number | string; h?: number; className?: string }) {
  return <span className={`skeleton block ${className}`} style={{ width: w, height: h }} />;
}

export function HomeSkeleton() {
  return (
    <div className="skeleton-wrap px-4 pt-5">
      <Bar w={110} h={14} />
      <Bar w={180} h={40} className="mt-3" />
      <Bar w={132} h={36} className="mt-3 rounded-full" />
      {[0, 1].map((i) => (
        <div key={i} className="mt-6">
          <Bar w={96} h={22} />
          <div className="mt-3 rounded-card bg-card p-4">
            {[0, 1, 2].map((r) => (
              <div key={r} className="flex items-center gap-3 py-2">
                <span className="skeleton block h-11 w-11 rounded-full" />
                <span className="flex-1">
                  <Bar w={120} h={16} />
                  <Bar w={80} h={12} className="mt-1.5" />
                </span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export function FeedSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div className="skeleton-wrap rounded-card bg-card p-4">
      {Array.from({ length: rows }, (_, r) => (
        <div key={r} className="flex items-center gap-3 py-2">
          <span className="skeleton block h-10 w-10 rounded-full" />
          <span className="flex-1">
            <Bar w={120} h={14} />
            <Bar w={80} h={12} className="mt-1.5" />
          </span>
          <Bar w={70} h={14} />
        </div>
      ))}
    </div>
  );
}

export function AnalyticsSkeleton() {
  return (
    <div className="skeleton-wrap px-4 pt-5">
      <Bar w={160} h={22} className="mx-auto" />
      <Bar w={150} h={32} className="mt-6" />
      <span className="skeleton mx-auto mt-6 block h-[200px] w-[200px] rounded-full" />
      <div className="mt-6 grid grid-cols-2 gap-2">
        {Array.from({ length: 6 }, (_, i) => (
          <Bar key={i} w="100%" h={34} className="rounded-full" />
        ))}
      </div>
    </div>
  );
}
