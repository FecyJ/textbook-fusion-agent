import { useEffect, useState } from "react";
import axios from "axios";

type Health = {
  status: string;
  llm: {
    provider: string;
    model: string;
    base_url: string;
    api_key_configured: boolean;
  };
};

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    axios
      .get<Health>("/api/health")
      .then((response) => setHealth(response.data))
      .catch((requestError: unknown) => {
        setError(requestError instanceof Error ? requestError.message : "健康检查失败");
      });
  }, []);

  return (
    <main className="shell">
      <section className="panel">
        <p className="eyebrow">AI 全栈黑客松</p>
        <h1>Textbook Fusion Agent</h1>
        <p className="summary">项目环境已配置为 FastAPI + React/Vite，后续将在这里接入教材解析、知识图谱、RAG 问答和整合对话。</p>
        <div className="status">
          <span>API</span>
          <strong>{error ? "未连接" : health?.status ?? "检查中"}</strong>
        </div>
        {health && (
          <div className="config">
            <div>
              <span>LLM</span>
              <strong>{health.llm.provider}</strong>
            </div>
            <div>
              <span>Model</span>
              <strong>{health.llm.model}</strong>
            </div>
            <div>
              <span>Key</span>
              <strong>{health.llm.api_key_configured ? "已配置" : "未配置"}</strong>
            </div>
          </div>
        )}
        {error && <p className="error">{error}</p>}
      </section>
    </main>
  );
}

