import React, { useState, useEffect } from 'react';
import client from '../api/client';
import { Upload, CheckCircle, AlertCircle } from 'lucide-react';

export default function UploadPage() {
  const [rolesList, setRolesList] = useState<string[]>([]);
  const [selectedRole, setSelectedRole] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  
  const [uploading, setUploading] = useState(false);
  const [indexing, setIndexing] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);

  // Fetch security roles list on load
  useEffect(() => {
    const fetchRoles = async () => {
      try {
        const res = await client.get('/roles');
        setRolesList(res.data.roles);
        if (res.data.roles.length > 0) {
          setSelectedRole(res.data.roles[0]);
        }
      } catch (e) {
        console.error('Failed to fetch roles for file upload mapping', e);
      }
    };
    fetchRoles();
  }, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setSelectedFile(e.target.files[0]);
      setStatusMsg(null);
      setErrorMsg(null);
    }
  };

  const handleUpload = async () => {
    if (!selectedFile || !selectedRole) {
      setErrorMsg('Please select a file and assign a security role.');
      return;
    }

    setUploading(true);
    setErrorMsg(null);
    setStatusMsg('Uploading document contents...');
    setProgress(0);

    const formData = new FormData();
    formData.append('file', selectedFile);
    formData.append('role', selectedRole);

    try {
      await client.post('/upload-docs', formData, {
        headers: {
          'Content-Type': 'multipart/form-data'
        }
      });

      setUploading(false);
      setIndexing(true);
      setStatusMsg('File registered. Indexing started...');

      // Begin polling status
      pollIndexingStatus(selectedFile.name);
    } catch (e: any) {
      console.error('Upload failed', e);
      setErrorMsg(e.response?.data?.detail || 'Upload failed. Check connection.');
      setUploading(false);
      setStatusMsg(null);
    }
  };

  const pollIndexingStatus = (filename: string) => {
    let attempts = 0;
    const interval = setInterval(async () => {
      attempts++;
      if (attempts > 300) { // Timeout after 7.5 mins
        clearInterval(interval);
        setIndexing(false);
        setErrorMsg('Indexing is taking longer than expected. Check progress in KB Indexing.');
        return;
      }

      try {
        const res = await client.get('/indexing-status', {
          params: { filename }
        });

        const { embedded, total_chunks, embedded_chunks } = res.data;

        if (embedded === 1) {
          clearInterval(interval);
          setIndexing(false);
          setProgress(100);
          setStatusMsg(`🎉 '${filename}' successfully indexed and mapped!`);
          setSelectedFile(null);
        } else if (embedded === -1) {
          clearInterval(interval);
          setIndexing(false);
          setErrorMsg(`❌ '${filename}' failed to index. Check backend logs.`);
          setStatusMsg(null);
        } else if (total_chunks > 0) {
          const pct = Math.min(99, Math.floor((embedded_chunks / total_chunks) * 100));
          setProgress(pct);
          setStatusMsg(`⏳ Embedding: ${embedded_chunks}/${total_chunks} chunks (${pct}%)`);
        } else {
          setStatusMsg('⏳ Parsing document sections...');
        }
      } catch (e) {
        console.warn('Failed to poll indexing status', e);
      }
    }, 1500);
  };

  return (
    <div>
      {/* Header */}
      <div className="fs-header">
        <h1 className="fs-title">📤 Upload knowledge documents</h1>
        <p className="fs-subtitle">Upload CSV datasets, Markdown guides, or PDF logs to securely index them in RAG knowledge bases.</p>
      </div>

      <div className="fs-card" style={{ maxWidth: '640px', margin: '0 auto' }}>
        <div style={formGridStyle}>
          {/* Assigned Security Role */}
          <div className="input-group" style={inputGroupStyle}>
            <label style={labelStyle}>Assign security access role</label>
            <select
              className="fs-input"
              value={selectedRole}
              onChange={(e) => setSelectedRole(e.target.value)}
              disabled={uploading || indexing}
            >
              {rolesList.map((r, idx) => (
                <option key={idx} value={r}>{r}</option>
              ))}
            </select>
            <span style={hintStyle}>Only users with this role (or higher) will be able to query this document.</span>
          </div>

          {/* File Picker Container */}
          <div style={filePickerContainerStyle(selectedFile !== null)}>
            <input
              type="file"
              id="file-upload-input"
              style={{ display: 'none' }}
              onChange={handleFileChange}
              accept=".csv,.md,.pdf"
              disabled={uploading || indexing}
            />
            
            <label htmlFor="file-upload-input" style={pickerLabelStyle(uploading || indexing)}>
              <Upload size={32} color="var(--primary)" style={{ marginBottom: '12px' }} />
              {selectedFile ? (
                <div>
                  <span style={selectedFilenameStyle}>{selectedFile.name}</span>
                  <span style={fileSizeStyle}>({(selectedFile.size / 1024).toFixed(1)} KB)</span>
                </div>
              ) : (
                <div>
                  <span style={pickerPrimaryTextStyle}>Click to browse document</span>
                  <span style={pickerSecondaryTextStyle}>Supports CSV, Markdown (.md), and PDF files</span>
                </div>
              )}
            </label>
          </div>

          {/* Action button */}
          <button
            className="fs-btn fs-btn-primary"
            style={{ width: '100%', height: '46px' }}
            onClick={handleUpload}
            disabled={uploading || indexing || !selectedFile}
          >
            <Upload size={16} />
            <span>Upload & Index Document</span>
          </button>

          {/* Messages */}
          {errorMsg && (
            <div style={errorContainerStyle}>
              <AlertCircle size={16} />
              <span>{errorMsg}</span>
            </div>
          )}

          {statusMsg && (
            <div style={statusContainerStyle(indexing)}>
              <CheckCircle size={16} />
              <div style={{ flex: 1 }}>
                <div>{statusMsg}</div>
                {indexing && (
                  <div className="progress-bar-track" style={{ marginTop: '8px' }}>
                    <div
                      className="progress-bar-fill"
                      style={{
                        width: `${progress}%`,
                        background: 'linear-gradient(90deg, var(--primary), var(--secondary))'
                      }}
                    />
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// Inline CSS Styles for upload page
const formGridStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: '24px',
};

const inputGroupStyle: React.CSSProperties = {
  display: 'flex',
  flexDirection: 'column',
  gap: '6px',
};

const labelStyle: React.CSSProperties = {
  fontSize: '11.5px',
  fontWeight: 700,
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
  color: 'var(--text-secondary)',
};

const hintStyle: React.CSSProperties = {
  fontSize: '11px',
  color: 'var(--text-muted)',
};

const filePickerContainerStyle = (hasFile: boolean): React.CSSProperties => ({
  border: `2px dashed ${hasFile ? 'var(--primary)' : 'rgba(99, 102, 241, 0.25)'}`,
  background: 'rgba(5, 7, 20, 0.4)',
  borderRadius: 'var(--radius-md)',
  padding: '32px 16px',
  textAlign: 'center',
  transition: 'var(--transition-smooth)',
});

const pickerLabelStyle = (disabled: boolean): React.CSSProperties => ({
  cursor: disabled ? 'not-allowed' : 'pointer',
  display: 'flex',
  flexDirection: 'column',
  alignItems: 'center',
});

const selectedFilenameStyle: React.CSSProperties = {
  display: 'block',
  fontSize: '14.5px',
  fontWeight: 'bold',
  color: '#ffffff',
};

const fileSizeStyle: React.CSSProperties = {
  fontSize: '11.5px',
  color: 'var(--text-muted)',
  marginTop: '4px',
};

const pickerPrimaryTextStyle: React.CSSProperties = {
  display: 'block',
  fontSize: '14px',
  fontWeight: 600,
  color: '#ffffff',
  marginBottom: '4px',
};

const pickerSecondaryTextStyle: React.CSSProperties = {
  display: 'block',
  fontSize: '11.5px',
  color: 'var(--text-muted)',
};

const errorContainerStyle: React.CSSProperties = {
  display: 'flex',
  alignItems: 'center',
  gap: '10px',
  background: 'rgba(239, 68, 68, 0.15)',
  border: '1px solid rgba(239, 68, 68, 0.3)',
  color: '#FCA5A5',
  padding: '12px 16px',
  borderRadius: 'var(--radius-sm)',
  fontSize: '13px',
};

const statusContainerStyle = (isIndexing: boolean): React.CSSProperties => ({
  display: 'flex',
  alignItems: 'flex-start',
  gap: '10px',
  background: isIndexing ? 'rgba(245, 158, 11, 0.12)' : 'rgba(16, 185, 129, 0.12)',
  border: isIndexing ? '1px solid rgba(245, 158, 11, 0.25)' : '1px solid rgba(16, 185, 129, 0.25)',
  color: isIndexing ? '#FCD34D' : '#34D399',
  padding: '12px 16px',
  borderRadius: 'var(--radius-sm)',
  fontSize: '13px',
});
