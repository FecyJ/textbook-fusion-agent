import { ChangeEvent, DragEvent, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import * as echarts from "echarts";
import {
  Database,
  FileText,
  GitMerge,
  Loader2,
  MessageSquare,
  Network,
  RefreshCw,
  Search,
  Send,
  Upload,
} from "lucide-react";

type Health = {
  status: string;
  llm: {
    provider: string;
    model: string;
    base_url: string;
    api_key_configured: boolean;
  };
};

type TextbookSummary = {
  textbook_id: string;
  filename: string;
  title: string;
  file_format: string;
  size_bytes: number;
  status: "pending" | "parsing" | "completed" | "failed";
  error?: string | null;
  total_pages: number;
  total_chars: number;
  chapter_count: number;
};

type KnowledgeNode = {
  id: string;
  name: string;
  definition: string;
  category: string;
  chapter: string;
  page: number;
  textbook_id: string;
  textbook_title: string;
  source_text: string;
  frequency: number;
};

type GraphEdge = {
  source: string;
  target: string;
  relation_type: string;
  description: string;
};

type GraphData = {
  textbook_id?: string;
  nodes: KnowledgeNode[];
  edges: GraphEdge[];
};

type IntegrationState = {
  decisions: Array<{
    decision_id: string;
    action: "merge" | "keep" | "remove";
    affected_nodes: string[];
    result_node?: string | null;
    reason: string;
    confidence: number;
    status: "active" | "overridden";
  }>;
  nodes: KnowledgeNode[];
  edges: GraphEdge[];
  stats: {
    original_chars: number;
    integrated_chars: number;
    compression_ratio: number;
    original_nodes: number;
    integrated_nodes: number;
    original_edges: number;
    integrated_edges: number;
    merge_count: number;
    keep_count: number;
    remove_count: number;
  };
  conversation: Array<{ role: string; content: string; time: string }>;
};

type RagStatus = {
  textbook_count: number;
  chunk_count: number;
  indexed_at?: string | null;
};

type RagAnswer = {
  answer: string;
  citations: Array<{ textbook: string; chapter: string; page: number; relevance_score: number }>;
  source_chunks: string[];
};

type TabKey = "integration" | "rag" | "dialogue" | "report";

const palette = ["#276c68", "#8f5f18", "#465f90", "#7b4e72", "#677235", "#a34e45", "#56606b"];

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [textbooks, setTextbooks] = useState<TextbookSummary[]>([]);
  const [graph, setGraph] = useState<GraphData>({ nodes: [], edges: [] });
  const [selectedNode, setSelectedNode] = useState<KnowledgeNode | null>(null);
  const [integration, setIntegration] = useState<IntegrationState | null>(null);
  const [ragStatus, setRagStatus] = useState<RagStatus | null>(null);
  const [ragAnswer, setRagAnswer] = useState<RagAnswer | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("integration");
  const [query, setQuery] = useState("炎症是什么？");
  const [feedback, setFeedback] = useState("请保留炎症相关知识点");
  const [report, setReport] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [useLlm, setUseLlm] = useState(false);
  const chartRef = useRef<HTMLDivElement | null>(null);

  const textbookColor = useMemo(() => {
    const map = new Map<string, string>();
    textbooks.forEach((textbook, index) => map.set(textbook.textbook_id, palette[index % palette.length]));
    return map;
  }, [textbooks]);

  useEffect(() => {
    void refreshAll();
  }, []);

  useEffect(() => {
    if (!chartRef.current) return;
    const chart = echarts.init(chartRef.current);
    const option = buildGraphOption(graph, textbookColor);
    chart.setOption(option);
    chart.on("click", (params) => {
      const data = params.data as KnowledgeNode | undefined;
      if (data?.id) setSelectedNode(data);
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [graph, textbookColor]);

  async function refreshAll() {
    setError(null);
    const [healthResponse, textbookResponse, integrationResponse, ragResponse] = await Promise.all([
      axios.get<Health>("/api/health"),
      axios.get<{ textbooks: TextbookSummary[] }>("/api/textbooks"),
      axios.get<IntegrationState>("/api/integration/decisions"),
      axios.get<RagStatus>("/api/rag/status"),
    ]);
    setHealth(healthResponse.data);
    setTextbooks(textbookResponse.data.textbooks);
    setIntegration(integrationResponse.data);
    setRagStatus(ragResponse.data);
    if (integrationResponse.data.nodes.length) {
      setGraph({ nodes: integrationResponse.data.nodes, edges: integrationResponse.data.edges });
    }
  }

  async function uploadFiles(files: FileList | File[]) {
    if (!files.length) return;
    setBusy("upload");
    setError(null);
    const form = new FormData();
    Array.from(files).forEach((file) => form.append("files", file));
    try {
      const response = await axios.post<{ textbooks: TextbookSummary[] }>("/api/textbooks/upload", form);
      setTextbooks((current) => mergeTextbooks(current, response.data.textbooks));
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(null);
    }
  }

  async function buildGraphs() {
    setBusy("graph");
    setError(null);
    try {
      const response = await axios.post<{ graphs: GraphData[] }>(
        "/api/graphs/build",
        {
          use_llm: useLlm,
          llm_chapter_limit: useLlm ? 2 : 0,
          max_chapters: 80,
        },
        { timeout: 90000 },
      );
      const firstGraph = response.data.graphs[0];
      if (firstGraph) setGraph(firstGraph);
      await refreshAll();
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(null);
    }
  }

  async function runIntegration() {
    setBusy("integration");
    setError(null);
    try {
      const response = await axios.post<IntegrationState>("/api/integration/run");
      setIntegration(response.data);
      setGraph({ nodes: response.data.nodes, edges: response.data.edges });
      setActiveTab("integration");
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(null);
    }
  }

  async function indexRag() {
    setBusy("index");
    setError(null);
    try {
      const response = await axios.post<RagStatus>("/api/rag/index");
      setRagStatus(response.data);
      setActiveTab("rag");
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(null);
    }
  }

  async function askRag() {
    if (!query.trim()) return;
    setBusy("rag");
    setError(null);
    try {
      const response = await axios.post<RagAnswer>("/api/rag/query", { question: query });
      setRagAnswer(response.data);
      setActiveTab("rag");
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(null);
    }
  }

  async function sendFeedback() {
    if (!feedback.trim()) return;
    setBusy("feedback");
    setError(null);
    try {
      const response = await axios.post<IntegrationState>("/api/integration/feedback", { message: feedback });
      setIntegration(response.data);
      setActiveTab("dialogue");
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(null);
    }
  }

  async function generateReport() {
    setBusy("report");
    setError(null);
    try {
      const response = await axios.get<{ content: string; stats: IntegrationState["stats"] }>("/api/report/integration");
      setReport(response.data.content);
      setActiveTab("report");
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setBusy(null);
    }
  }

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    void uploadFiles(event.dataTransfer.files);
  }

  function onFileChange(event: ChangeEvent<HTMLInputElement>) {
    if (event.target.files) void uploadFiles(event.target.files);
  }

  const completedCount = textbooks.filter((textbook) => textbook.status === "completed").length;
  const graphNodeCount = graph.nodes.length;
  const graphEdgeCount = graph.edges.length;

  return (
    <main className="workspace">
      <aside className="left-rail">
        <header className="brand">
          <span>Textbook Fusion</span>
          <strong>医学教材整合智能体</strong>
        </header>

        <label className="upload-zone" onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
          <Upload size={22} />
          <strong>上传教材</strong>
          <span>PDF / Markdown / TXT / DOCX</span>
          <input multiple type="file" accept=".pdf,.md,.markdown,.txt,.docx" onChange={onFileChange} />
        </label>

        <section className="metric-grid">
          <Metric label="教材" value={`${completedCount}/${textbooks.length}`} />
          <Metric label="章节" value={String(textbooks.reduce((sum, item) => sum + item.chapter_count, 0))} />
          <Metric label="图谱节点" value={String(graphNodeCount)} />
          <Metric label="RAG 块" value={String(ragStatus?.chunk_count ?? 0)} />
        </section>

        <section className="book-list">
          <div className="section-title">
            <Database size={16} />
            <span>教材队列</span>
          </div>
          {textbooks.length === 0 && <p className="empty">尚未上传教材。</p>}
          {textbooks.map((textbook) => (
            <article key={textbook.textbook_id} className="book-row">
              <div>
                <strong>{textbook.title}</strong>
                <span>{formatSize(textbook.size_bytes)} · {textbook.chapter_count} 章 · {textbook.total_pages || "-"} 页</span>
              </div>
              <StatusPill status={textbook.status} />
            </article>
          ))}
        </section>
      </aside>

      <section className="graph-stage">
        <div className="topbar">
          <div>
            <span className="eyebrow">Knowledge Graph</span>
            <h1>跨教材知识结构</h1>
          </div>
          <div className="actions">
            <label className="switch">
              <input checked={useLlm} type="checkbox" onChange={(event) => setUseLlm(event.target.checked)} />
              <span>少量 LLM 增强</span>
            </label>
            <button onClick={buildGraphs} disabled={!!busy || completedCount === 0}>
              {busy === "graph" ? <Loader2 className="spin" size={16} /> : <Network size={16} />}
              构建图谱
            </button>
            <button onClick={runIntegration} disabled={!!busy || graphNodeCount === 0}>
              {busy === "integration" ? <Loader2 className="spin" size={16} /> : <GitMerge size={16} />}
              整合
            </button>
            <button onClick={refreshAll} disabled={!!busy}>
              <RefreshCw size={16} />
            </button>
          </div>
        </div>

        {error && <div className="error-bar">{error}</div>}
        <div className="graph-shell">
          <div ref={chartRef} className="graph-canvas" />
          {graphNodeCount === 0 && (
            <div className="graph-empty">
              <Network size={34} />
              <strong>等待知识图谱</strong>
              <span>上传教材后构建图谱，节点会按教材来源和出现频次编码。</span>
            </div>
          )}
        </div>

        <footer className="node-inspector">
          {selectedNode ? (
            <>
              <div>
                <span className="eyebrow">{selectedNode.textbook_title} · 第 {selectedNode.page} 页</span>
                <strong>{selectedNode.name}</strong>
              </div>
              <p>{selectedNode.definition}</p>
              <span>{selectedNode.chapter}</span>
            </>
          ) : (
            <>
              <strong>节点详情</strong>
              <span>点击图谱节点查看定义、章节、页码与来源片段。</span>
            </>
          )}
        </footer>
      </section>

      <aside className="right-panel">
        <nav className="tabs">
          <TabButton active={activeTab === "integration"} icon={<GitMerge size={15} />} label="整合" onClick={() => setActiveTab("integration")} />
          <TabButton active={activeTab === "rag"} icon={<Search size={15} />} label="RAG" onClick={() => setActiveTab("rag")} />
          <TabButton active={activeTab === "dialogue"} icon={<MessageSquare size={15} />} label="对话" onClick={() => setActiveTab("dialogue")} />
          <TabButton active={activeTab === "report"} icon={<FileText size={15} />} label="报告" onClick={() => setActiveTab("report")} />
        </nav>

        {activeTab === "integration" && (
          <Panel title="整合决策">
            <section className="stat-stack">
              <Metric label="压缩比" value={formatPercent(integration?.stats.compression_ratio ?? 0)} />
              <Metric label="节点" value={`${integration?.stats.original_nodes ?? 0}→${integration?.stats.integrated_nodes ?? 0}`} />
              <Metric label="合并/删除" value={`${integration?.stats.merge_count ?? 0}/${integration?.stats.remove_count ?? 0}`} />
            </section>
            <div className="decision-list">
              {(integration?.decisions ?? []).slice(0, 24).map((decision) => (
                <article key={decision.decision_id} className={`decision ${decision.action}`}>
                  <span>{decision.action} · {Math.round(decision.confidence * 100)}%</span>
                  <strong>{decision.decision_id}</strong>
                  <p>{decision.reason}</p>
                </article>
              ))}
              {!integration?.decisions.length && <p className="empty">运行整合后显示 merge / keep / remove 决策。</p>}
            </div>
          </Panel>
        )}

        {activeTab === "rag" && (
          <Panel title="RAG 精准问答">
            <button className="wide" onClick={indexRag} disabled={!!busy || completedCount === 0}>
              {busy === "index" ? <Loader2 className="spin" size={16} /> : <Database size={16} />}
              建立索引
            </button>
            <div className="input-row">
              <input value={query} onChange={(event) => setQuery(event.target.value)} />
              <button onClick={askRag} disabled={!!busy}>
                {busy === "rag" ? <Loader2 className="spin" size={16} /> : <Send size={16} />}
              </button>
            </div>
            <span className="subtle">已索引 {ragStatus?.textbook_count ?? 0} 本教材，共 {ragStatus?.chunk_count ?? 0} 个知识块</span>
            {ragAnswer && (
              <article className="answer">
                <p>{ragAnswer.answer}</p>
                {ragAnswer.citations.map((citation, index) => (
                  <details key={`${citation.textbook}-${index}`}>
                    <summary>{citation.textbook} · {citation.chapter} · 第 {citation.page} 页 · {citation.relevance_score.toFixed(2)}</summary>
                    <p>{ragAnswer.source_chunks[index]}</p>
                  </details>
                ))}
              </article>
            )}
          </Panel>
        )}

        {activeTab === "dialogue" && (
          <Panel title="教师反馈">
            <div className="input-row tall">
              <textarea value={feedback} onChange={(event) => setFeedback(event.target.value)} />
              <button onClick={sendFeedback} disabled={!!busy}>
                {busy === "feedback" ? <Loader2 className="spin" size={16} /> : <Send size={16} />}
              </button>
            </div>
            <div className="conversation">
              {(integration?.conversation ?? []).map((item, index) => (
                <article key={`${item.time}-${index}`} className={item.role}>
                  <span>{item.role}</span>
                  <p>{item.content}</p>
                </article>
              ))}
              {!integration?.conversation.length && <p className="empty">输入“请保留…”或“拆分…”来覆盖整合决策。</p>}
            </div>
          </Panel>
        )}

        {activeTab === "report" && (
          <Panel title="整合报告">
            <button className="wide" onClick={generateReport} disabled={!!busy}>
              {busy === "report" ? <Loader2 className="spin" size={16} /> : <FileText size={16} />}
              生成 report/整合报告.md
            </button>
            <pre className="report-preview">{report || "报告生成后会显示 Markdown 预览。"}</pre>
          </Panel>
        )}
      </aside>
    </main>
  );
}

function buildGraphOption(graph: GraphData, colors: Map<string, string>) {
  return {
    backgroundColor: "transparent",
    tooltip: {
      formatter: (params: { data: KnowledgeNode }) => params.data?.definition || params.data?.name,
    },
    series: [
      {
        type: "graph",
        layout: "force",
        roam: true,
        draggable: true,
        data: graph.nodes.map((node) => ({
          ...node,
          symbolSize: 24 + Math.min(node.frequency || 1, 6) * 7,
          itemStyle: { color: colors.get(node.textbook_id) ?? "#276c68" },
          label: { show: true, formatter: node.name, color: "#20313b", fontSize: 12 },
        })),
        links: graph.edges.map((edge) => ({
          source: edge.source,
          target: edge.target,
          label: { show: false },
          lineStyle: { color: "#8a98a5", opacity: 0.45 },
        })),
        force: { repulsion: 220, edgeLength: 112, gravity: 0.08 },
        emphasis: { focus: "adjacency" },
      },
    ],
  };
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function StatusPill({ status }: { status: TextbookSummary["status"] }) {
  return <span className={`status-pill ${status}`}>{status}</span>;
}

function TabButton({ active, icon, label, onClick }: { active: boolean; icon: React.ReactNode; label: string; onClick: () => void }) {
  return (
    <button className={active ? "active" : ""} onClick={onClick}>
      {icon}
      {label}
    </button>
  );
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="panel-section">
      <h2>{title}</h2>
      {children}
    </section>
  );
}

function mergeTextbooks(current: TextbookSummary[], incoming: TextbookSummary[]) {
  const map = new Map(current.map((item) => [item.textbook_id, item]));
  incoming.forEach((item) => map.set(item.textbook_id, item));
  return Array.from(map.values());
}

function formatSize(size: number) {
  if (size > 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  return `${(size / 1024).toFixed(1)} KB`;
}

function formatPercent(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

function errorMessage(error: unknown) {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === "string") return detail;
  }
  return error instanceof Error ? error.message : "操作失败";
}
