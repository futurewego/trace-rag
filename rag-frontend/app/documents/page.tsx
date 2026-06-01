"use client";

import { useEffect, useRef, useState } from "react";

const API =
  process.env.NEXT_PUBLIC_RAG_BACKEND_URL || "http://localhost:8088";

type Doc = {
  id: number;
  filename: string;
  status: string;
  error_msg: string | null;
  page_count: number | null;
  chunk_count: number;
};

export default function DocumentsPage() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = async () => {
    try {
      const r = await fetch(`${API}/api/v1/documents`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setDocs(await r.json());
    } catch (e: any) {
      setError(e.message || "load failed");
    }
  };

  useEffect(() => {
    load();
    const id = setInterval(load, 3000);
    return () => clearInterval(id);
  }, []);

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setError(null);
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await fetch(`${API}/api/v1/documents`, {
        method: "POST",
        body: fd,
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await load();
    } catch (e: any) {
      setError(e.message || "upload failed");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <>
      <h2 style={{ marginBottom: 12 }}>Documents</h2>
      <p className="muted" style={{ marginBottom: 20 }}>Backend: {API}</p>

      <div className="card">
        <input
          ref={fileRef}
          type="file"
          accept=".pdf"
          onChange={onUpload}
          disabled={uploading}
        />
        {uploading && <span className="muted" style={{ marginLeft: 10 }}>上传中...</span>}
        {error && <div className="error" style={{ marginTop: 10 }}>{error}</div>}
      </div>

      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Filename</th>
            <th>Status</th>
            <th>Pages</th>
            <th>Chunks</th>
          </tr>
        </thead>
        <tbody>
          {docs.length === 0 && (
            <tr><td colSpan={5} className="muted">暂无文档</td></tr>
          )}
          {docs.map((d) => (
            <tr key={d.id}>
              <td>{d.id}</td>
              <td>{d.filename}</td>
              <td>
                <span className={`badge badge-${d.status}`}>{d.status}</span>
                {d.error_msg && <div className="error" style={{ fontSize: 12, marginTop: 4 }}>{d.error_msg}</div>}
              </td>
              <td>{d.page_count ?? "-"}</td>
              <td>{d.chunk_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
