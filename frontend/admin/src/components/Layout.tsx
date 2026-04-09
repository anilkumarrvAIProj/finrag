import React from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import {
  LayoutDashboard, FileText, Upload, Shield,
  Users, Activity, ChevronRight,
} from 'lucide-react';
import clsx from 'clsx';

const NAV = [
  { to: '/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
  { to: '/documents',  icon: FileText,       label: 'Documents' },
  { to: '/upload',     icon: Upload,          label: 'Upload' },
  { to: '/health',     icon: Activity,        label: 'Pipeline Health' },
  { to: '/audit',      icon: Shield,          label: 'Audit Logs' },
  { to: '/users',      icon: Users,           label: 'Users' },
];

export default function Layout() {
  return (
    <div className="flex h-screen bg-gray-50 font-sans">
      {/* Sidebar */}
      <aside className="w-64 bg-slate-900 flex flex-col shadow-xl">
        {/* Logo */}
        <div className="h-16 flex items-center px-6 border-b border-slate-700">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-blue-500 flex items-center justify-center text-white text-xs font-bold">F</div>
            <span className="text-white font-semibold text-sm tracking-wide">FinRAG</span>
            <span className="text-slate-400 text-xs ml-1">Admin</span>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
          {NAV.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                clsx(
                  'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all',
                  isActive
                    ? 'bg-blue-600 text-white'
                    : 'text-slate-400 hover:bg-slate-800 hover:text-white',
                )
              }
            >
              <Icon size={16} />
              <span className="flex-1">{label}</span>
            </NavLink>
          ))}
        </nav>

        {/* Footer */}
        <div className="p-4 border-t border-slate-700">
          <p className="text-slate-500 text-xs">FinRAG Enterprise v1.0</p>
        </div>
      </aside>

      {/* Main */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <header className="h-16 bg-white border-b border-gray-200 flex items-center px-6 gap-2 shadow-sm">
          <h1 className="text-gray-800 font-medium text-sm">Admin Portal</h1>
        </header>
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
