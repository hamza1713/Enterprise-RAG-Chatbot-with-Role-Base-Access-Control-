import React, { useState, useEffect } from 'react';
import client from '../api/client';
import { UserPlus, ShieldAlert, CheckCircle, AlertCircle } from 'lucide-react';

export default function AdminPage() {
  // Create System User Form
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [selectedRole, setSelectedRole] = useState('');
  const [roles, setRoles] = useState<string[]>([]);
  const [userLoading, setUserLoading] = useState(false);
  const [userSuccess, setUserSuccess] = useState<string | null>(null);
  const [userError, setUserError] = useState<string | null>(null);

  // Add Security Role Form
  const [newRoleName, setNewRoleName] = useState('');
  const [roleLoading, setRoleLoading] = useState(false);
  const [roleSuccess, setRoleSuccess] = useState<string | null>(null);
  const [roleError, setRoleError] = useState<string | null>(null);

  const fetchRoles = async () => {
    try {
      const res = await client.get('/roles');
      setRoles(res.data.roles);
      if (res.data.roles.length > 0 && !selectedRole) {
        setSelectedRole(res.data.roles[0]);
      }
    } catch (e) {
      console.error('Failed to fetch roles', e);
    }
  };

  useEffect(() => {
    fetchRoles();
  }, []);

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim() || !selectedRole) {
      setUserError('All fields are required.');
      return;
    }

    setUserLoading(true);
    setUserSuccess(null);
    setUserError(null);

    const formData = new FormData();
    formData.append('username', username.trim());
    formData.append('password', password.trim());
    formData.append('role', selectedRole);

    try {
      const res = await client.post('/create-user', formData);
      setUserSuccess(res.data.message || `User '${username}' created successfully!`);
      setUsername('');
      setPassword('');
    } catch (e: any) {
      console.error('Failed to create user', e);
      setUserError(e.response?.data?.detail || 'Failed to create user. Check if username is taken.');
    } finally {
      setUserLoading(false);
    }
  };

  const handleAddRole = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newRoleName.trim()) {
      setRoleError('Role name is required.');
      return;
    }

    setRoleLoading(true);
    setRoleSuccess(null);
    setRoleError(null);

    const formData = new FormData();
    formData.append('role_name', newRoleName.trim());

    try {
      const res = await client.post('/create-role', formData);
      setRoleSuccess(res.data.message || `Role '${newRoleName}' added successfully!`);
      setNewRoleName('');
      // Reload roles dropdown
      fetchRoles();
    } catch (e: any) {
      console.error('Failed to add role', e);
      setRoleError(e.response?.data?.detail || 'Failed to add role. Check if role already exists.');
    } finally {
      setRoleLoading(false);
    }
  };

  return (
    <div>
      {/* Header */}
      <div className="fs-header">
        <h1 className="fs-title">⚙️ Administrative Controls</h1>
        <p className="fs-subtitle">Manage system users, passwords, and security roles mapping.</p>
      </div>

      <div style={gridStyle}>
        {/* Create User Card */}
        <div className="fs-card" style={cardStyle}>
          <div style={cardTitleContainerStyle}>
            <UserPlus size={20} color="var(--primary)" />
            <h2 style={cardTitleStyle}>Create system user</h2>
          </div>
          <p style={cardSubtitleStyle}>Add a new user credential to the SQLite database with role assignments.</p>

          <form onSubmit={handleCreateUser} style={formStyle}>
            {userError && (
              <div style={errorBannerStyle}>
                <AlertCircle size={15} />
                <span>{userError}</span>
              </div>
            )}
            {userSuccess && (
              <div style={successBannerStyle}>
                <CheckCircle size={15} />
                <span>{userSuccess}</span>
              </div>
            )}

            <div style={inputGroupStyle}>
              <label style={labelStyle}>Username</label>
              <input
                type="text"
                className="fs-input"
                placeholder="Enter username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                disabled={userLoading}
                required
              />
            </div>

            <div style={inputGroupStyle}>
              <label style={labelStyle}>Password</label>
              <input
                type="password"
                className="fs-input"
                placeholder="Enter password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={userLoading}
                required
              />
            </div>

            <div style={inputGroupStyle}>
              <label style={labelStyle}>Security Access Role</label>
              <select
                className="fs-input"
                value={selectedRole}
                onChange={(e) => setSelectedRole(e.target.value)}
                disabled={userLoading}
              >
                {roles.map((r, idx) => (
                  <option key={idx} value={r}>{r}</option>
                ))}
              </select>
            </div>

            <button
              type="submit"
              className="fs-btn fs-btn-primary"
              disabled={userLoading || roles.length === 0}
              style={{ marginTop: '10px' }}
            >
              <span>{userLoading ? 'Creating User...' : 'Create User'}</span>
            </button>
          </form>
        </div>

        {/* Create Role Card */}
        <div className="fs-card" style={cardStyle}>
          <div style={cardTitleContainerStyle}>
            <ShieldAlert size={20} color="var(--secondary)" />
            <h2 style={cardTitleStyle}>Add security role</h2>
          </div>
          <p style={cardSubtitleStyle}>Define a new organizational security department (e.g. Legal, Compliance).</p>

          <form onSubmit={handleAddRole} style={formStyle}>
            {roleError && (
              <div style={errorBannerStyle}>
                <AlertCircle size={15} />
                <span>{roleError}</span>
              </div>
            )}
            {roleSuccess && (
              <div style={successBannerStyle}>
                <CheckCircle size={15} />
                <span>{roleSuccess}</span>
              </div>
            )}

            <div style={inputGroupStyle}>
              <label style={labelStyle}>Role Name</label>
              <input
                type="text"
                className="fs-input"
                placeholder="e.g. Legal, Operations"
                value={newRoleName}
                onChange={(e) => setNewRoleName(e.target.value)}
                disabled={roleLoading}
                required
              />
            </div>

            <button
              type="submit"
              className="fs-btn fs-btn-secondary"
              disabled={roleLoading || !newRoleName.trim()}
              style={{ marginTop: '10px' }}
            >
              <span>{roleLoading ? 'Adding Role...' : 'Add Security Role'}</span>
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

// Inline CSS for Admin Page Layout
const gridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '1fr 1fr',
  gap: '24px',
  alignItems: 'start',
};

const cardStyle: React.CSSProperties = {
  padding: '28px 24px',
};

const cardTitleContainerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '12px',
  marginBottom: '6px',
};

const cardTitleStyle: React.CSSProperties = {
  fontSize: '16px',
  fontWeight: 700,
  color: '#ffffff',
  margin: 0,
};

const cardSubtitleStyle: React.CSSProperties = {
  fontSize: '12px',
  color: 'var(--text-muted)',
  marginBottom: '20px',
};

const formStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: '18px',
};

const inputGroupStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: '6px',
};

const labelStyle: React.CSSProperties = {
  fontSize: '11px',
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
  color: 'var(--text-secondary)',
};

const errorBannerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '8px',
  background: 'rgba(239, 68, 68, 0.15)',
  border: '1px solid rgba(239, 68, 68, 0.3)',
  color: '#FCA5A5',
  padding: '10px 14px',
  borderRadius: 'var(--radius-sm)',
  fontSize: '12.5px',
};

const successBannerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '8px',
  background: 'rgba(16, 185, 129, 0.15)',
  border: '1px solid rgba(16, 185, 129, 0.3)',
  color: '#34D399',
  padding: '10px 14px',
  borderRadius: 'var(--radius-sm)',
  fontSize: '12.5px',
};
