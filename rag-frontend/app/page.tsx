"use client";

import Link from "next/link";
import { useState } from "react";

const API = "/api/backend";

type Citation = {
  doc_id: number;
  filename: string;
  page_num: number | null;
  chunk_id: number;
  score: number;
};

type Message = {
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
};

export default function ChatPage() {
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    const trimmed = input.trim();
    if (!trimmed || loading) return;
    setError(null);
    setLoading(true);

    const userMsg: Message = { role: "user", content: trimmed };
    setMessages((m) => [...m, userMsg]);
    setInput("");

    try {
      const res = await fetch(`${API}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message: trimmed }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setSessionId(data.session_id);
      setMessages((m) => [
        ...m,
        {
          role: "assistant",
          content: data.answer,
          citations: data.citations,
        },
      ]);
    } catch (e: any) {
      console.error(e);
      setError("服务暂时无响应，请稍后再试。");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      {messages.length === 0 && (
        <div className="card" style={{ marginBottom: 16 }}>
          <p>👋 把企业内部 PDF 传到 <Link href="/documents">文档</Link>，然后在下方提问。</p>
          <p className="muted" style={{ marginTop: 6 }}>
            每个回答会标注 <code>[1] [2]</code> 引用，对应原文页码可追溯。
          </p>
        </div>
      )}

      <div className="messages">
        {messages.map((m, i) => (
          <div key={i} className={`message message-${m.role}`}>
            <div>{m.content}</div>
            {m.citations && m.citations.length > 0 && (
              <div style={{ marginTop: 10 }}>
                {m.citations.map((c, idx) => (
                  <div key={idx} className="citation">
                    <span className="citation-num">[{idx + 1}]</span>
                    {c.filename}
                    {c.page_num ? ` · 第 ${c.page_num} 页` : ""}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
        {loading && <div className="muted">思考中...</div>}
        {error && <div className="error">{error}</div>}
      </div>

      <div className="card">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="提问（如：这份合同的违约责任如何约定？）"
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) send();
          }}
        />
        <div style={{ marginTop: 10, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span className="muted">Cmd/Ctrl+Enter 发送</span>
          <button onClick={send} disabled={loading || !input.trim()}>
            {loading ? "..." : "发送"}
          </button>
        </div>
      </div>
    </>
  );
}
