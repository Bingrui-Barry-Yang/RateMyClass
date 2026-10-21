import { Link } from 'react-router'
import { PageContainer } from '@/components/layout/PageContainer'

export function SiteHeader() {
  return (
    <header className="border-b">
      <PageContainer className="flex h-14 items-center justify-between py-0">
        <Link to="/" className="font-heading text-lg font-semibold">
          RateMyClassOxy
        </Link>
      </PageContainer>
    </header>
  )
}
