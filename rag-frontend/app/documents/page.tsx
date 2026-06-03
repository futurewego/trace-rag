"use client";

import { useEffect, useRef, useState } from "react";

const API = "/api/backend";

type Doc = {
  id: number;
  filename: string;
  status: string;
  error_msg: string | null;
  page_count: number | null;
  chunk_count: number;
};

const STATUS_LABEL: Record<string, string> = {
  queued: "排队中",
  parsing: "解析中",
  indexed: "已索引",
  failed: "失败",
};

export default function DocumentsPage() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = async () => {
    try {
      const r = await fetch(`${API}/documents`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setDocs(await r.json());
    } catch (e: any) {
      console.error(e);
      setError("文档列表加载失败，请稍后再试。");
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
      const r = await fetch(`${API}/documents`, {
        method: "POST",
        body: fd,
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      await load();
    } catch (e: any) {
      console.error(e);
      setError("上传失败，请稍后再试。");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  return (
    <>
      <div className="card" style={{ marginBottom: 16 }}>
        <p>📁 上传企业内部文档（PDF / Word / PPT / Excel）。系统会自动解析、分块、生成向量索引，几十秒后即可在 <a href="/">问答</a> 页提问。</p>
      </div>

      <div className="card">
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.docx,.pptx,.xlsx"
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
            <th>文件名</th>
            <th>状态</th>
            <th>页数</th>
            <th>分块数</th>
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
                <span className={`badge badge-${d.status}`}>
                  {STATUS_LABEL[d.status] ?? d.status}
                </span>
                {d.error_msg && (
                  <div className="error" style={{ fontSize: 12, marginTop: 4 }}>
                    {d.error_msg}
                  </div>
                )}
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
