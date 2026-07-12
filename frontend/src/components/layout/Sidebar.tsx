import React, { useEffect, useState } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { useAuthStore } from '../../store/authStore';
import client, { API_URL } from '../../api/client';
import {
  MessageSquare,
  Folder,
  Upload,
  Database,
  Settings,
  TrendingUp,
  LogOut,
  Crown,
  User,
} from 'lucide-react';

interface SystemMetrics {
  docs: number;
  users: number;
  roles: number;
  tables: number;
}

export default function Sidebar() {
  const { username, role, logout } = useAuthStore();
  const navigate = useNavigate();
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [apiOnline, setApiOnline] = useState<boolean>(false);

  // Check API health
  useEffect(() => {
    const checkHealth = async () => {
      try {
        const res = await fetch(`${API_URL}/`, { method: 'GET' });
        setApiOnline(res.status === 200);
      } catch (e) {
        setApiOnline(false);
      }
    };
    checkHealth();
    const interval = setInterval(checkHealth, 15000);
    return () => clearInterval(interval);
  }, []);

  // Fetch metrics if C-Level
  useEffect(() => {
    if (role?.toLowerCase() !== 'c-level') return;

    const fetchMetrics = async () => {
      try {
        const res = await client.get('/system-metrics');
        setMetrics(res.data);
      } catch (e) {
        console.error('Failed to fetch sidebar system metrics', e);
      }
    };

    fetchMetrics();
    const interval = setInterval(fetchMetrics, 30000);
    return () => clearInterval(interval);
  }, [role]);

  const handleSignOut = () => {
    logout();
    navigate('/login');
  };

  // Define nav links based on role
  const isCLevel = role?.toLowerCase() === 'c-level';

  const getRoleColor = (r: string | null) => {
    if (!r) return 'var(--role-general)';
    const clean = r.toLowerCase();
    if (clean === 'c-level') return 'var(--role-clevel)';
    if (clean === 'hr') return 'var(--role-hr)';
    if (clean === 'finance') return 'var(--role-finance)';
    if (clean === 'engineering') return 'var(--role-engineering)';
    if (clean === 'marketing') return 'var(--role-marketing)';
    return 'var(--role-general)';
  };

  return (
    <aside style={sidebarStyle}>
      {/* Brand logo header */}
      <div style={logoContainerStyle}>
        <div style={logoIconStyle}>📊</div>
        <span style={logoTextStyle}>
          Fin<span style={{ color: 'var(--primary-hover)' }}>Sight</span>
        </span>
      </div>

      {/* User Card */}
      <div style={userCardStyle}>
        <div style={userAvatarStyle(getRoleColor(role))}>
          {role?.toLowerCase() === 'c-level' ? (
            <Crown size={16} color={getRoleColor(role)} />
          ) : (
            <User size={16} color={getRoleColor(role)} />
          )}
        </div>
        <div style={{ overflow: 'hidden', flex: 1 }}>
          <div style={usernameStyle} title={username || 'User'}>
            {username}
          </div>
          <div style={roleBadgeStyle(getRoleColor(role))}>{role}</div>
        </div>
      </div>

      {/* Navigation Links */}
      <nav style={navContainerStyle}>
        <NavLink
          to="/chat"
          style={({ isActive }) => navLinkStyle(isActive)}
        >
          <MessageSquare size={18} />
          <span>AI Chat</span>
        </NavLink>

        <NavLink
          to="/explorer"
          style={({ isActive }) => navLinkStyle(isActive)}
        >
          <Folder size={18} />
          <span>Explorer</span>
        </NavLink>

        {isCLevel && (
          <>
            <div style={navDividerTextStyle}>Management</div>
            <NavLink
              to="/upload"
              style={({ isActive }) => navLinkStyle(isActive)}
            >
              <Upload size={18} />
              <span>Upload Docs</span>
            </NavLink>

            <NavLink
              to="/kb-indexing"
              style={({ isActive }) => navLinkStyle(isActive)}
            >
              <Database size={18} />
              <span>KB Indexing</span>
            </NavLink>

            <NavLink
              to="/admin"
              style={({ isActive }) => navLinkStyle(isActive)}
            >
              <Settings size={18} />
              <span>Admin Panel</span>
            </NavLink>

            <NavLink
              to="/evaluation"
              style={({ isActive }) => navLinkStyle(isActive)}
            >
              <TrendingUp size={18} />
              <span>Evaluation</span>
            </NavLink>
          </>
        )}
      </nav>

      {/* Sidebar Metrics (C-Level Only) */}
      {isCLevel && metrics && (
        <div style={metricsContainerStyle}>
          <div className="fs-metric-card-grid">
            <div className="fs-metric-card-small">
              <span className="fs-metric-label-small">Docs</span>
              <div className="fs-metric-value-small" style={{ color: 'var(--primary-hover)' }}>{metrics.docs}</div>
            </div>
            <div className="fs-metric-card-small">
              <span className="fs-metric-label-small">Users</span>
              <div className="fs-metric-value-small" style={{ color: '#10B981' }}>{metrics.users}</div>
            </div>
            <div className="fs-metric-card-small">
              <span className="fs-metric-label-small">Roles</span>
              <div className="fs-metric-value-small" style={{ color: '#F59E0B' }}>{metrics.roles}</div>
            </div>
            <div className="fs-metric-card-small">
              <span className="fs-metric-label-small">Tables</span>
              <div className="fs-metric-value-small" style={{ color: '#A78BFA' }}>{metrics.tables}</div>
            </div>
          </div>
        </div>
      )}

      {/* Sign Out & API Indicator Footer */}
      <div style={footerStyle}>
        <button className="fs-btn fs-btn-secondary" style={signOutBtnStyle} onClick={handleSignOut}>
          <LogOut size={14} />
          <span>Sign Out</span>
        </button>

        <div className="fs-online-indicator" style={{ marginTop: '14px' }}>
          <span className={`fs-dot ${apiOnline ? 'fs-dot-online' : 'fs-dot-offline'}`}></span>
          <span>API {apiOnline ? 'online' : 'offline'}</span>
        </div>
      </div>
    </aside>
  );
}

