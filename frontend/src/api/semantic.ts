import client from './client';
import type { SemanticModel } from '../types';

export async function fetchSemanticModels(): Promise<SemanticModel[]> {
  const res = await client.get<{ models: SemanticModel[] }>('/semantic-models');
  return res.data.models || [];
}

export async function updateSemanticModel(
  tableName: string,
  payload: Omit<SemanticModel, 'id' | 'table_name' | 'doc_id' | 'updated_by' | 'updated_at'>
): Promise<SemanticModel> {
  const res = await client.put<SemanticModel>(
    `/semantic-models/${encodeURIComponent(tableName)}`,
    payload
  );
  return res.data;
}

export async function resetSemanticModel(tableName: string): Promise<SemanticModel> {
  const res = await client.post<SemanticModel>(
    `/semantic-models/${encodeURIComponent(tableName)}/reset`
  );
  return res.data;
}
