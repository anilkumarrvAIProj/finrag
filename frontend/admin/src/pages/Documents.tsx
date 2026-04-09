import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getDocuments, reprocessDocument, deleteDocument, getDownloadUrl } from '../utils/api';
import { RefreshCw, Trash2, Download, ChevronLeft, ChevronRight, Search, Filter } from 'lucide-react';
import toast from 'react-hot-toast';
import clsx from 'clsx';
import { format } from 'date-fns';

const STATUS_STYLES: Record<string, string> = {
  uploaded:       'bg-gray-100 text-gray-600',
  queued:         'bg-yellow-50 text-yellow-700',
  ocr_processing: 'bg-blue-50 text-blue-700',
  parsing:        'bg-blue-50 text-blue-700',
  embedding:      'bg-purple-50 text-purple-700',
  indexed:        'bg-green-50 text-green-700',
  failed:         'bg-red-50 text-red-700',
  degraded:       'bg-orange-50 text-orange-700',
};

const DOC_TYPE_LABELS: Record<string, string> = {
  fact_sheet: 'Fact Sheet',
  investment_report: 'Investment Report',
  quarterly_report: 'Quarterly Report',
  personnel: 'Personnel',
  portfolio_summary: 'Portfolio Summary',
  other: 'Other',
};

export default function Documents() {
  const qc = useQueryClient();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [docTypeFilter, setDocTypeFilter] = useState('');

  const { data, isLoading } = useQuery({
    queryKey: ['documents', page, search, statusFilter, docTypeFilter],
    queryFn: () => getDocuments({
      page,
      page_size: 20,
      search: search || undefined,
      status: statusFilter || undefined,
      doc_type: docTypeFilter || undefined,
    }),
    refetchInterval: 10_000,
  });

  const reprocess = useMutation({
    mutationFn: (id: string) => reprocessDocument(id),
    onSuccess: () => {
      toast.success('Reprocessing started');
      qc.invalidateQueries({ queryKey: ['documents'] });
    },
    onError: () => toast.error('Reprocess failed'),
  });

  const del = useMutation({
    mutationFn: (id: string) => deleteDocument(id),
    onSuccess: () => {
      toast.success('Document deleted');
      qc.invalidateQueries({ queryKey: ['documents'] });
    },
    onError: () => toast.error('Delete failed'),
  });

  const download = async (id: string, filename: string) => {
    try {
      const { url } = await getDownloadUrl(id);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
    } catch {
      toast.error('Download failed');
    }
  };

  const totalPages = Math.ceil((data?.total ?? 0) / 20);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold text-gray-900">Documents</h2>
          <p className="text-sm text-gray-500 mt-0.5">{data?.total ?? 0} total documents</p>
        </div>
        <button
          onClick={() => qc.invalidateQueries({ queryKey: ['documents'] })}
          className="p-2 rounded-lg border border-gray-200 hover:bg-gray-50 transition"
        >
          <RefreshCw size={15} className="text-gray-500" />
        </button>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1); }}
            placeholder="Search by filename..."
            className="w-full pl-9 pr-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <select
          value={statusFilter}
          onChange={e => { setStatusFilter(e.target.value); setPage(1); }}
          className="text-sm border border-gray-200 rounded-lg px-3 py-2 text-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All statuses</option>
          {Object.keys(STATUS_STYLES).map(s => (
            <option key={s} value={s}>{s.replace('_', ' ')}</option>
          ))}
        </select>
        <select
          value={docTypeFilter}
          onChange={e => { setDocTypeFilter(e.target.value); setPage(1); }}
          className="text-sm border border-gray-200 rounded-lg px-3 py-2 text-gray-600 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All types</option>
          {Object.entries(DOC_TYPE_LABELS).map(([v, l]) => (
            <option key={v} value={v}>{l}</option>
          ))}
        </select>
      </div>

      {/* Table */}
      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              {['Filename', 'Type', 'Status', 'Pages', 'Fund', 'Uploaded', 'Actions'].map(h => (
                <th key={h} className="text-left px-4 py-3 text-xs font-medium text-gray-500">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {isLoading ? (
              <tr><td colSpan={7} className="text-center py-12 text-gray-400 text-sm">Loading…</td></tr>
            ) : data?.items?.length === 0 ? (
              <tr><td colSpan={7} className="text-center py-12 text-gray-400 text-sm">No documents found</td></tr>
            ) : (
              data?.items?.map((doc: any) => (
                <tr key={doc.id} className="hover:bg-gray-50 transition">
                  <td className="px-4 py-3 max-w-[220px]">
                    <p className="truncate font-medium text-gray-800 text-xs">{doc.filename}</p>
                    <p className="text-gray-400 text-xs mt-0.5">v{doc.version}</p>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs text-gray-600">{DOC_TYPE_LABELS[doc.doc_type] ?? doc.doc_type}</span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={clsx('text-xs px-2 py-0.5 rounded-full font-medium', STATUS_STYLES[doc.status] ?? 'bg-gray-100 text-gray-600')}>
                      {doc.status.replace('_', ' ')}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-500">{doc.page_count ?? '—'}</td>
                  <td className="px-4 py-3 text-xs text-gray-500 max-w-[140px] truncate">{doc.fund_name ?? '—'}</td>
                  <td className="px-4 py-3 text-xs text-gray-400">
                    {format(new Date(doc.created_at), 'dd MMM yy')}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-1">
                      <button
                        onClick={() => download(doc.id, doc.filename)}
                        title="Download"
                        className="p-1.5 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-700 transition"
                      >
                        <Download size={13} />
                      </button>
                      <button
                        onClick={() => reprocess.mutate(doc.id)}
                        title="Reprocess"
                        className="p-1.5 rounded hover:bg-blue-50 text-gray-400 hover:text-blue-600 transition"
                      >
                        <RefreshCw size={13} />
                      </button>
                      <button
                        onClick={() => {
                          if (window.confirm(`Delete "${doc.filename}"?`)) del.mutate(doc.id);
                        }}
                        title="Delete"
                        className="p-1.5 rounded hover:bg-red-50 text-gray-400 hover:text-red-600 transition"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-gray-100">
            <p className="text-xs text-gray-500">
              Page {page} of {totalPages} · {data?.total} documents
            </p>
            <div className="flex gap-1">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="p-1.5 rounded hover:bg-gray-100 disabled:opacity-40 transition"
              >
                <ChevronLeft size={14} />
              </button>
              <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="p-1.5 rounded hover:bg-gray-100 disabled:opacity-40 transition"
              >
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
