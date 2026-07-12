import React, { useState } from 'react';
import { useNavigate, Navigate } from 'react-router-dom';
import { useAuthStore } from '../store/authStore';

export default function LoginPage() {
  const [usernameInput, setUsernameInput] = useState('');
  const [passwordInput, setPasswordInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const login = useAuthStore((state) => state.login);
  const isAuthenticated = useAuthStore((state) => state.isAuthenticated);
  const navigate = useNavigate();

  // Already logged in — skip login page entirely
  if (isAuthenticated) {
    return <Navigate to="/chat" replace />;
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!usernameInput.trim() || !passwordInput.trim()) {
      setErrorMsg('Please enter both username and password.');
      return;
    }

    setLoading(true);
    setErrorMsg(null);

    try {
      await login(usernameInput, passwordInput);
      navigate('/chat');
    } catch (err: any) {
      console.error('Login failed', err);
      if (err.response && err.response.status === 401) {
        setErrorMsg('Invalid username or password.');
      } else if (err.code === 'ERR_NETWORK') {
        setErrorMsg('🔌 Connection failed. Backend server is offline.');
      } else {
        setErrorMsg(err.response?.data?.detail || 'Unexpected error occurred. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={containerStyle}>
      {/* Glow blobs for premium aesthetics */}
      <div style={glowBlob1Style} />
      <div style={glowBlob2Style} />

      <div className="fs-card" style={loginCardStyle}>
        {/* Brand Header */}
        <div style={{ textAlign: 'center', marginBottom: '28px' }}>
          <div style={logoContainerStyle}>
            <div style={logoIconStyle}>📊</div>
            <span style={logoTextStyle}>
              Fin<span style={{ color: 'var(--primary-hover)' }}>Sight</span>
            </span>
          </div>
          <p style={subtitleStyle}>Role-Based AI Workspace</p>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} style={formStyle}>
          {errorMsg && (
            <div style={errorBannerStyle}>
              {errorMsg}
            </div>
          )}

          <div style={inputGroupStyle}>
            <label style={labelStyle}>Username</label>
            <input
              type="text"
              className="fs-input"
              placeholder="Enter your username"
              value={usernameInput}
              onChange={(e) => setUsernameInput(e.target.value)}
              disabled={loading}
              required
            />
          </div>

          <div style={inputGroupStyle}>
            <label style={labelStyle}>Password</label>
            <input
              type="password"
              className="fs-input"
              placeholder="Enter your password"
              value={passwordInput}
              onChange={(e) => setPasswordInput(e.target.value)}
              disabled={loading}
              required
            />
          </div>

          <button
            type="submit"
            className="fs-btn fs-btn-primary"
            style={{ width: '100%', marginTop: '10px' }}
            disabled={loading}
          >
            {loading ? 'Signing In...' : 'Sign In →'}
          </button>
        </form>

        <div style={footerStyle}>
          🔒 Secured with JWT Authentication
        </div>
      </div>
    </div>
  );
}

// Custom inline CSS to guarantee beautiful layout without Tailwind issues
const containerStyle: React.CSSProperties = {
  minHeight: '100vh',
  width: '100vw',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  background: 'radial-gradient(circle at center, #0f1235 0%, #050716 100%)',
  position: 'relative',
  overflow: 'hidden',
  padding: '20px',
};

const glowBlob1Style: React.CSSProperties = {
  position: 'absolute',
  top: '20%',
  left: '25%',
  width: '350px',
  height: '350px',
  background: 'rgba(99, 102, 241, 0.12)',
  borderRadius: '50%',
  filter: 'blur(80px)',
  zIndex: 0,
};

const glowBlob2Style: React.CSSProperties = {
  position: 'absolute',
  bottom: '20%',
  right: '25%',
  width: '350px',
  height: '350px',
  background: 'rgba(139, 92, 246, 0.12)',
  borderRadius: '50%',
  filter: 'blur(80px)',
  zIndex: 0,
};

const loginCardStyle: React.CSSProperties = {
  width: '100%',
  maxWidth: '420px',
  position: 'relative',
  zIndex: 1,
  padding: '40px 32px',
};

const logoContainerStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: '12px',
  marginBottom: '6px',
};

const logoIconStyle: React.CSSProperties = {
  width: '46px',
  height: '46px',
  borderRadius: '14px',
  background: 'linear-gradient(135deg, var(--primary), var(--secondary))',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  fontSize: '22px',
  boxShadow: '0 4px 18px rgba(99, 102, 241, 0.35)',
};

const logoTextStyle: React.CSSProperties = {
  fontSize: '26px',
  fontWeight: 800,
  letterSpacing: '-0.03em',
  color: '#ffffff',
};

const subtitleStyle: React.CSSProperties = {
  fontSize: '12.5px',
  color: 'var(--text-muted)',
  fontStyle: 'italic',
};

const formStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: '20px',
};

const errorBannerStyle: React.CSSProperties = {
  background: 'rgba(239, 68, 68, 0.15)',
  border: '1px solid rgba(239, 68, 68, 0.3)',
  color: '#FCA5A5',
  padding: '12px',
  borderRadius: 'var(--radius-sm)',
  fontSize: '13px',
  lineHeight: 1.5,
  textAlign: 'center',
};

const inputGroupStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: '6px',
};

const labelStyle: React.CSSProperties = {
  fontSize: '11.5px',
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
  color: 'var(--text-secondary)',
};

const footerStyle: React.CSSProperties = {
  textAlign: 'center',
  marginTop: '24px',
  fontSize: '11px',
  color: 'var(--text-muted)',
};
