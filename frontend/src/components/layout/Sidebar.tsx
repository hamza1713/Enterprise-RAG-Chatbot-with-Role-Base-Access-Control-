import { useEffect, useState } from 'react';
import { NavLink } from 'react-router-dom';
import { useAuthStore } from '../../store/authStore';
import client, { API_URL } from '../../api/client';
import { MessageSquare, Folder, Upload, Database, Settings, ChartNoAxesCombined, LogOut, Layers, ShieldCheck } from 'lucide-react';

export default function Sidebar() {
  const { username, role, logout } = useAuthStore();
  const [online, setOnline] = useState<boolean | null>(null);
  const [metrics, setMetrics] = useState<{ docs: number; users: number } | null>(null);
  const isAdmin = role?.toLowerCase() === 'c-level';
  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const refresh = async () => {
      try {
        const res = await fetch(`${API_URL}/`, { signal: AbortSignal.any([controller.signal, AbortSignal.timeout(8000)]) });
        if (active) setOnline(res.ok);
      } catch { if (active) setOnline(false); }
      if (isAdmin) {
        try {
          const res = await client.get('/system-metrics', { signal: controller.signal });
          if (active) setMetrics(res.data);
        } catch { if (active) setMetrics(null); }
      }
    };
    void refresh();
    const interval = setInterval(refresh, 30000);
    return () => { active = false; controller.abort(); clearInterval(interval); };
  }, [isAdmin]);
  const linkClass = ({ isActive }: { isActive: boolean }) => `nav-item${isActive ? ' active' : ''}`;
  return <aside className="workspace-sidebar" id="workspace-navigation">
    <NavLink to="/chat" className="brand"><span className="brand-mark"><Layers size={22} /></span>FinSight<span className="brand-period">.</span></NavLink>
    <div className="workspace-label"><span className="workspace-avatar">F</span><div>Company workspace<small>{role || 'Member'} access</small></div><ShieldCheck size={15} /></div>
    <nav aria-label="Main navigation">
      <p className="nav-section">Workspace</p>
      <NavLink to="/chat" className={linkClass}><MessageSquare size={18} />AI assistant<span className="nav-tag">AI</span></NavLink>
      <NavLink to="/explorer" className={linkClass}><Folder size={18} />Document library</NavLink>
      {isAdmin && <><p className="nav-section">Manage</p>
        <NavLink to="/upload" className={linkClass}><Upload size={18} />Upload documents</NavLink>
        <NavLink to="/kb-indexing" className={linkClass}><Database size={18} />Knowledge base</NavLink>
        <NavLink to="/evaluation" className={linkClass}><ChartNoAxesCombined size={18} />Quality & evaluation</NavLink>
        <NavLink to="/admin" className={linkClass}><Settings size={18} />Administration</NavLink>
      </>}
    </nav>
    <div className="sidebar-bottom">
      <div className="workspace-note"><ShieldCheck size={19} /><strong>Knowledge, with context</strong><p>Answers grounded in the documents available to your role.</p>{metrics && <small>{metrics.docs} documents · {metrics.users} members</small>}</div>
      <div className="connection-status" role="status"><span className={`status-dot ${online === true ? 'online' : online === false ? 'offline' : ''}`} />{online === null ? 'Connecting to workspace' : online ? 'Workspace connected' : 'Connection unavailable'}</div>
      <div className="sidebar-user"><span className="user-initial">{username?.slice(0, 1).toUpperCase()}</span><div><strong>{username}</strong><small>{role}</small></div><button onClick={logout} className="icon-button" aria-label="Sign out" title="Sign out"><LogOut size={17} /></button></div>
    </div>
  </aside>;
}
