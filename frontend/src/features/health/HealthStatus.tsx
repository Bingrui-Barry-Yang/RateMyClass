import { useHealth } from '@/features/health/api'

function StatusRow({ label, ok }: { label: string; ok: boolean }) {
  return (
    <li className="flex items-center justify-between gap-4">
      <span>{label}</span>
      <span className={ok ? 'text-foreground' : 'text-destructive'}>
        {ok ? 'ok' : 'unavailable'}
      </span>
    </li>
  )
}

export function HealthStatus() {
  const { data, isPending, isError } = useHealth()

  if (isPending) return <p className="text-muted-foreground">Checking backend…</p>

  return (
    <ul className="max-w-xs space-y-1 rounded-lg border p-4 text-sm">
      <StatusRow label="Backend" ok={!isError} />
      <StatusRow label="Database" ok={data?.db === 'ok'} />
    </ul>
  )
}
