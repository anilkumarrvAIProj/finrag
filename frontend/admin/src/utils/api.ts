import axios from 'axios';

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:7200';

export const api = axios.create({
  baseURL: `${BASE}/api/v1`,
  timeout: 30_000,
});

// Attach token from localStorage
api.interceptors.request.use(cfg => {
  const token = localStorage.getItem('finrag_token');
  if (token && cfg.headers) cfg.headers.Authorization = `Bearer ${token}`;
  return cfg;
});

// ── Documents ─────────────────────────────────────────────────────────────────
export const getDocuments = (params?: Record<string, unknown>) =>
  api.get('/documents', { params }).then(r => r.data);

export const getDocument = (id: string) =>
  api.get(`/documents/${id}`).then(r => r.data);

export const uploadDocument = (formData: FormData) =>
  api.post('/documents/upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120_000,
  }).then(r => r.data);

export const bulkUpload = (formData: FormData) =>
  api.post('/documents/bulk-upload', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300_000,
  }).then(r => r.data);

export const reprocessDocument = (id: string, forceOcr = false) =>
  api.post(`/documents/${id}/reprocess`, { force_ocr: forceOcr }).then(r => r.data);

export const deleteDocument = (id: string) =>
  api.delete(`/documents/${id}`).then(r => r.data);

export const getDownloadUrl = (id: string) =>
  api.get(`/documents/${id}/download`).then(r => r.data);

// ── Admin ──────────────────────────────────────────────────────────────────────
export const getHealth = () =>
  api.get('/admin/health').then(r => r.data);

export const getStats = () =>
  api.get('/admin/stats').then(r => r.data);

export const getAuditLogs = (params?: Record<string, unknown>) =>
  api.get('/admin/audit-logs', { params }).then(r => r.data);

export const verifyAuditChain = () =>
  api.post('/admin/audit-logs/verify').then(r => r.data);

// ── Users ──────────────────────────────────────────────────────────────────────
export const getUsers = () =>
  api.get('/users').then(r => r.data);

export const updateUserRole = (id: string, role: string) =>
  api.patch(`/users/${id}/role`, { role }).then(r => r.data);

// ── Dev Auth ───────────────────────────────────────────────────────────────────
export const getDevToken = async (role = 'admin') => {
  const r = await api.post(`/auth/dev-token?role=${role}`);
  localStorage.setItem('finrag_token', r.data.access_token);
  return r.data;
};
