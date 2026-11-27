import client from './client';
import type { RoleDetail, UserRecord } from '../types';

export interface RolesResponse {
  roles: string[];
  role_details?: RoleDetail[];
}

export async function fetchRoles(): Promise<RolesResponse> {
  const res = await client.get<RolesResponse>('/roles');
  return res.data;
}

export async function deleteRole(roleName: string): Promise<{ message: string }> {
  const res = await client.delete(`/roles/${encodeURIComponent(roleName)}`);
  return res.data;
}

export async function fetchUsers(): Promise<UserRecord[]> {
  const res = await client.get<{ users: UserRecord[] }>('/users');
  return res.data.users || [];
}

export async function updateUser(
  username: string,
  payload: { role?: string; is_active?: boolean },
): Promise<UserRecord> {
  const res = await client.patch<UserRecord>(`/users/${encodeURIComponent(username)}`, payload);
  return res.data;
}

export async function resetUserPassword(
  username: string,
  password: string,
): Promise<{ message: string }> {
  const res = await client.post(`/users/${encodeURIComponent(username)}/reset-password`, {
    password,
  });
  return res.data;
}

export async function deleteUser(username: string): Promise<{ message: string }> {
  const res = await client.delete(`/users/${encodeURIComponent(username)}`);
  return res.data;
}
