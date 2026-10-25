import { Route, Routes } from 'react-router-dom'
import AppShell from './components/AppShell'
import AuthorPage from './pages/AuthorPage'
import AuthorsPage from './pages/AuthorsPage'
import MethodologyPage from './pages/MethodologyPage'
import NetworkPage from './pages/NetworkPage'
import NotFoundPage from './pages/NotFoundPage'
import OverviewPage from './pages/OverviewPage'
import PaperPage from './pages/PaperPage'
import PapersPage from './pages/PapersPage'

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<OverviewPage />} />
        <Route path="papers" element={<PapersPage />} />
        <Route path="papers/*" element={<PaperPage />} />
        <Route path="authors" element={<AuthorsPage />} />
        <Route path="authors/:stableId" element={<AuthorPage />} />
        <Route path="network" element={<NetworkPage />} />
        <Route path="methodology" element={<MethodologyPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
