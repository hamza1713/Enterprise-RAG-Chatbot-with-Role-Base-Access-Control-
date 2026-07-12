import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useAuthStore } from './store/authStore';
import AppLayout from './components/layout/AppLayout';

// Pages
import LoginPage from './pages/LoginPage';
import ChatPage from './pages/ChatPage';
import ExplorerPage from './pages/ExplorerPage';
import UploadPage from './pages/UploadPage';
import KbIndexingPage from './pages/KbIndexingPage';
import AdminPage from './pages/AdminPage';
import EvaluationPage from './pages/EvaluationPage';

// Auth Guard component
function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  return isAuthenticated ? <>{children}</> : <Navigate to="/login" replace />;
}

// Role-based C-Level authorization guard
function CLevelRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, role } = useAuthStore();
  
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  
  const isCLevel = role?.toLowerCase() === 'c-level';
  return isCLevel ? <>{children}</> : <Navigate to="/chat" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Public Login Route */}
        <Route path="/login" element={<LoginPage />} />

        {/* Protected Dashboard Routes inside AppLayout */}
        <Route
          path="/chat"
          element={
            <ProtectedRoute>
              <AppLayout>
                <ChatPage />
              </AppLayout>
            </ProtectedRoute>
          }
        />
        
        <Route
          path="/explorer"
          element={
            <ProtectedRoute>
              <AppLayout>
                <ExplorerPage />
              </AppLayout>
            </ProtectedRoute>
          }
        />

        <Route
          path="/upload"
          element={
            <CLevelRoute>
              <AppLayout>
                <UploadPage />
              </AppLayout>
            </CLevelRoute>
          }
        />

        <Route
          path="/kb-indexing"
          element={
            <CLevelRoute>
              <AppLayout>
                <KbIndexingPage />
              </AppLayout>
            </CLevelRoute>
          }
        />

        <Route
          path="/admin"
          element={
            <CLevelRoute>
              <AppLayout>
                <AdminPage />
              </AppLayout>
            </CLevelRoute>
          }
        />

        <Route
          path="/evaluation"
          element={
            <CLevelRoute>
              <AppLayout>
                <EvaluationPage />
              </AppLayout>
            </CLevelRoute>
          }
        />

        {/* Catch-all: send to login — ProtectedRoute forwards authed users onward */}
        <Route path="*" element={<Navigate to="/login" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
