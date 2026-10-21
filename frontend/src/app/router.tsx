import { createBrowserRouter } from 'react-router'
import { AppShell } from '@/components/layout/AppShell'
import { HomePage } from '@/features/home/HomePage'
import { NotFoundPage } from '@/features/home/NotFoundPage'

// Every page renders inside AppShell, so site-wide layout lives in one place.
export const router = createBrowserRouter([
  {
    element: <AppShell />,
    children: [
      { index: true, element: <HomePage /> },
      { path: '*', element: <NotFoundPage /> },
    ],
  },
])
