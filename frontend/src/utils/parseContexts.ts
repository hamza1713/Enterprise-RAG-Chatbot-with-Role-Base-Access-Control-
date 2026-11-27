/**
 * Safely parse RAGAS retrieved_contexts values from API records.
 * Supports arrays, valid JSON strings, and Python list repr strings containing apostrophes.
 */
export function parseContexts(contexts: string | string[] | undefined): string[] {
  if (!contexts) return [];
  if (Array.isArray(contexts)) return contexts.map((item) => String(item));

  const str = contexts.trim();
  if (!str) return [];

  if (str.startsWith('[') && str.endsWith(']')) {
    try {
      const parsed = JSON.parse(str);
      if (Array.isArray(parsed)) {
        return parsed.map((item) => String(item));
      }
    } catch {
      // Fallback for Python list repr strings without corrupting inner apostrophes (e.g. "FinSolve's")
      const items: string[] = [];
      let i = 1;
      const n = str.length - 1;
      while (i < n) {
        while (i < n && /[\s,]/.test(str[i])) i++;
        if (i >= n) break;
        const quote = str[i];
        if (quote === "'" || quote === '"') {
          i++;
          let current = '';
          while (i < n) {
            const ch = str[i];
            if (ch === '\\' && i + 1 < n) {
              const nxt = str[i + 1];
              current += nxt === 'n' ? '\n' : nxt === 't' ? '\t' : nxt;
              i += 2;
              continue;
            }
            if (ch === quote) {
              i++;
              break;
            }
            current += ch;
            i++;
          }
          items.push(current);
        } else {
          let end = i;
          while (end < n && str[end] !== ',') end++;
          const raw = str.slice(i, end).trim();
          if (raw) items.push(raw);
          i = end + 1;
        }
      }
      if (items.length > 0) return items;
    }
  }

  return [str];
}
