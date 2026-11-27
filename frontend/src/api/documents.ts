import client from './client';
import type { DocumentPermission } from '../types';

export async function openPdfPreview(filepath: string, docId?: number): Promise<void> {
  const preview = window.open('about:blank', '_blank');
  if (!preview) throw new Error('Allow pop-ups to open the PDF preview.');
  preview.opener = null;
  try {
    const params = docId !== undefined ? { doc_id: docId, filepath } : { filepath };
    const response = await client.get('/preview-pdf', { params, responseType: 'blob' });
    const url = URL.createObjectURL(new Blob([response.data], { type: 'application/pdf' }));
    preview.location.replace(url);
    window.setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch {
    preview.close();
    throw new Error('The PDF could not be opened. Check your connection and document access.');
  }
}

export async function updateDocumentRole(
  docId: number,
  role: string,
): Promise<{ id: number; filename: string; role: string; message: string }> {
  const res = await client.patch(`/documents/${docId}`, { role });
  return res.data;
}

export async function reindexDocument(
  docId: number,
): Promise<{ status: string; doc_id: number; job_id: string; message: string }> {
  const res = await client.post(`/documents/${docId}/reindex`);
  return res.data;
}

export async function deleteDocument(docId: number): Promise<{ message: string }> {
  const res = await client.delete(`/documents/${docId}`);
  return res.data;
}

export async function fetchDocumentPermissions(
  docId: number,
): Promise<{ doc_id: number; filename: string; role: string; permissions: DocumentPermission[] }> {
  const res = await client.get(`/documents/${docId}/permissions`);
  return res.data;
}

export async function grantDocumentPermission(
  docId: number,
  subject: string,
  relation = 'viewer',
): Promise<{ permissions: DocumentPermission[] }> {
  const res = await client.post(`/documents/${docId}/permissions`, { subject, relation });
  return res.data;
}

export async function revokeDocumentPermission(
  docId: number,
  subject: string,
  relation = 'viewer',
): Promise<{ permissions: DocumentPermission[] }> {
  const res = await client.delete(`/documents/${docId}/permissions`, {
    params: { subject, relation },
  });
  return res.data;
}
