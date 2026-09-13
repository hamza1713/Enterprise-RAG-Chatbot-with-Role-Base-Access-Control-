import { useState, type FormEvent } from 'react';
import { Navigate } from 'react-router-dom';
import axios from 'axios';
import { ArrowRight, Layers, ShieldCheck, FileText, ChartNoAxesCombined, Eye, EyeOff } from 'lucide-react';
import { useAuthStore } from '../store/authStore';

export default function LoginPage() {
  const { login, isAuthenticated } = useAuthStore();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [visible, setVisible] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  if (isAuthenticated) return <Navigate to="/chat" replace />;
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (loading) return;
    setLoading(true); setError('');
    try { await login(username.trim(), password); }
    catch (err) {
      setError(axios.isAxiosError(err) && err.response?.status === 401 ? 'The username or password is incorrect. Please try again.' : 'We couldn’t connect to your workspace. Please try again shortly.');
    } finally { setLoading(false); }
  };
  return <div className="login-page">
    <section className="login-story" aria-label="About FinSight">
      <div className="brand"><span className="brand-mark"><Layers size={24} /></span>FinSight<span className="brand-period">.</span></div>
      <div className="login-story-content"><span className="eyebrow">YOUR INTELLIGENCE WORKSPACE</span><h1>Your knowledge.<br />A clearer perspective.</h1><p>Connect the dots across your documents and data. Turn everyday questions into informed decisions.</p>
        <div className="login-capabilities"><div><FileText size={20} /><span><strong>Ask your documents</strong><small>Find answers with source references.</small></span></div><div><ChartNoAxesCombined size={20} /><span><strong>Understand your data</strong><small>Explore structured data in plain English.</small></span></div><div><ShieldCheck size={20} /><span><strong>A workspace for every role</strong><small>Department-specific access to knowledge.</small></span></div></div>
      </div><div className="login-story-footer">FINSIGHT <span>Clarity starts with a question.</span></div>
    </section>
    <section className="login-form-panel"><div className="login-form-wrap"><span className="eyebrow">WELCOME BACK</span><h2>Sign in to your workspace</h2><p className="login-intro">Your next insight is one question away.</p>
      <form onSubmit={submit}>
        {error && <div className="form-error" role="alert">{error}</div>}
        <label htmlFor="username">Username</label><input id="username" name="username" className="fs-input" autoComplete="username" placeholder="Your work username" value={username} onChange={e => setUsername(e.target.value)} required disabled={loading} />
        <label htmlFor="password">Password</label><div className="password-field"><input id="password" name="password" className="fs-input" type={visible ? 'text' : 'password'} autoComplete="current-password" placeholder="Enter your password" value={password} onChange={e => setPassword(e.target.value)} required disabled={loading} /><button className="icon-button" type="button" aria-label={visible ? 'Hide password' : 'Show password'} aria-pressed={visible} onClick={() => setVisible(!visible)}>{visible ? <EyeOff size={18} /> : <Eye size={18} />}</button></div>
        <button className="fs-btn fs-btn-primary login-submit" disabled={loading}>{loading ? 'Signing in…' : 'Sign in'}<ArrowRight size={17} /></button>
      </form><p className="login-help">Need access or help signing in?<br />Contact your workspace administrator.</p><div className="login-security"><ShieldCheck size={15} />Access is managed by your organization</div>
    </div><footer className="login-footer">FinSight · AI-powered knowledge workspace</footer></section>
  </div>;
}
