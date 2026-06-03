"use client";

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
      const res = await fetch(`${API}/api/v1/chat`, {
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
      setError(e.message || "请求失败");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <h2 style={{ marginBottom: 12 }}>Chat</h2>
      <p className="muted" style={{ marginBottom: 20 }}>
        Backend: {API} {sessionId ? `· session ${sessionId}` : ""}
      </p>

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
                    {c.page_num ? ` · 第 ${c.page_num} 页` : ""} · score{" "}
                    {c.score.toFixed(3)}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
        {loading && <div className="muted">思考中...</div>}
        {error && <div className="error">错误: {error}</div>}
      </div>

      <div className="card">
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="问题（如：这份合同的违约责任如何约定？）"
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
