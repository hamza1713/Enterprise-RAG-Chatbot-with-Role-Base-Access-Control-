import React, { useState, useEffect, useCallback } from 'react';
import client from '../api/client';
import {
  deleteRole,
  deleteUser,
  fetchRoles,
  fetchUsers,
  resetUserPassword,
  updateUser,
} from '../api/admin';
import {
  fetchDocumentPermissions,
  grantDocumentPermission,
  revokeDocumentPermission,
} from '../api/documents';
import {
  fetchSemanticModels,
  resetSemanticModel,
  updateSemanticModel,
} from '../api/semantic';
import { useAuthStore } from '../store/authStore';
import type {
  Document,
  DocumentPermission,
  RoleDetail,
  SemanticModel,
  UserRecord,
} from '../types';
import {
  UserPlus,
  ShieldAlert,
  CheckCircle,
  AlertCircle,
  Users,
  KeyRound,
  Trash2,
  Lock,
  Share2,
  Database,
  RotateCcw,
} from 'lucide-react';

export default function AdminPage() {
  const currentUsername = useAuthStore((s) => s.username);

  // Create System User Form
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [selectedRole, setSelectedRole] = useState('');
  const [roles, setRoles] = useState<string[]>([]);
  const [roleDetails, setRoleDetails] = useState<RoleDetail[]>([]);
  const [userLoading, setUserLoading] = useState(false);
  const [userSuccess, setUserSuccess] = useState<string | null>(null);
  const [userError, setUserError] = useState<string | null>(null);

  // Add / Manage Security Role Form
  const [newRoleName, setNewRoleName] = useState('');
  const [roleLoading, setRoleLoading] = useState(false);
  const [roleSuccess, setRoleSuccess] = useState<string | null>(null);
  const [roleError, setRoleError] = useState<string | null>(null);
  const [confirmDeleteRole, setConfirmDeleteRole] = useState<string | null>(null);

  // Users Directory & Access Control
  const [usersList, setUsersList] = useState<UserRecord[]>([]);
  const [directoryLoading, setDirectoryLoading] = useState(false);
  const [dirSuccess, setDirSuccess] = useState<string | null>(null);
  const [dirError, setDirError] = useState<string | null>(null);
  const [busyUsername, setBusyUsername] = useState<string | null>(null);
  const [confirmDeleteUsername, setConfirmDeleteUsername] = useState<string | null>(null);

  // Inline Password Reset Modal State
  const [resetTargetUser, setResetTargetUser] = useState<string | null>(null);
  const [resetPasswordVal, setResetPasswordVal] = useState('');
  const [resetPasswordLoading, setResetPasswordLoading] = useState(false);

  // ReBAC Document Permissions State
  const [docsList, setDocsList] = useState<Document[]>([]);
  const [selectedDocId, setSelectedDocId] = useState<number | null>(null);
  const [docPermissions, setDocPermissions] = useState<DocumentPermission[]>([]);
  const [grantSubject, setGrantSubject] = useState('');
  const [permBanner, setPermBanner] = useState<string | null>(null);
  const [permError, setPermError] = useState<string | null>(null);

  // Semantic Layer Governance State
  const [semanticModels, setSemanticModels] = useState<SemanticModel[]>([]);
  const [selectedSemanticTable, setSelectedSemanticTable] = useState<string>('');
  const [semanticDescription, setSemanticDescription] = useState('');
  const [semanticSynonymsText, setSemanticSynonymsText] = useState('');
  const [semanticBanner, setSemanticBanner] = useState<string | null>(null);
  const [semanticError, setSemanticError] = useState<string | null>(null);

  const loadRoles = useCallback(async () => {
    try {
      const data = await fetchRoles();
      const names = data.roles || [];
      setRoles(names);
      setRoleDetails(
        data.role_details ||
          names.map((r) => ({
            role_name: r,
            is_system: r.toLowerCase() === 'c-level' || r.toLowerCase() === 'general',
          })),
      );
      if (names.length > 0) setSelectedRole((current) => current || names[0]);
    } catch (e) {
      console.error('Failed to fetch roles', e);
    }
  }, []);

  const loadUsers = useCallback(async () => {
    setDirectoryLoading(true);
    try {
      const list = await fetchUsers();
      setUsersList(list);
    } catch (e) {
      console.error('Failed to fetch users directory', e);
    } finally {
      setDirectoryLoading(false);
    }
  }, []);

  const loadGovernance = useCallback(async () => {
    try {
      const [docsRes, models] = await Promise.all([
        client.get<Document[]>('/documents'),
        fetchSemanticModels().catch(() => [] as SemanticModel[]),
      ]);
      const docs = docsRes.data || [];
      setDocsList(docs);
      if (docs.length > 0 && docs[0].id) {
        setSelectedDocId((cur) => cur ?? docs[0].id ?? null);
      }
      setSemanticModels(models);
      if (models.length > 0) {
        setSelectedSemanticTable((cur) => {
          const active = cur || models[0].table_name;
          const m = models.find((x) => x.table_name === active);
          if (m) {
            setSemanticDescription(m.description || '');
            setSemanticSynonymsText(
              Object.entries(m.synonyms || {})
                .map(([k, v]) => `${k}=${v}`)
                .join(', ')
            );
          }
          return active;
        });
      }
    } catch {
      // Governance panels remain safely empty on transient errors
    }
  }, []);

  useEffect(() => {
    void loadRoles();
    void loadUsers();
    void loadGovernance();
  }, [loadRoles, loadUsers, loadGovernance]);

  useEffect(() => {
    if (!selectedDocId) {
      setDocPermissions([]);
      return;
    }
    void fetchDocumentPermissions(selectedDocId)
      .then((res) => setDocPermissions(res.permissions || []))
      .catch(() => setDocPermissions([]));
  }, [selectedDocId]);

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password || !selectedRole) {
      setUserError('All fields are required.');
      return;
    }

    setUserLoading(true);
    setUserSuccess(null);
    setUserError(null);

    const formData = new FormData();
    formData.append('username', username.trim());
    formData.append('password', password);
    formData.append('role', selectedRole);

    try {
      const res = await client.post('/create-user', formData);
      setUserSuccess(res.data.message || `User '${username}' created successfully!`);
      setUsername('');
      setPassword('');
      void loadUsers();
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
      void loadRoles();
    } catch (e: any) {
      console.error('Failed to add role', e);
      setRoleError(e.response?.data?.detail || 'Failed to add role. Check if role already exists.');
    } finally {
      setRoleLoading(false);
    }
  };

  const handleDeleteRole = async (roleName: string) => {
    if (confirmDeleteRole !== roleName) {
      setConfirmDeleteRole(roleName);
      setRoleError(null);
      return;
    }
    setConfirmDeleteRole(null);
    setRoleSuccess(null);
    setRoleError(null);
    setRoleLoading(true);
    try {
      const res = await deleteRole(roleName);
      setRoleSuccess(res.message || `Role '${roleName}' deleted.`);
      void loadRoles();
    } catch (e: any) {
      setRoleError(e.response?.data?.detail || `Could not delete role '${roleName}'.`);
    } finally {
      setRoleLoading(false);
    }
  };

  const handleRoleChange = async (targetUser: UserRecord, newRole: string) => {
    if (newRole === targetUser.role) return;
    setBusyUsername(targetUser.username);
    setDirSuccess(null);
    setDirError(null);
    try {
      const updated = await updateUser(targetUser.username, { role: newRole });
      setUsersList((prev) =>
        prev.map((u) => (u.username === targetUser.username ? updated : u)),
      );
      setDirSuccess(`Updated '${targetUser.username}' role to '${updated.role}' and revoked previous tokens.`);
    } catch (e: any) {
      setDirError(e.response?.data?.detail || 'Failed to update user role.');
    } finally {
      setBusyUsername(null);
    }
  };

  const handleToggleActive = async (targetUser: UserRecord) => {
    setBusyUsername(targetUser.username);
    setDirSuccess(null);
    setDirError(null);
    try {
      const updated = await updateUser(targetUser.username, {
        is_active: !targetUser.is_active,
      });
      setUsersList((prev) =>
        prev.map((u) => (u.username === targetUser.username ? updated : u)),
      );
      setDirSuccess(
        updated.is_active
          ? `Reactivated account '${updated.username}'.`
          : `Deactivated account '${updated.username}' and revoked active sessions.`,
      );
    } catch (e: any) {
      setDirError(e.response?.data?.detail || 'Failed to change account status.');
    } finally {
      setBusyUsername(null);
    }
  };

  const handleDeleteUser = async (targetUsername: string) => {
    if (confirmDeleteUsername !== targetUsername) {
      setConfirmDeleteUsername(targetUsername);
      setDirError(null);
      return;
    }
    setConfirmDeleteUsername(null);
    setBusyUsername(targetUsername);
    setDirSuccess(null);
    setDirError(null);
    try {
      const res = await deleteUser(targetUsername);
      setUsersList((prev) => prev.filter((u) => u.username !== targetUsername));
      setDirSuccess(res.message || `Deleted user '${targetUsername}'.`);
    } catch (e: any) {
      setDirError(e.response?.data?.detail || 'Failed to delete user.');
    } finally {
      setBusyUsername(null);
    }
  };

  const handleResetPasswordSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!resetTargetUser || !resetPasswordVal) return;
    setResetPasswordLoading(true);
    setDirSuccess(null);
    setDirError(null);
    try {
      const res = await resetUserPassword(resetTargetUser, resetPasswordVal);
      setDirSuccess(res.message || `Password updated for '${resetTargetUser}'.`);
      setResetTargetUser(null);
      setResetPasswordVal('');
    } catch (e: any) {
      setDirError(e.response?.data?.detail || 'Password reset failed.');
    } finally {
      setResetPasswordLoading(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', paddingBottom: '32px' }}>
      {/* Header */}
      <div className="fs-header">
        <h1 className="fs-title">Administration</h1>
        <p className="fs-subtitle">
          Manage PostgreSQL user accounts, immediate JWT session revocation, and department security roles.
        </p>
      </div>

      <div style={gridStyle}>
        {/* Create User Card */}
        <div className="fs-card" style={cardStyle}>
          <div style={cardTitleContainerStyle}>
            <UserPlus size={20} color="var(--primary)" />
            <h2 style={cardTitleStyle}>Create system user</h2>
          </div>
          <p style={cardSubtitleStyle}>
            Provision a new PostgreSQL credential with role-based document and analytics access.
          </p>

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
                placeholder="At least 12 characters"
                minLength={12}
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
                  <option key={idx} value={r}>
                    {r}
                  </option>
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

        {/* Create & Manage Roles Card */}
        <div className="fs-card" style={cardStyle}>
          <div style={cardTitleContainerStyle}>
            <ShieldAlert size={20} color="var(--secondary)" />
            <h2 style={cardTitleStyle}>Security roles</h2>
          </div>
          <p style={cardSubtitleStyle}>
            Define new departments or remove unused custom roles. System roles (C-Level, General) are protected.
          </p>

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
            >
              <span>{roleLoading ? 'Adding Role...' : 'Add Security Role'}</span>
            </button>
          </form>

          {/* Existing Roles Chips */}
          <div style={{ marginTop: '20px', borderTop: '1px solid var(--border)', paddingTop: '16px' }}>
            <div style={{ ...labelStyle, marginBottom: '10px' }}>Configured Roles ({roleDetails.length})</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
              {roleDetails.map((rd) => (
                <div key={rd.role_name} style={roleChipStyle}>
                  <span>{rd.role_name}</span>
                  {rd.is_system ? (
                    <span title="Protected system role" style={{ color: 'var(--text-muted)', display: 'inline-flex' }}>
                      <Lock size={12} />
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="icon-button"
                      disabled={roleLoading}
                      onClick={() => handleDeleteRole(rd.role_name)}
                      title={
                        confirmDeleteRole === rd.role_name
                          ? `Click again to confirm deleting '${rd.role_name}'`
                          : `Delete role '${rd.role_name}'`
                      }
                      style={{
                        color: confirmDeleteRole === rd.role_name ? '#F87171' : 'var(--text-muted)',
                        padding: '2px',
                      }}
                    >
                      <Trash2 size={13} />
                    </button>
                  )}
                </div>
              ))}
            </div>
            {confirmDeleteRole && (
              <div style={{ fontSize: '11.5px', color: '#FCA5A5', marginTop: '8px' }}>
                Click the trash icon on <b>{confirmDeleteRole}</b> again to confirm deletion.
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Users Directory & Access Control */}
      <div className="fs-card" style={{ padding: '24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
          <div style={cardTitleContainerStyle}>
            <Users size={20} color="var(--primary)" />
            <h2 style={cardTitleStyle}>Users Directory & Access Control</h2>
          </div>
          <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
            {directoryLoading ? 'Refreshing…' : `${usersList.length} member(s)`}
          </span>
        </div>

        {dirError && (
          <div style={{ ...errorBannerStyle, marginBottom: '14px' }}>
            <AlertCircle size={15} />
            <span>{dirError}</span>
          </div>
        )}
        {dirSuccess && (
          <div style={{ ...successBannerStyle, marginBottom: '14px' }}>
            <CheckCircle size={15} />
            <span>{dirSuccess}</span>
          </div>
        )}

        <div className="fs-table-wrap" style={{ margin: 0 }}>
          <table className="fs-table">
            <thead>
              <tr>
                <th>Username</th>
                <th>Assigned Role</th>
                <th>Account Status</th>
                <th style={{ textAlign: 'right' }}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {usersList.length === 0 ? (
                <tr>
                  <td colSpan={4} style={{ textAlign: 'center', padding: '28px', color: 'var(--text-muted)' }}>
                    No users found.
                  </td>
                </tr>
              ) : (
                usersList.map((u) => {
                  const isSelf = u.username.toLowerCase() === (currentUsername || '').toLowerCase();
                  const isBusy = busyUsername === u.username;
                  return (
                    <tr key={u.id}>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontWeight: 600 }}>
                          <span>{u.username}</span>
                          {isSelf && <span className="fs-badge">you</span>}
                        </div>
                      </td>
                      <td>
                        <select
                          className="fs-input"
                          value={u.role}
                          disabled={isBusy || isSelf}
                          onChange={(e) => handleRoleChange(u, e.target.value)}
                          style={{ width: '160px', height: '32px', padding: '0 8px', fontSize: '12.5px' }}
                        >
                          {roles.map((r) => (
                            <option key={r} value={r}>
                              {r}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <button
                          type="button"
                          className={`fs-badge ${u.is_active ? 'fs-badge-success' : 'fs-badge-danger'}`}
                          style={{ cursor: isSelf || isBusy ? 'not-allowed' : 'pointer', border: 'none' }}
                          disabled={isBusy || isSelf}
                          onClick={() => handleToggleActive(u)}
                          title={isSelf ? 'Cannot deactivate your own session' : 'Click to toggle active state'}
                        >
                          {u.is_active ? 'Active' : 'Disabled'}
                        </button>
                      </td>
                      <td>
                        <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                          <button
                            type="button"
                            className="fs-btn fs-btn-secondary"
                            style={{ height: '30px', padding: '0 10px', fontSize: '12px' }}
                            disabled={isBusy}
                            onClick={() => {
                              setResetTargetUser(u.username);
                              setResetPasswordVal('');
                              setDirError(null);
                            }}
                          >
                            <KeyRound size={13} />
                            <span>Reset Password</span>
                          </button>

                          {!isSelf && (
                            <button
                              type="button"
                              className="fs-btn fs-btn-danger"
                              style={{ height: '30px', padding: '0 10px', fontSize: '12px' }}
                              disabled={isBusy}
                              onClick={() => handleDeleteUser(u.username)}
                            >
                              <Trash2 size={13} />
                              <span>
                                {confirmDeleteUsername === u.username ? 'Confirm?' : 'Delete'}
                              </span>
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Password Reset Modal */}
      {resetTargetUser && (
        <div style={modalBackdropStyle}>
          <div className="fs-card" style={{ width: '100%', maxWidth: '420px', padding: '24px' }}>
            <h3 style={{ margin: '0 0 6px', fontSize: '16px', fontWeight: 700, color: '#fff' }}>
              Reset Password for {resetTargetUser}
            </h3>
            <p style={{ fontSize: '12px', color: 'var(--text-muted)', marginBottom: '16px' }}>
              All existing JWT sessions for this account will be invalidated immediately.
            </p>
            <form onSubmit={handleResetPasswordSubmit} style={formStyle}>
              <div style={inputGroupStyle}>
                <label style={labelStyle}>New Password (12–72 characters)</label>
                <input
                  type="password"
                  className="fs-input"
                  minLength={12}
                  value={resetPasswordVal}
                  onChange={(e) => setResetPasswordVal(e.target.value)}
                  disabled={resetPasswordLoading}
                  required
                />
              </div>
              <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  className="fs-btn fs-btn-secondary"
                  disabled={resetPasswordLoading}
                  onClick={() => {
                    setResetTargetUser(null);
                    setResetPasswordVal('');
                  }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="fs-btn fs-btn-primary"
                  disabled={resetPasswordLoading || resetPasswordVal.length < 12}
                >
                  {resetPasswordLoading ? 'Updating…' : 'Update Password'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ReBAC Document Sharing & Semantic Governance */}
      <div style={{ ...gridStyle, marginTop: '24px' }}>
        <div className="fs-card" style={cardStyle}>
          <div style={cardTitleContainerStyle}>
            <Share2 size={20} color="var(--primary)" />
            <h2 style={cardTitleStyle}>Document Access Sharing (ReBAC)</h2>
          </div>
          <p style={cardSubtitleStyle}>
            Grant or revoke cross-department or per-user OpenFGA viewer permissions.
          </p>

          {permError && <div style={{ ...errorBannerStyle, marginBottom: '12px' }}>{permError}</div>}
          {permBanner && <div style={{ ...successBannerStyle, marginBottom: '12px' }}>{permBanner}</div>}

          <div style={inputGroupStyle}>
            <label style={labelStyle}>Document</label>
            <select
              className="fs-input"
              value={selectedDocId ?? ''}
              onChange={(e) => setSelectedDocId(e.target.value ? Number(e.target.value) : null)}
            >
              {docsList.map((d) => (
                <option key={d.id ?? d.filename} value={d.id ?? ''}>
                  {d.filename} ({d.role})
                </option>
              ))}
            </select>
          </div>

          <form
            style={{ display: 'flex', gap: '8px', marginTop: '12px' }}
            onSubmit={async (e) => {
              e.preventDefault();
              if (!selectedDocId || !grantSubject.trim()) return;
              setPermError(null);
              setPermBanner(null);
              try {
                const res = await grantDocumentPermission(selectedDocId, grantSubject.trim(), 'viewer');
                setDocPermissions(res.permissions || []);
                setGrantSubject('');
                setPermBanner('Viewer permission granted.');
              } catch (err: any) {
                setPermError(err?.response?.data?.detail || 'Failed to grant permission.');
              }
            }}
          >
            <input
              className="fs-input"
              placeholder="user:marketing or role:finance#assignee"
              value={grantSubject}
              onChange={(e) => setGrantSubject(e.target.value)}
            />
            <button type="submit" className="fs-btn fs-btn-primary">
              Share
            </button>
          </form>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '14px' }}>
            {docPermissions.map((p) => {
              const removable = p.relation === 'viewer' || p.relation === 'owner';
              return (
                <span key={p.id} style={roleChipStyle}>
                  <span>
                    {p.subject} ({p.relation})
                  </span>
                  {removable && selectedDocId && (
                    <button
                      type="button"
                      onClick={async () => {
                        setPermError(null);
                        try {
                          const res = await revokeDocumentPermission(selectedDocId, p.subject, p.relation);
                          setDocPermissions(res.permissions || []);
                          setPermBanner(`Revoked ${p.subject}.`);
                        } catch (err: any) {
                          setPermError(err?.response?.data?.detail || 'Revoke failed.');
                        }
                      }}
                      style={{ background: 'none', border: 'none', color: '#FCA5A5', cursor: 'pointer' }}
                      aria-label={`Revoke ${p.subject}`}
                    >
                      <Trash2 size={12} />
                    </button>
                  )}
                </span>
              );
            })}
          </div>
        </div>

        <div className="fs-card" style={cardStyle}>
          <div style={cardTitleContainerStyle}>
            <Database size={20} color="var(--primary)" />
            <h2 style={cardTitleStyle}>Semantic NL2SQL Governance</h2>
          </div>
          <p style={cardSubtitleStyle}>
            Configure business descriptions & synonyms used by the DuckDB SQL planner.
          </p>

          {semanticError && <div style={{ ...errorBannerStyle, marginBottom: '12px' }}>{semanticError}</div>}
          {semanticBanner && <div style={{ ...successBannerStyle, marginBottom: '12px' }}>{semanticBanner}</div>}

          <div style={inputGroupStyle}>
            <label style={labelStyle}>Dataset Table</label>
            <select
              className="fs-input"
              value={selectedSemanticTable}
              onChange={(e) => {
                const name = e.target.value;
                setSelectedSemanticTable(name);
                const found = semanticModels.find((m) => m.table_name === name);
                setSemanticDescription(found?.description || '');
                setSemanticSynonymsText(
                  Object.entries(found?.synonyms || {})
                    .map(([k, v]) => `${k}=${v}`)
                    .join(', ')
                );
              }}
            >
              {semanticModels.map((m) => (
                <option key={m.table_name} value={m.table_name}>
                  {m.table_name} ({m.metrics?.length || 0} metrics)
                </option>
              ))}
            </select>
          </div>

          <div style={{ ...inputGroupStyle, marginTop: '12px' }}>
            <label style={labelStyle}>Description</label>
            <input
              className="fs-input"
              value={semanticDescription}
              onChange={(e) => setSemanticDescription(e.target.value)}
            />
          </div>

          <div style={{ ...inputGroupStyle, marginTop: '12px' }}>
            <label style={labelStyle}>Synonyms (term=column, comma separated)</label>
            <input
              className="fs-input"
              placeholder="pay=salary, team=department"
              value={semanticSynonymsText}
              onChange={(e) => setSemanticSynonymsText(e.target.value)}
            />
          </div>

          <div style={{ display: 'flex', gap: '10px', marginTop: '14px' }}>
            <button
              type="button"
              className="fs-btn fs-btn-primary"
              disabled={!selectedSemanticTable}
              onClick={async () => {
                const current = semanticModels.find((m) => m.table_name === selectedSemanticTable);
                if (!current) return;
                setSemanticError(null);
                setSemanticBanner(null);
                const synObj: Record<string, string> = {};
                semanticSynonymsText.split(',').forEach((pair) => {
                  const [k, v] = pair.split('=').map((x) => x.trim());
                  if (k && v) synObj[k] = v;
                });
                try {
                  const saved = await updateSemanticModel(current.table_name, {
                    display_name: current.display_name,
                    description: semanticDescription,
                    metrics: current.metrics,
                    dimensions: current.dimensions,
                    synonyms: synObj,
                    joins: current.joins,
                  });
                  setSemanticModels((prev) =>
                    prev.map((m) => (m.table_name === saved.table_name ? saved : m))
                  );
                  setSemanticBanner(`Saved semantic model for ${saved.table_name}.`);
                } catch (err: any) {
                  setSemanticError(err?.response?.data?.detail || 'Save failed.');
                }
              }}
            >
              Save Model
            </button>
            <button
              type="button"
              className="fs-btn fs-btn-secondary"
              disabled={!selectedSemanticTable}
              onClick={async () => {
                if (!selectedSemanticTable) return;
                const reset = await resetSemanticModel(selectedSemanticTable);
                setSemanticModels((prev) =>
                  prev.map((m) => (m.table_name === reset.table_name ? reset : m))
                );
                setSemanticDescription(reset.description || '');
                setSemanticSynonymsText(
                  Object.entries(reset.synonyms || {})
                    .map(([k, v]) => `${k}=${v}`)
                    .join(', ')
                );
                setSemanticBanner(`Reset ${reset.table_name} to auto-inferred schema.`);
              }}
            >
              <RotateCcw size={13} />
              <span>Reset</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

const gridStyle: React.CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 320px), 1fr))',
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
  gap: '16px',
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

const roleChipStyle: React.CSSProperties = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: '6px',
  padding: '5px 10px',
  borderRadius: '6px',
  background: 'rgba(255, 255, 255, 0.04)',
  border: '1px solid var(--border)',
  fontSize: '12.5px',
  color: 'var(--text-secondary)',
};

const modalBackdropStyle: React.CSSProperties = {
  position: 'fixed',
  inset: 0,
  background: 'rgba(6, 12, 14, 0.72)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  padding: '16px',
  zIndex: 100,
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
