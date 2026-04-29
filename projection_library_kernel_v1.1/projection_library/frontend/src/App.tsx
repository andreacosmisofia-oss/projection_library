import { Navigate, Route, Routes } from 'react-router-dom'

import { ProjectDashboardPage } from '@/pages/ProjectDashboardPage'
import { ProjectsListPage } from '@/pages/ProjectsListPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/projects" replace />} />
      <Route path="/projects" element={<ProjectsListPage />} />
      <Route path="/projects/:projectId" element={<ProjectDashboardPage />} />
      <Route path="*" element={<Navigate to="/projects" replace />} />
    </Routes>
  )
}

export default App
