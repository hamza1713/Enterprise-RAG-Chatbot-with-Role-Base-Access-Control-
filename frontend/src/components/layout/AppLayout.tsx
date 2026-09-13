import { useState, type ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { Menu, X, ShieldCheck } from 'lucide-react';
import Sidebar from './Sidebar';

const titles: Record<string, string> = { '/chat': 'AI assistant', '/explorer': 'Document library', '/upload': 'Upload documents', '/kb-indexing': 'Knowledge base', '/admin': 'Administration', '/evaluation': 'Quality & evaluation' };
export default function AppLayout({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const { pathname } = useLocation();
  return <div className={`app-container${open ? ' navigation-open' : ''}`}>
    <a className="skip-link" href="#main-content">Skip to content</a>
    <Sidebar />
    <div className="workspace-main">
      <header className="workspace-topbar">
        <button className="icon-button mobile-menu" aria-label={open ? 'Close navigation' : 'Open navigation'} aria-expanded={open} aria-controls="workspace-navigation" onClick={() => setOpen(!open)}>{open ? <X size={20} /> : <Menu size={20} />}</button>
        <span>Workspace <span className="breadcrumb-separator">/</span> <strong>{titles[pathname] || 'Overview'}</strong></span>
        <span className="topbar-access"><ShieldCheck size={14} />Role-based access</span>
      </header>
      <main className="main-content" id="main-content" tabIndex={-1}>{children}</main>
    </div>
  </div>;
}