// Inline Styles to guarantee layout without Tailwind conflicts
const sidebarStyle: React.CSSProperties = {
  width: '260px',
  background: 'rgba(10, 12, 30, 0.95)',
  borderRight: '1px solid var(--border)',
  display: 'flex',
  flexDirection: 'column',
  height: '100vh',
  padding: '24px 18px',
  flexShrink: 0,
};

const logoContainerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '10px',
  justifyContent: 'center',
  marginBottom: '26px',
};

const logoIconStyle: React.CSSProperties = {
  width: '36px',
  height: '36px',
  borderRadius: '10px',
  background: 'linear-gradient(135deg, var(--primary), var(--secondary))',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  fontSize: '18px',
  boxShadow: '0 4px 12px rgba(99,102,241,0.3)',
};

const logoTextStyle: React.CSSProperties = {
  fontSize: '20px',
  fontWeight: 800,
  letterSpacing: '-0.03em',
  color: '#ffffff',
};

const userCardStyle: React.CSSProperties = {
  background: 'rgba(5, 7, 20, 0.5)',
  border: '1px solid rgba(255, 255, 255, 0.05)',
  borderRadius: '12px',
  padding: '12px',
  display: 'flex',
  alignItems: 'center',
  gap: '12px',
  marginBottom: '24px',
};

const userAvatarStyle = (color: string): React.CSSProperties => ({
  width: '36px',
  height: '36px',
  borderRadius: '10px',
  background: `rgba(99, 102, 241, 0.05)`,
  border: `1px solid ${color}`,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  flexShrink: 0,
});

const usernameStyle: React.CSSProperties = {
  fontSize: '13.5px',
  fontWeight: 700,
  color: '#F8FAFC',
  overflow: 'hidden',
  textOverflow: 'ellipsis',
  whiteSpace: 'nowrap',
};

const roleBadgeStyle = (color: string): React.CSSProperties => ({
  fontSize: '10px',
  fontWeight: 700,
  color: color,
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
  marginTop: '2px',
});

const navContainerStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: '4px',
  flex: 1,
  overflowY: 'auto',
};

const navLinkStyle = (isActive: boolean): React.CSSProperties => ({
  display: 'flex',
  alignItems: 'center',
  gap: '12px',
  padding: '10px 14px',
  borderRadius: 'var(--radius-sm)',
  color: isActive ? '#ffffff' : 'var(--text-secondary)',
  backgroundColor: isActive ? 'rgba(99, 102, 241, 0.15)' : 'transparent',
  border: isActive ? '1px solid rgba(99, 102, 241, 0.3)' : '1px solid transparent',
  fontSize: '14px',
  fontWeight: isActive ? 600 : 500,
  textDecoration: 'none',
  transition: 'var(--transition-smooth)',
});

const navDividerTextStyle: React.CSSProperties = {
  fontSize: '10px',
  fontWeight: 700,
  color: 'var(--text-muted)',
  textTransform: 'uppercase',
  letterSpacing: '0.1em',
  margin: '16px 0 6px 14px',
};

const metricsContainerStyle: React.CSSProperties = {
  marginTop: 'auto',
  paddingTop: '16px',
};

const footerStyle: React.CSSProperties = {
  borderTop: '1px solid rgba(255, 255, 255, 0.05)',
  paddingTop: '16px',
  marginTop: 'auto',
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
};

const signOutBtnStyle: React.CSSProperties = {
  width: '100%',
  fontSize: '13px',
  padding: '10px',
};
