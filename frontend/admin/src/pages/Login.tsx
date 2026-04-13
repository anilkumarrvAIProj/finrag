import React, { useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import axios from 'axios';
import toast from 'react-hot-toast';

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:7200';

export default function Login({ onLogin }: { onLogin: () => void }) {
  const [email, setEmail] = useState('admin@finrag.local');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);

  const loginMutation = useMutation({
    mutationFn: async () => {
      const res = await axios.post(`${BASE}/api/v1/auth/login`, {
        email, password, tenant_slug: 'default',
      });
      return res.data;
    },
    onSuccess: (data) => {
      localStorage.setItem('finrag_token', data.access_token);
      localStorage.setItem('finrag_refresh_token', data.refresh_token);
      localStorage.setItem('finrag_user', JSON.stringify(data.user));
      toast.success(`Welcome back, ${data.user.display_name || data.user.email}`);
      onLogin();
    },
    onError: (err: any) => {
      toast.error(err.response?.data?.detail || 'Login failed');
    },
  });

  return (
    <div style={{
      minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: '#f8f9fa', fontFamily: 'system-ui, sans-serif',
    }}>
      <div style={{
        background: 'white', borderRadius: 12, border: '0.5px solid #e5e7eb',
        padding: '2.5rem', width: '100%', maxWidth: 400,
      }}>
        <div style={{ textAlign: 'center', marginBottom: '2rem' }}>
          <div style={{
            width: 44, height: 44, background: '#185FA5', borderRadius: 10,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto 12px', color: 'white', fontSize: 20, fontWeight: 700,
          }}>F</div>
          <h1 style={{ fontSize: 20, fontWeight: 600, color: '#111', margin: 0 }}>FinRAG Enterprise</h1>
          <p style={{ fontSize: 13, color: '#6b7280', marginTop: 4 }}>Admin Portal</p>
        </div>

        <div style={{ marginBottom: 16 }}>
          <label style={{ fontSize: 13, fontWeight: 500, color: '#374151', display: 'block', marginBottom: 6 }}>
            Email
          </label>
          <input
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="admin@finrag.local"
            style={{
              width: '100%', padding: '10px 12px', border: '0.5px solid #d1d5db',
              borderRadius: 8, fontSize: 14, outline: 'none', boxSizing: 'border-box',
            }}
            onKeyDown={e => e.key === 'Enter' && loginMutation.mutate()}
          />
        </div>

        <div style={{ marginBottom: 24 }}>
          <label style={{ fontSize: 13, fontWeight: 500, color: '#374151', display: 'block', marginBottom: 6 }}>
            Password
          </label>
          <div style={{ position: 'relative' }}>
            <input
              type={showPassword ? 'text' : 'password'}
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="Enter your password"
              style={{
                width: '100%', padding: '10px 40px 10px 12px', border: '0.5px solid #d1d5db',
                borderRadius: 8, fontSize: 14, outline: 'none', boxSizing: 'border-box',
              }}
              onKeyDown={e => e.key === 'Enter' && loginMutation.mutate()}
            />
            <button
              onClick={() => setShowPassword(s => !s)}
              style={{
                position: 'absolute', right: 10, top: '50%', transform: 'translateY(-50%)',
                background: 'none', border: 'none', cursor: 'pointer', color: '#9ca3af', fontSize: 12,
              }}
            >
              {showPassword ? 'Hide' : 'Show'}
            </button>
          </div>
        </div>

        <button
          onClick={() => loginMutation.mutate()}
          disabled={loginMutation.isPending || !email || !password}
          style={{
            width: '100%', padding: '10px', background: '#185FA5', color: 'white',
            border: 'none', borderRadius: 8, fontSize: 14, fontWeight: 500, cursor: 'pointer',
            opacity: loginMutation.isPending || !email || !password ? 0.6 : 1,
          }}
        >
          {loginMutation.isPending ? 'Signing in...' : 'Sign in'}
        </button>

        {!import.meta.env.PROD && (
          <div style={{ marginTop: 16, padding: '10px 12px', background: '#f0f9ff', borderRadius: 8, fontSize: 12, color: '#0369a1' }}>
            <strong>Dev mode:</strong> Default password is <code>FinRag@Admin123</code>
          </div>
        )}
      </div>
    </div>
  );
}
