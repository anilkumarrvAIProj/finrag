import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Plus, ChevronRight, Folder, X, Check } from 'lucide-react';
import toast from 'react-hot-toast';
import { api as apiClient } from '../utils/api';

interface Fund {
  id: string;
  name: string;
  slug: string;
  strategy?: string;
  description?: string;
  document_count: number;
  quick_questions: string[];
  weaviate_collection: string;
}

export default function Funds() {
  const qc = useQueryClient();
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<Fund | null>(null);
  const [form, setForm] = useState({ name: '', description: '' });
  const [editQuestions, setEditQuestions] = useState<string[]>([]);
  const [newQ, setNewQ] = useState('');

  const { data: funds = [], isLoading } = useQuery<Fund[]>({
    queryKey: ['funds'],
    queryFn: () => apiClient.get('/funds').then(r => r.data),
  });

  const createMutation = useMutation({
    mutationFn: (data: any) => apiClient.post('/funds', data).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['funds'] });
      setCreating(false);
      setForm({ name: '', description: '' });
      toast.success('Fund created');
    },
    onError: (e: any) => toast.error(e.response?.data?.detail || 'Failed to create fund'),
  });

  const updateQMutation = useMutation({
    mutationFn: ({ id, questions }: { id: string; questions: string[] }) =>
      apiClient.post(`/funds/${id}/quick-questions`, questions).then(r => r.data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['funds'] });
      toast.success('Quick questions saved');
    },
  });

  const openFund = (f: Fund) => {
    setSelected(f);
    setEditQuestions([...f.quick_questions]);
  };

  if (isLoading) return <div style={{ padding: '2rem', color: '#6b7280' }}>Loading funds...</div>;

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.5rem' }}>
        <div>
          <h2 style={{ fontSize: 20, fontWeight: 600, margin: 0 }}>Funds</h2>
          <p style={{ fontSize: 13, color: '#6b7280', marginTop: 4 }}>{funds.length} funds · each with isolated document search</p>
        </div>
        <button
          onClick={() => setCreating(true)}
          style={{
            display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px',
            background: '#185FA5', color: 'white', border: 'none', borderRadius: 8,
            fontSize: 13, fontWeight: 500, cursor: 'pointer',
          }}
        >
          <Plus size={14} /> New fund
        </button>
      </div>

      {creating && (
        <div style={{ background: 'white', border: '0.5px solid #e5e7eb', borderRadius: 12, padding: '1.5rem', marginBottom: '1rem' }}>
          <h3 style={{ fontSize: 15, fontWeight: 600, marginBottom: '1rem' }}>Create fund</h3>
          <div style={{ display: 'grid', gap: 12 }}>
            <div>
              <label style={{ fontSize: 12, fontWeight: 500, color: '#374151' }}>Fund name *</label>
              <input
                value={form.name} onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
                placeholder="e.g. Aether Global Macro Fund"
                style={{ display: 'block', width: '100%', marginTop: 4, padding: '8px 10px', border: '0.5px solid #d1d5db', borderRadius: 6, fontSize: 13, boxSizing: 'border-box' }}
              />
            </div>
            <div>
              <label style={{ fontSize: 12, fontWeight: 500, color: '#374151' }}>Description</label>
              <textarea
                value={form.description} onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                rows={2} placeholder="Brief description of the fund"
                style={{ display: 'block', width: '100%', marginTop: 4, padding: '8px 10px', border: '0.5px solid #d1d5db', borderRadius: 6, fontSize: 13, resize: 'none', boxSizing: 'border-box' }}
              />
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                onClick={() => createMutation.mutate(form)}
                disabled={!form.name || createMutation.isPending}
                style={{ padding: '8px 16px', background: '#185FA5', color: 'white', border: 'none', borderRadius: 6, fontSize: 13, fontWeight: 500, cursor: 'pointer' }}
              >
                {createMutation.isPending ? 'Creating...' : 'Create fund'}
              </button>
              <button onClick={() => setCreating(false)} style={{ padding: '8px 16px', border: '0.5px solid #d1d5db', borderRadius: 6, fontSize: 13, cursor: 'pointer', background: 'white' }}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}

      <div style={{ display: 'grid', gap: 8 }}>
        {funds.map(f => (
          <div
            key={f.id}
            onClick={() => openFund(f)}
            style={{
              background: 'white', border: '0.5px solid #e5e7eb', borderRadius: 10,
              padding: '14px 16px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 12,
            }}
          >
            <div style={{ width: 36, height: 36, background: '#E6F1FB', borderRadius: 8, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <Folder size={16} style={{ color: '#185FA5' }} />
            </div>
            <div style={{ flex: 1 }}>
              <p style={{ fontSize: 14, fontWeight: 500, margin: 0 }}>{f.name}</p>
              <p style={{ fontSize: 12, color: '#6b7280', marginTop: 2 }}>
                
                {f.document_count} documents
              </p>
            </div>
            <ChevronRight size={16} style={{ color: '#9ca3af' }} />
          </div>
        ))}
        {funds.length === 0 && !creating && (
          <div style={{ textAlign: 'center', padding: '3rem', color: '#9ca3af', fontSize: 14 }}>
            No funds yet. Create your first fund to get started.
          </div>
        )}
      </div>

      {selected && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.4)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50,
        }} onClick={() => setSelected(null)}>
          <div
            style={{ background: 'white', borderRadius: 12, padding: '1.5rem', width: '90%', maxWidth: 540 }}
            onClick={e => e.stopPropagation()}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1.25rem' }}>
              <h3 style={{ fontSize: 16, fontWeight: 600, margin: 0 }}>{selected.name}</h3>
              <button onClick={() => setSelected(null)} style={{ background: 'none', border: 'none', cursor: 'pointer' }}>
                <X size={18} style={{ color: '#6b7280' }} />
              </button>
            </div>

            <div style={{ marginBottom: '1rem', fontSize: 13, color: '#6b7280' }}>
              <p><strong>Strategy:</strong> {selected.strategy || '—'}</p>
              <p><strong>Documents:</strong> {selected.document_count}</p>
              <p style={{ fontFamily: 'monospace', fontSize: 11 }}><strong>Collection:</strong> {selected.weaviate_collection}</p>
            </div>

            <div>
              <p style={{ fontSize: 13, fontWeight: 500, marginBottom: 8 }}>Quick questions (shown in chat)</p>
              {editQuestions.map((q, i) => (
                <div key={i} style={{ display: 'flex', gap: 6, marginBottom: 6 }}>
                  <input
                    value={q}
                    onChange={e => setEditQuestions(qs => qs.map((x, j) => j === i ? e.target.value : x))}
                    style={{ flex: 1, padding: '6px 8px', border: '0.5px solid #d1d5db', borderRadius: 6, fontSize: 13 }}
                  />
                  <button onClick={() => setEditQuestions(qs => qs.filter((_, j) => j !== i))}
                    style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#ef4444' }}>
                    <X size={14} />
                  </button>
                </div>
              ))}
              {editQuestions.length < 8 && (
                <div style={{ display: 'flex', gap: 6, marginTop: 6 }}>
                  <input
                    value={newQ} onChange={e => setNewQ(e.target.value)}
                    placeholder="Add a question..."
                    style={{ flex: 1, padding: '6px 8px', border: '0.5px solid #d1d5db', borderRadius: 6, fontSize: 13 }}
                    onKeyDown={e => { if (e.key === 'Enter' && newQ.trim()) { setEditQuestions(qs => [...qs, newQ.trim()]); setNewQ(''); }}}
                  />
                  <button
                    onClick={() => { if (newQ.trim()) { setEditQuestions(qs => [...qs, newQ.trim()]); setNewQ(''); }}}
                    style={{ padding: '6px 10px', background: '#185FA5', color: 'white', border: 'none', borderRadius: 6, cursor: 'pointer', fontSize: 13 }}
                  >
                    Add
                  </button>
                </div>
              )}
              <button
                onClick={() => updateQMutation.mutate({ id: selected.id, questions: editQuestions })}
                style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 6, padding: '8px 14px', background: '#059669', color: 'white', border: 'none', borderRadius: 6, fontSize: 13, fontWeight: 500, cursor: 'pointer' }}
              >
                <Check size={14} /> Save questions
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
