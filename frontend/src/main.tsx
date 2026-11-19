import '@fontsource-variable/inter'
import { Activity, BookOpen, ChevronRight, Command, LayoutDashboard, MessageSquare, PanelTop, Radio, ShieldCheck } from 'lucide-react'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, NavLink, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import type { Health } from './api'
import { Approvals } from './approvals'
import { ErrorNotice } from './components'
import { Overview } from './overview'
import { KnowledgeBase } from './knowledge'
import { Trace } from './trace'
import { useApi } from './useApi'
import { Workspace } from './workspace'
import './styles.css'

const navigation = [
  { path: '/', label: 'Overview', icon: LayoutDashboard },
  { path: '/workspace', label: 'Agent Workspace', icon: MessageSquare },
  { path: '/trace', label: 'Workflow Trace', icon: Activity },
  { path: '/knowledge', label: 'Knowledge Base', icon: BookOpen },
  { path: '/approvals', label: 'Approval Center', icon: ShieldCheck },
]

function App() {
  const { pathname } = useLocation()
  const { data: health, error } = useApi<Health>('/health/ready', 8000)
  const page = navigation.find((entry) => entry.path === pathname)?.label
  const ready = !error && health?.status === 'ready'
  const offline = Boolean(error || health?.status === 'unavailable')

  return <div className="app-shell">
    <a className="skip-link" href="#page-main">Skip to content</a>
    <aside className="sidebar">
      <NavLink to="/" className="brand">
        <span className="brand-mark"><Command size={23} strokeWidth={2.5} /></span>
        <span>OpsPilot <b>AI</b></span>
      </NavLink>
      <nav aria-label="Main navigation">
        {navigation.map(({ path, label, icon: Icon }) => <NavLink key={path} to={path} end
          className={({ isActive }) => `nav-link ${isActive ? 'nav-active' : ''}`}>
          <Icon size={19} /><span>{label}</span>
        </NavLink>)}
      </nav>
      <div className="sidebar-profile">
        <span className="profile-avatar">MC</span>
        <div><strong>Maya Chen</strong><span>Demo workspace</span></div>
      </div>
    </aside>
    <div className="app-content">
      <header className="topbar">
        <div className="breadcrumb"><PanelTop size={17} /><span>Workspace</span>
          <ChevronRight size={14} /><strong>{page}</strong>
        </div>
        <span className={`system-pill ${ready ? 'system-ready' : offline ? 'system-offline' : ''}`}>
          <Radio size={15} />{ready ? 'Local model online' : offline ? 'Local model unavailable' : 'Checking local model'}
        </span>
      </header>
      <main id="page-main" className="page" tabIndex={-1}>
        {offline && <ErrorNotice>{error ?? health?.ollama.detail ?? health?.demo_data}</ErrorNotice>}
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/workspace" element={<Workspace />} />
          <Route path="/trace" element={<Trace />} />
          <Route path="/knowledge" element={<KnowledgeBase />} />
          <Route path="/approvals" element={<Approvals />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  </div>
}

createRoot(document.getElementById('root')!).render(<StrictMode><BrowserRouter><App /></BrowserRouter></StrictMode>)
