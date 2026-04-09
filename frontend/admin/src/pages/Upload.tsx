import React, { useState, useCallback } from 'react';
import { useDropzone } from 'react-dropzone';
import { useMutation } from '@tanstack/react-query';
import toast from 'react-hot-toast';
import { uploadDocument } from '../utils/api';
import { Upload as UploadIcon, FileText, X, CheckCircle, Loader2, AlertCircle } from 'lucide-react';
import clsx from 'clsx';

interface FileItem {
  file: File;
  status: 'pending' | 'uploading' | 'done' | 'error';
  message?: string;
  docId?: string;
}

const DOC_TYPES = [
  { value: '', label: 'Auto-detect' },
  { value: 'fact_sheet', label: 'Fact Sheet' },
  { value: 'investment_report', label: 'Investment Report' },
  { value: 'quarterly_report', label: 'Quarterly Report' },
  { value: 'personnel', label: 'Personnel' },
  { value: 'portfolio_summary', label: 'Portfolio Summary' },
];

// Accept by extension, not MIME — more reliable on Windows
const ACCEPTED_EXTENSIONS = ['.pdf', '.docx', '.doc', '.xlsx', '.xls', '.pptx', '.ppt'];

function getFileIcon(filename: string) {
  const ext = filename.split('.').pop()?.toLowerCase();
  const colors: Record<string, string> = {
    pdf: 'text-red-400', docx: 'text-blue-400', doc: 'text-blue-400',
    xlsx: 'text-green-400', xls: 'text-green-400',
    pptx: 'text-orange-400', ppt: 'text-orange-400',
  };
  return colors[ext || ''] || 'text-gray-400';
}

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function isValidFile(file: File): boolean {
  const ext = '.' + file.name.split('.').pop()?.toLowerCase();
  return ACCEPTED_EXTENSIONS.includes(ext);
}

