import { Link } from 'react-router'
import { PageContainer } from '@/components/layout/PageContainer'
import { Button } from '@/components/ui/button'

export function NotFoundPage() {
  return (
    <PageContainer className="space-y-4">
      <h1 className="font-heading text-2xl font-semibold">Page not found</h1>
      <Button asChild>
        <Link to="/">Back to home</Link>
      </Button>
    </PageContainer>
  )
}
