import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import DashboardPage from './pages/DashboardPage'
import DocumentUploadPage from './pages/DocumentUploadPage'
import ReviewPage from './pages/ReviewPage'
import ConsultationPage from './pages/ConsultationPage'
import EvalPage from './pages/EvalPage'
import useAuth from './hooks/useAuth'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isLoggedIn } = useAuth()
  if (!isLoggedIn) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/" element={
        <ProtectedRoute>
          <Layout />
        </ProtectedRoute>
      }>
        <Route index element={<DashboardPage />} />
        <Route path="upload" element={<DocumentUploadPage />} />
        <Route path="review/:taskId" element={<ReviewPage />} />
        <Route path="consult/:documentId" element={<ConsultationPage />} />
        <Route path="eval" element={<EvalPage />} />
      </Route>
    </Routes>
  )
}
