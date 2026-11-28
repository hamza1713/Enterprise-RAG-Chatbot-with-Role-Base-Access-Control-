import React, { lazy, Suspense, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useAuthStore } from './store/authStore';
import AppLayout from './components/layout/AppLayout';

// Pages
import LoginPage from './pages/LoginPage';
const ChatPage = lazy(() => import('./pages/ChatPage'));
const ExplorerPage = lazy(() => import('./pages/ExplorerPage'));
const UploadPage = lazy(() => import('./pages/UploadPage'));
const KbIndexingPage = lazy(() => import('./pages/KbIndexingPage'));
const AdminPage = lazy(() => import('./pages/AdminPage'));
const EvaluationPage = lazy(() => import('./pages/EvaluationPage'));

// Auth Guard component
function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, authReady } = useAuthStore();
  if (!authReady) {
    return <div className="fs-empty-state" role="status">Checking session…</div>;
  }
  return isAuthenticated ? <>{children}</> : <Navigate to="/login" replace />;
}

// Role-based C-Level authorization guard
function CLevelRoute({ children }: { children: React.ReactNode }) {
  const { isAuthenticated, authReady, role } = useAuthStore();
  if (!authReady) {
    return <div className="fs-empty-state" role="status">Checking session…</div>;
  }
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  const isCLevel = role?.toLowerCase() === 'c-level';
  return isCLevel ? <>{children}</> : <Navigate to="/chat" replace />;
}

export default function App() {
  const hydrateSession = useAuthStore((s) => s.hydrateSession);
  const clearLocalSession = useAuthStore((s) => s.clearLocalSession);

  useEffect(() => {
    void hydrateSession();
    const onUnauthorized = () => clearLocalSession();
    window.addEventListener('finsight:unauthorized', onUnauthorized);
    return () => window.removeEventListener('finsight:unauthorized', onUnauthorized);
  }, [hydrateSession, clearLocalSession]);

  return (
    <BrowserRouter>
      <Suspense fallback={<div className="fs-empty-state" role="status">Opening your workspace…</div>}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />

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

          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}
