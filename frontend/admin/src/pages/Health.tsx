// Health.tsx
import React from 'react';
import { useQuery, useMutation } from '@tanstack/react-query';
import { getHealth, verifyAuditChain } from '../utils/api';
import { CheckCircle, AlertCircle, Activity, RefreshCw } from 'lucide-react';
import toast from 'react-hot-toast';
import clsx from 'clsx';

export function Health() {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['health'],
    queryFn: getHealth,
    refetchInterval: 15_000,
  });

  const verify = useMutation({
    mutationFn: verifyAuditChain,
    onSuccess: (d) => {
      if (d.chain_valid) toast.success('Audit chain is valid ✓');
      else toast.error(`Chain broken at: ${d.first_broken_record_id}`);
    },
  });

  const services = [
    { label: 'Database', key: 'database' },
    { label: 'Vector Store', key: 'vector_store' },
    { label: 'Cache (Redis)', key: 'cache' },
    { label: 'Overall', key: 'status' },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-gray-900">Pipeline Health</h2>
          <p className="text-sm text-gray-500 mt-0.5">Live service status and queue depths</p>
        </div>
        <button onClick={() => refetch()} className="p-2 rounded-lg border border-gray-200 hover:bg-gray-50 transition">
          <RefreshCw size={15} className="text-gray-500" />
        </button>
      </div>

      {/* Service status cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {services.map(({ label, key }) => {
          const val = data?.[key] ?? 'unknown';
          const ok = val === 'ok' || val === 'healthy';
          return (
            <div key={key} className={clsx('rounded-xl border p-4', ok ? 'border-green-100 bg-green-50' : 'border-amber-100 bg-amber-50')}>
              <div className="flex items-center gap-2 mb-1">
                {ok
                  ? <CheckCircle size={15} className="text-green-600" />
                  : <AlertCircle size={15} className="text-amber-600" />
                }
                <p className="text-xs font-medium text-gray-700">{label}</p>
              </div>
              <p className={clsx('text-xs', ok ? 'text-green-700' : 'text-amber-700')}>{val}</p>
            </div>
          );
        })}
      </div>

      {/* Queue depths */}
      {data?.queue_depths && (
        <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
          <h3 className="text-sm font-medium text-gray-700 mb-4 flex items-center gap-2">
            <Activity size={15} />
            Celery Queue Depths
          </h3>
          <div className="space-y-3">
            {Object.entries(data.queue_depths).map(([queue, depth]) => (
              <div key={queue} className="flex items-center gap-3">
                <p className="text-sm text-gray-600 w-28 capitalize">{queue}</p>
                <div className="flex-1 bg-gray-100 rounded-full h-2">
                  <div
                    className="bg-blue-500 h-2 rounded-full transition-all"
                    style={{ width: `${Math.min(100, (Number(depth) / 50) * 100)}%` }}
                  />
                </div>
                <p className="text-sm text-gray-500 w-8 text-right">{String(depth)}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Workers */}
      {data?.workers && Object.keys(data.workers).length > 0 && (
        <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
          <h3 className="text-sm font-medium text-gray-700 mb-3">Active Workers</h3>
          <div className="space-y-2">
            {Object.entries(data.workers).map(([worker, count]) => (
              <div key={worker} className="flex justify-between text-sm">
                <span className="text-gray-600 font-mono text-xs">{worker}</span>
                <span className="text-gray-500">{String(count)} active tasks</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Audit chain verify */}
      <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm">
        <h3 className="text-sm font-medium text-gray-700 mb-2">Audit Chain Integrity</h3>
        <p className="text-xs text-gray-500 mb-3">Verify HMAC chain integrity across all audit log records.</p>
        <button
          onClick={() => verify.mutate()}
          disabled={verify.isPending}
          className="px-4 py-2 bg-slate-800 hover:bg-slate-700 text-white text-sm rounded-lg transition disabled:opacity-50"
        >
          {verify.isPending ? 'Verifying…' : 'Verify Audit Chain'}
        </button>
      </div>
    </div>
  );
}

export default Health;
