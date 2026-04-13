import React, { useState, useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, NavLink, useNavigate } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { Toaster } from 'react-hot-toast';
import { LayoutDashboard, Upload, FileText, Folder, Users, Shield, LogOut } from 'lucide-react';
import axios from 'axios';

import Login from './pages/Login';
import Dashboard from './pages/Dashboard';
import UploadPage from './pages/Upload';
import Documents from './pages/Documents';
import Funds from './pages/Funds';
import AuditLogs from './pages/AuditLogs';

const qc = new QueryClient();
const BASE = import.meta.env.VITE_API_URL || 'http://localhost:7200';

// Axios interceptor — attach token to all requests
axios.interceptors.request.use(config => {
  const token = localStorage.getItem('finrag_token');
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Axios interceptor — handle 401 → redirect to login
axios.interceptors.response.use(
  r => r,
  async err => {
    if (err.response?.status === 401) {
      // Try refresh token
      const refresh = localStorage.getItem('finrag_refresh_token');
      if (refresh && !err.config._retry) {
        err.config._retry = true;
        try {
          const res = await axios.post(`${BASE}/api/v1/auth/refresh`, { refresh_token: refresh });
          localStorage.setItem('finrag_token', res.data.access_token);
          err.config.headers.Authorization = `Bearer ${res.data.access_token}`;
          return axios(err.config);
        } catch {
          localStorage.removeItem('finrag_token');
          localStorage.removeItem('finrag_refresh_token');
          window.location.href = '/login';
        }
      } else {
        localStorage.removeItem('finrag_token');
        localStorage.removeItem('finrag_refresh_token');
        window.location.href = '/login';
      }
    }
    return Promise.reject(err);
  }
);

function Sidebar() {
  const navigate = useNavigate();
  const user = JSON.parse(localStorage.getItem('finrag_user') || '{}');

  const logout = () => {
    localStorage.removeItem('finrag_token');
    localStorage.removeItem('finrag_refresh_token');
    localStorage.removeItem('finrag_user');
    navigate('/login');
  };

  const navItem = (to: string, Icon: any, label: string) => (
    <NavLink to={to} style={({ isActive }) => ({
      display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px',
      borderRadius: 6, fontSize: 13, fontWeight: 500, cursor: 'pointer',
      textDecoration: 'none', margin: '1px 0',
      color: isActive ? '#185FA5' : '#4b5563',
      background: isActive ? '#EBF4FF' : 'transparent',
    })}>
      <Icon size={15} />
      {label}
    </NavLink>
  );

  return (
    <div style={{ width: 200, background: '#f9fafb', borderRight: '0.5px solid #e5e7eb', display: 'flex', flexDirection: 'column', height: '100vh', padding: '1rem 0.75rem', flexShrink: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 4px 16px', marginBottom: 8, borderBottom: '0.5px solid #e5e7eb' }}>
        <div style={{ width: 28, height: 28, background: '#185FA5', borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white', fontSize: 13, fontWeight: 700 }}>F</div>
        <div>
          <p style={{ fontSize: 13, fontWeight: 600, margin: 0 }}>FinRAG</p>
          <p style={{ fontSize: 10, color: '#9ca3af', margin: 0 }}>Admin Portal</p>
        </div>
      </div>

      <nav style={{ flex: 1 }}>
        {navItem('/dashboard', LayoutDashboard, 'Dashboard')}
        {navItem('/upload', Upload, 'Upload')}
        {navItem('/documents', FileText, 'Documents')}
        {navItem('/funds', Folder, 'Funds')}
        {navItem('/audit', Shield, 'Audit log')}
      </nav>

      <div style={{ borderTop: '0.5px solid #e5e7eb', paddingTop: 12 }}>
        <div style={{ padding: '4px 4px 8px', fontSize: 12 }}>
          <p style={{ margin: 0, fontWeight: 500, color: '#374151' }}>{user.display_name || user.email || 'Admin'}</p>
          <p style={{ margin: 0, color: '#9ca3af', fontSize: 11 }}>{user.role || 'admin'}</p>
        </div>
        <button onClick={logout} style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', padding: '6px 4px', background: 'none', border: 'none', cursor: 'pointer', fontSize: 12, color: '#ef4444' }}>
          <LogOut size={13} /> Sign out
        </button>
      </div>
    </div>
  );
}

function Layout() {
  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden' }}>
      <Sidebar />
      <main style={{ flex: 1, overflow: 'auto', padding: '1.5rem 2rem', background: 'white' }}>
        <Routes>
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/upload" element={<UploadPage />} />
          <Route path="/documents" element={<Documents />} />
          <Route path="/funds" element={<Funds />} />
          <Route path="/audit" element={<AuditLogs />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  const [loggedIn, setLoggedIn] = useState(!!localStorage.getItem('finrag_token'));

  // No auto-login — always show login screen

  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={
            loggedIn ? <Navigate to="/dashboard" replace /> :
            <Login onLogin={() => setLoggedIn(true)} />
          } />
          <Route path="/*" element={
            loggedIn ? <Layout /> : <Navigate to="/login" replace />
          } />
        </Routes>
      </BrowserRouter>
      <Toaster position="top-right" />
    </QueryClientProvider>
  );
}
