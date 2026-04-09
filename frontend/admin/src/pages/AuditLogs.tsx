import React, { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getAuditLogs } from '../utils/api';
import { Shield, ChevronLeft, ChevronRight } from 'lucide-react';
import { format } from 'date-fns';
import clsx from 'clsx';

const ACTION_COLORS: Record<string, string> = {
  upload: 'bg-blue-50 text-blue-700',
  delete: 'bg-red-50 text-red-700',
  query: 'bg-purple-50 text-purple-700',
  reprocess: 'bg-amber-50 text-amber-700',
  login: 'bg-green-50 text-green-700',
  role_change: 'bg-orange-50 text-orange-700',
  export: 'bg-gray-50 text-gray-700',
};

export default function AuditLogs() {
  const [page, setPage] = useState(1);
  const [actionFilter, setActionFilter] = useState('');

  const { data, isLoading } = useQuery({
    queryKey: ['audit', page, actionFilter],
    queryFn: () => getAuditLogs({ page, page_size: 50, action: actionFilter || undefined }),
    refetchInterval: 30_000,
  });

  const totalPages = Math.ceil((data?.total ?? 0) / 50);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
            <Shield size={20} className="text-slate-600" />
            Audit Logs
          </h2>
          <p className="text-sm text-gray-500 mt-0.5">Immutable HMAC-chained activity log · {data?.total ?? 0} records</p>
        </div>
        <select
          value={actionFilter}
          onChange={e => { setActionFilter(e.target.value); setPage(1); }}
          className="text-sm border border-gray-200 rounded-lg px-3 py-2 text-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All actions</option>
          {Object.keys(ACTION_COLORS).map(a => (
            <option key={a} value={a}>{a}</option>
          ))}
        </select>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
        <table className="w-full text-xs">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              {['Time', 'Action', 'Resource', 'Resource ID', 'IP Address', 'Details'].map(h => (
                <th key={h} className="text-left px-4 py-3 text-xs font-medium text-gray-500">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-50">
            {isLoading ? (
              <tr><td colSpan={6} className="text-center py-12 text-gray-400">Loading…</td></tr>
            ) : data?.items?.length === 0 ? (
              <tr><td colSpan={6} className="text-center py-12 text-gray-400">No audit records found</td></tr>
            ) : (
              data?.items?.map((log: any) => (
                <tr key={log.id} className="hover:bg-gray-50 transition">
                  <td className="px-4 py-2.5 text-gray-400 whitespace-nowrap">
                    {format(new Date(log.created_at), 'dd MMM HH:mm:ss')}
                  </td>
                  <td className="px-4 py-2.5">
                    <span className={clsx('px-2 py-0.5 rounded-full font-medium text-xs', ACTION_COLORS[log.action] ?? 'bg-gray-100 text-gray-600')}>
                      {log.action}
                    </span>
                  </td>
                  <td className="px-4 py-2.5 text-gray-600">{log.resource_type ?? '—'}</td>
                  <td className="px-4 py-2.5 text-gray-400 font-mono">{log.resource_id?.slice(0, 8) ?? '—'}…</td>
                  <td className="px-4 py-2.5 text-gray-400">{log.ip_address ?? '—'}</td>
                  <td className="px-4 py-2.5 text-gray-500 max-w-[200px] truncate">
                    {log.details ? JSON.stringify(log.details).slice(0, 60) : '—'}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>

        {totalPages > 1 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100">
            <p className="text-xs text-gray-500">Page {page} of {totalPages}</p>
            <div className="flex gap-1">
              <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={page === 1} className="p-1.5 rounded hover:bg-gray-100 disabled:opacity-40">
                <ChevronLeft size={14} />
              </button>
              <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={page === totalPages} className="p-1.5 rounded hover:bg-gray-100 disabled:opacity-40">
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
