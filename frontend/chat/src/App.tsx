import React, { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Toaster } from 'react-hot-toast'
import ChatPage from './pages/ChatPage'
import axios from 'axios'

const qc = new QueryClient()
const BASE = import.meta.env.VITE_API_URL || 'http://localhost:7200'

export default function App() {
  const [ready, setReady] = useState(!!localStorage.getItem('finrag_token'))

  useEffect(() => {
    if (!localStorage.getItem('finrag_token')) {
      axios.post(`${BASE}/api/v1/auth/dev-token?role=analyst`)
        .then(r => {
          localStorage.setItem('finrag_token', r.data.access_token)
          setReady(true)
        })
        .catch(() => setReady(true)) // proceed anyway
    }
  }, [])

  if (!ready) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', fontFamily: 'sans-serif', color: '#666' }}>
        Starting FinRAG...
      </div>
    )
  }

  return (
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Routes>
          <Route path="/*" element={<ChatPage />} />
        </Routes>
      </BrowserRouter>
      <Toaster position="top-right" />
    </QueryClientProvider>
  )
}
