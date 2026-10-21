import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

/** Consistent page width and side padding. Change site width here, not per page. */
export function PageContainer({ className, ...props }: ComponentProps<'div'>) {
  return <div className={cn('mx-auto w-full max-w-5xl px-4 py-8', className)} {...props} />
}
