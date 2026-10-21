import { PageContainer } from '@/components/layout/PageContainer'
import { HealthStatus } from '@/features/health/HealthStatus'

export function HomePage() {
  return (
    <PageContainer className="space-y-6">
      <div className="space-y-2">
        <h1 className="font-heading text-3xl font-semibold">RateMyClassOxy</h1>
        <p className="text-muted-foreground">
          Find honest reviews of Occidental College courses and professors.
        </p>
      </div>
      <HealthStatus />
    </PageContainer>
  )
}
