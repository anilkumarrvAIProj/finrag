import React, { useEffect } from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { getStats, getHealth } from '../utils/api';
import { FileText, CheckCircle, AlertCircle, Server, LogIn } from 'lucide-react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts';
import axios from 'axios';

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:7200';

function StatCard({ label, value, icon: Icon, color }: { label: string; value: number | string; icon: any; color: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5 flex items-center gap-4 shadow-sm">
      <div className={`w-10 h-10 rounded-lg flex items-center justify-center ${color}`}>
        <Icon size={20} className="text-white" />
      </div>
      <div>
        <p className="text-2xl font-semibold text-gray-900">{value}</p>
        <p className="text-xs text-gray-500 mt-0.5">{label}</p>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const isLoggedIn = !!localStorage.getItem('finrag_token');

  // Auto-login in dev mode on page load if no token
  useEffect(() => {
    if (!isLoggedIn) {
      axios.post(`${BASE}/api/v1/auth/dev-token?role=admin`)
        .then(r => {
          localStorage.setItem('finrag_token', r.data.access_token);
          window.location.reload();
        })
        .catch(() => {});
    }
  }, []);

  const stats = useQuery({ queryKey: ['stats'], queryFn: getStats, refetchInterval: 15_000, enabled: isLoggedIn });
  const health = useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 15_000, enabled: isLoggedIn });

  const loginMutation = useMutation({
    mutationFn: async (role: string) => {
      const r = await axios.post(`${BASE}/api/v1/auth/dev-token?role=${role}`);
      localStorage.setItem('finrag_token', r.data.access_token);
      window.location.reload();
    },
  });

  const docs = stats.data?.documents ?? {};
  const queueData = health.data?.queue_depths
    ? Object.entries(health.data.queue_depths).map(([name, depth]) => ({ name, depth }))
    : [];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-gray-900">Dashboard</h2>
          <p className="text-sm text-gray-500 mt-0.5">Pipeline overview and document statistics</p>
        </div>
        {!isLoggedIn && (
          <button
            onClick={() => loginMutation.mutate('admin')}
            disabled={loginMutation.isPending}
            className="flex items-center gap-2 text-sm px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition"
          >
            <LogIn size={15} />
            {loginMutation.isPending ? 'Logging in...' : 'Dev Login (Admin)'}
          </button>
        )}
        {isLoggedIn && (
          <span className="text-xs text-green-600 bg-green-50 px-3 py-1.5 rounded-full border border-green-100">
            ✓ Logged in
          </span>
        )}
      </div>

      {!isLoggedIn && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm text-amber-800">
          Logging in automatically... if this persists, click "Dev Login (Admin)" above.
        </div>
      )}

      {isLoggedIn && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <StatCard label="Total Documents" value={docs.total ?? '—'} icon={FileText} color="bg-blue-500" />
            <StatCard label="Indexed" value={docs.indexed ?? '—'} icon={CheckCircle} color="bg-green-500" />
            <StatCard label="Failed" value={docs.failed ?? '—'} icon={AlertCircle} color="bg-red-500" />
          </div>

          <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
            <h3 className="text-sm font-medium text-gray-700 mb-4 flex items-center gap-2">
              <Server size={16} />
              Service Health
            </h3>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {(['database', 'vector_store', 'cache', 'status'] as const).map(key => {
                const val = health.data?.[key] ?? 'unknown';
                const isOk = typeof val === 'string' && (val === 'ok' || val === 'healthy');
                return (
                  <div key={key}>
                    <p className="text-xs text-gray-500 capitalize mb-1">{key.replace('_', ' ')}</p>
                    <span className={`text-xs font-medium px-2 py-1 rounded-full ${isOk ? 'bg-green-50 text-green-700' : 'bg-amber-50 text-amber-700'}`}>
                      {val}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          {queueData.length > 0 && (
            <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
              <h3 className="text-sm font-medium text-gray-700 mb-4">Queue Depths</h3>
              <ResponsiveContainer width="100%" height={160}>
                <BarChart data={queueData} barSize={40}>
                  <XAxis dataKey="name" tick={{ fontSize: 12 }} />
                  <YAxis tick={{ fontSize: 12 }} />
                  <Tooltip />
                  <Bar dataKey="depth" radius={[4, 4, 0, 0]}>
                    {queueData.map((_, i) => (
                      <Cell key={i} fill={i === 0 ? '#3b82f6' : i === 1 ? '#8b5cf6' : '#10b981'} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}
    </div>
  );
}
