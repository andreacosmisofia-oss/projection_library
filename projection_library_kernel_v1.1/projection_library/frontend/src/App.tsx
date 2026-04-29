import { Navigate, Route, Routes } from 'react-router-dom'

import { ProjectsListPage } from '@/pages/ProjectsListPage'

function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/projects" replace />} />
      <Route path="/projects" element={<ProjectsListPage />} />
      <Route path="*" element={<Navigate to="/projects" replace />} />
    </Routes>
  )
}

export default App
