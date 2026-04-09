import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getUsers, updateUserRole } from '../utils/api';
import { Users as UsersIcon, Shield } from 'lucide-react';
import toast from 'react-hot-toast';
import clsx from 'clsx';
import { format } from 'date-fns';

const ROLE_STYLES: Record<string, string> = {
  super_admin: 'bg-red-50 text-red-700',
  admin: 'bg-orange-50 text-orange-700',
  analyst: 'bg-blue-50 text-blue-700',
  read_only: 'bg-gray-50 text-gray-600',
};

const ROLES = ['super_admin', 'admin', 'analyst', 'read_only'];

export default function Users() {
  const qc = useQueryClient();
  const { data: users = [], isLoading } = useQuery({
    queryKey: ['users'],
    queryFn: getUsers,
  });

  const updateRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: string }) => updateUserRole(id, role),
    onSuccess: () => {
      toast.success('Role updated');
      qc.invalidateQueries({ queryKey: ['users'] });
    },
    onError: () => toast.error('Role update failed'),
  });

  return (
    <div className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold text-gray-900 flex items-center gap-2">
          <UsersIcon size={20} className="text-slate-600" />
          User Management
        </h2>
        <p className="text-sm text-gray-500 mt-0.5">{users.length} users in this tenant</p>
      </div>

      <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b border-gray-200">
            <tr>
              {['Email', 'Display Name', 'Role', 'Status', 'Created', 'Change Role'].map(h => (
                <th key={h} className="text-left px-4 py-3 text-xs font-medium text-gray-500">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {isLoading ? (
              <tr><td colSpan={6} className="text-center py-12 text-gray-400 text-sm">Loading…</td></tr>
            ) : users.length === 0 ? (
              <tr><td colSpan={6} className="text-center py-12 text-gray-400 text-sm">No users found</td></tr>
            ) : (
              users.map((user: any) => (
                <tr key={user.id} className="hover:bg-gray-50 transition">
                  <td className="px-4 py-3 text-sm text-gray-800">{user.email}</td>
                  <td className="px-4 py-3 text-sm text-gray-600">{user.display_name ?? '—'}</td>
                  <td className="px-4 py-3">
                    <span className={clsx('text-xs px-2 py-0.5 rounded-full font-medium', ROLE_STYLES[user.role] ?? 'bg-gray-50 text-gray-600')}>
                      {user.role}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className={clsx('text-xs px-2 py-0.5 rounded-full', user.is_active ? 'bg-green-50 text-green-700' : 'bg-gray-100 text-gray-500')}>
                      {user.is_active ? 'Active' : 'Inactive'}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-gray-400">
                    {format(new Date(user.created_at), 'dd MMM yyyy')}
                  </td>
                  <td className="px-4 py-3">
                    <select
                      defaultValue={user.role}
                      onChange={e => updateRole.mutate({ id: user.id, role: e.target.value })}
                      className="text-xs border border-gray-200 rounded px-2 py-1 text-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
                    >
                      {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