export default function Upload() {
  const [files, setFiles] = useState<FileItem[]>([]);
  const [docType, setDocType] = useState('');

  const onDrop = useCallback((accepted: File[], rejected: any[]) => {
    // Filter by extension (not MIME — Windows is unreliable with MIME)
    const valid: FileItem[] = [];
    const invalid: string[] = [];

    // Include both accepted and check rejected ones too
    const allFiles = [...accepted, ...rejected.map((r: any) => r.file)];

    for (const file of allFiles) {
      if (isValidFile(file)) {
        valid.push({ file, status: 'pending' });
      } else {
        invalid.push(file.name);
      }
    }

    if (invalid.length > 0) {
      toast.error(`Unsupported: ${invalid.join(', ')}`);
    }
    if (valid.length > 0) {
      setFiles(prev => [...prev, ...valid]);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    // Accept all files — we validate by extension ourselves
    accept: undefined,
    multiple: true,
    maxSize: 100 * 1024 * 1024, // 100MB
  });

  const remove = (i: number) => {
    setFiles(prev => prev.filter((_, idx) => idx !== i));
  };

  const uploadMutation = useMutation({
    mutationFn: async () => {
      const pending = files.filter(f => f.status === 'pending');
      if (pending.length === 0) {
        toast.error('No files to upload');
        return;
      }

      let successCount = 0;
      let failCount = 0;

      for (let i = 0; i < files.length; i++) {
        if (files[i].status !== 'pending') continue;

        // Mark as uploading
        setFiles(prev => prev.map((f, idx) =>
          idx === i ? { ...f, status: 'uploading' } : f
        ));

        const fd = new FormData();
        fd.append('file', files[i].file);
        if (docType) fd.append('doc_type', docType);

        try {
          const result = await uploadDocument(fd);
          setFiles(prev => prev.map((f, idx) =>
            idx === i ? { ...f, status: 'done', docId: result.id } : f
          ));
          successCount++;
        } catch (err: any) {
          const msg = err.response?.data?.detail || err.message || 'Upload failed';
          setFiles(prev => prev.map((f, idx) =>
            idx === i ? { ...f, status: 'error', message: msg } : f
          ));
          failCount++;
        }
      }

      if (successCount > 0) toast.success(`${successCount} file(s) uploaded. Processing started.`);
      if (failCount > 0) toast.error(`${failCount} file(s) failed. Check errors below.`);
    },
  });

  const pendingCount = files.filter(f => f.status === 'pending').length;

  return (
    <div className="max-w-2xl space-y-6">
      <div>
        <h2 className="text-xl font-semibold text-gray-900">Upload Documents</h2>
        <p className="text-sm text-gray-500 mt-0.5">
          Supports PDF, Word, Excel and PowerPoint. Office files are auto-converted to PDF.
        </p>
      </div>

      {/* Doc type */}
      <div>
        <label className="block text-xs font-medium text-gray-600 mb-1">Document Type</label>
        <select
          value={docType}
          onChange={e => setDocType(e.target.value)}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {DOC_TYPES.map(t => (
            <option key={t.value} value={t.value}>{t.label}</option>
          ))}
        </select>
      </div>

      {/* Dropzone */}
      <div
        {...getRootProps()}
        className={clsx(
          'border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-all select-none',
          isDragActive
            ? 'border-blue-500 bg-blue-50'
            : 'border-gray-200 hover:border-blue-400 hover:bg-gray-50'
        )}
      >
        <input {...getInputProps()} />
        <UploadIcon
          size={32}
          className={clsx('mx-auto mb-3', isDragActive ? 'text-blue-500' : 'text-gray-300')}
        />
        <p className="text-sm font-medium text-gray-700">
          {isDragActive ? 'Drop files here' : 'Drag & drop files, or click to browse'}
        </p>
        <p className="text-xs text-gray-400 mt-2">
          PDF · DOCX · XLSX · PPTX · Max 100MB per file
        </p>
      </div>

      {/* File list */}
      {files.length > 0 && (
        <div className="space-y-2">
          {files.map((item, i) => (
            <div
              key={i}
              className={clsx(
                'flex items-center gap-3 bg-white border rounded-lg px-4 py-3',
                item.status === 'error' ? 'border-red-200' : 'border-gray-200'
              )}
            >
              <FileText size={16} className={clsx('shrink-0', getFileIcon(item.file.name))} />
              <div className="flex-1 min-w-0">
                <p className="text-sm text-gray-800 truncate font-medium">{item.file.name}</p>
                <p className="text-xs text-gray-400">{formatBytes(item.file.size)}</p>
                {item.message && (
                  <p className="text-xs text-red-500 mt-0.5">{item.message}</p>
                )}
              </div>
              {/* Status icons */}
              {item.status === 'pending' && (
                <button
                  onClick={(e) => { e.stopPropagation(); remove(i); }}
                  className="text-gray-300 hover:text-red-500 transition p-1"
                >
                  <X size={14} />
                </button>
              )}
              {item.status === 'uploading' && (
                <Loader2 size={16} className="text-blue-500 animate-spin shrink-0" />
              )}
              {item.status === 'done' && (
                <CheckCircle size={16} className="text-green-500 shrink-0" />
              )}
              {item.status === 'error' && (
                <AlertCircle size={16} className="text-red-500 shrink-0" />
              )}
            </div>
          ))}
        </div>
      )}

      {/* Buttons */}
      <div className="flex gap-3">
        <button
          onClick={() => uploadMutation.mutate()}
          disabled={pendingCount === 0 || uploadMutation.isPending}
          className="flex items-center gap-2 px-5 py-2.5 bg-blue-600 hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm rounded-lg font-medium transition"
        >
          {uploadMutation.isPending
            ? <><Loader2 size={15} className="animate-spin" /> Uploading…</>
            : <>
                <UploadIcon size={15} />
                Upload {pendingCount > 0 ? `${pendingCount} File${pendingCount !== 1 ? 's' : ''}` : 'Files'}
              </>
          }
        </button>

        {files.length > 0 && !uploadMutation.isPending && (
          <button
            onClick={() => setFiles([])}
            className="px-4 py-2.5 border border-gray-200 text-sm text-gray-600 rounded-lg hover:bg-gray-50 transition"
          >
            Clear All
          </button>
        )}
      </div>
    </div>
  );
}
