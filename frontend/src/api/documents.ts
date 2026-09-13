import client from './client';

export async function openPdfPreview(filepath: string): Promise<void> {
  const preview = window.open('about:blank', '_blank');
  if (!preview) throw new Error('Allow pop-ups to open the PDF preview.');
  preview.opener = null;
  try {
    const response = await client.get('/preview-pdf', { params: { filepath }, responseType: 'blob' });
    const url = URL.createObjectURL(new Blob([response.data], { type: 'application/pdf' }));
    preview.location.replace(url);
    window.setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch {
    preview.close();
    throw new Error('The PDF could not be opened. Check your connection and document access.');
  }
}
