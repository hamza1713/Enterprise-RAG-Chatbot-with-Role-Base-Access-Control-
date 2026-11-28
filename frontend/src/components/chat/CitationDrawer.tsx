import type { CitationItem } from '../../types';
import { X, FileText, ExternalLink } from 'lucide-react';

interface CitationDrawerProps {
  citation: CitationItem | null;
  onClose: () => void;
  onOpenDocument: (source: string, docId?: number | null) => void;
}

export default function CitationDrawer({
  citation,
  onClose,
  onOpenDocument,
}: CitationDrawerProps) {
  if (!citation) return null;

  return (
    <aside className="citation-drawer" aria-label="Source citation preview">
      <div className="citation-drawer-header">
        <div className="citation-drawer-title">
          <span className="citation-chip-index">[{citation.index}]</span>
          <div>
            <strong>{citation.source}</strong>
            <small>
              {citation.page_number ? `Page ${citation.page_number}` : 'Document chunk'}
              {citation.section_title ? ` · ${citation.section_title}` : ''}
              {citation.parser_used ? ` · ${citation.parser_used}` : ''}
            </small>
          </div>
        </div>
        <button
          type="button"
          className="icon-button"
          onClick={onClose}
          aria-label="Close citation inspector"
        >
          <X size={16} />
        </button>
      </div>

      <div className="citation-drawer-body">
        <span className="eyebrow">EXTRACTED EVIDENCE PASSAGE</span>
        <blockquote className="citation-snippet-box">
          {citation.snippet}
        </blockquote>
      </div>

      <div className="citation-drawer-footer">
        <button
          type="button"
          className="fs-btn fs-btn-secondary"
          onClick={() => onOpenDocument(citation.source, citation.doc_id)}
        >
          <FileText size={14} />
          <span>Open source file</span>
          <ExternalLink size={12} />
        </button>
      </div>
    </aside>
  );
}
