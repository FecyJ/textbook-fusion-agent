import { ChangeEvent, DragEvent, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import * as echarts from "echarts";
import {
  Activity,
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

type UploadProgress = {
  active: boolean;
  percent: number;
  label: string;
  filename: string;
};

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
  const [uploadProgress, setUploadProgress] = useState<UploadProgress>({
    active: false,
    percent: 0,
    label: "等待教材",
    filename: "",
  });
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
    const selectedFiles = Array.from(files);
    if (!selectedFiles.length) return;
    setBusy("upload");
    setError(null);
    setUploadProgress({
      active: true,
      percent: 0,
      label: "准备上传",
      filename: selectedFiles.length === 1 ? selectedFiles[0].name : `${selectedFiles.length} 个文件`,
    });
    const form = new FormData();
    selectedFiles.forEach((file) => form.append("files", file));
    try {
      const response = await axios.post<{ textbooks: TextbookSummary[] }>("/api/textbooks/upload", form, {
        timeout: 180000,
        onUploadProgress: (event) => {
          const total = event.total ?? selectedFiles.reduce((sum, file) => sum + file.size, 0);
          const uploadPercent = total ? Math.round((event.loaded / total) * 72) : 18;
          setUploadProgress((current) => ({
            ...current,
            percent: Math.min(uploadPercent, 72),
            label: uploadPercent >= 72 ? "上传完成，解析教材中" : "上传中",
          }));
        },
      });
      setUploadProgress((current) => ({ ...current, percent: 100, label: "complete" }));
      setTextbooks((current) => mergeTextbooks(current, response.data.textbooks));
    } catch (requestError) {
      setUploadProgress((current) => ({ ...current, label: "上传失败" }));
      setError(errorMessage(requestError));
    } finally {
      setBusy(null);
      window.setTimeout(() => {
        setUploadProgress((current) => (current.percent === 100 ? { ...current, active: false } : current));
      }, 1200);
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

        <UploadProgressView progress={uploadProgress} busy={busy === "upload"} />

        <section className="metric-grid">
          <Metric label="教材" value={`${completedCount}/${textbooks.length}`} />
          <Metric label="章节" value={String(textbooks.reduce((sum, item) => sum + item.chapter_count, 0))} />
          <Metric label="图谱节点" value={String(graphNodeCount)} />
          <Metric label="RAG 块" value={String(ragStatus?.chunk_count ?? 0)} />
        </section>

        <section className="visual-legend">
          <div className="section-title">
            <Activity size={16} />
            <span>图谱编码</span>
          </div>
          <div className="legend-row">
            <i className="node-dot major" />
            <span>大节点：高频/重点概念</span>
          </div>
          <div className="legend-row">
            <i className="node-dot minor" />
            <span>小节点：章节局部概念</span>
          </div>
          <div className="legend-row">
            <i className="label-pill-demo">概念名</i>
            <span>仅关键节点常显标签</span>
          </div>
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
            <span className="graph-meta">{graphNodeCount} nodes · {graphEdgeCount} relations · click node to inspect</span>
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
          <div className="graph-toolbar">
            <span>节点尺寸 = 频次 + 定义完整度</span>
            <span>标签避让：仅重点节点常显</span>
          </div>
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
  const scoredNodes = graph.nodes.map((node) => ({
    node,
    score: nodeScore(node),
  }));
  const maxScore = Math.max(1, ...scoredNodes.map((item) => item.score));
  return {
    backgroundColor: "transparent",
    tooltip: {
      borderWidth: 0,
      backgroundColor: "rgba(24,36,43,0.92)",
      textStyle: { color: "#f7fbfa", fontSize: 12 },
      extraCssText: "max-width:340px;white-space:normal;border-radius:8px;box-shadow:0 16px 40px rgba(15,31,38,.22);",
      formatter: (params: { data: KnowledgeNode }) => {
        const node = params.data;
        if (!node?.id) return "";
        return `<strong>${escapeHtml(node.name)}</strong><br/>${escapeHtml(node.chapter)} · 第 ${node.page} 页<br/><span>${escapeHtml(node.definition || "")}</span>`;
      },
    },
    series: [
      {
        type: "graph",
        layout: "force",
        roam: true,
        draggable: true,
        cursor: "pointer",
        data: scoredNodes.map(({ node, score }) => ({
          ...node,
          value: score,
          symbol: "circle",
          symbolSize: nodeSize(score, maxScore),
          itemStyle: {
            color: nodeColor(node, colors),
            borderColor: "#f7fbfa",
            borderWidth: score > maxScore * 0.55 ? 3 : 2,
            shadowBlur: score > maxScore * 0.55 ? 18 : 8,
            shadowColor: "rgba(31,76,78,.22)",
          },
          label: {
            show: score > maxScore * 0.46,
            formatter: truncateLabel(node.name),
            position: "right",
            distance: 10,
            color: "#17242b",
            fontSize: score > maxScore * 0.7 ? 13 : 11,
            fontWeight: 700,
            lineHeight: 18,
            backgroundColor: "rgba(248,250,249,.92)",
            borderColor: "rgba(163,176,181,.72)",
            borderWidth: 1,
            borderRadius: 6,
            padding: [3, 7],
            shadowBlur: 8,
            shadowColor: "rgba(35,48,56,.12)",
          },
        })),
        links: graph.edges.map((edge) => ({
          source: edge.source,
          target: edge.target,
          label: { show: false },
          lineStyle: {
            color: relationColor(edge.relation_type),
            opacity: 0.36,
            width: edge.relation_type === "contains" ? 1.7 : 1.1,
            curveness: edge.relation_type === "parallel" ? 0.08 : 0.02,
          },
        })),
        force: { repulsion: 260, edgeLength: [86, 154], gravity: 0.05, friction: 0.62 },
        edgeSymbol: ["none", "arrow"],
        edgeSymbolSize: 5,
        scaleLimit: { min: 0.25, max: 4 },
        emphasis: {
          focus: "adjacency",
          scale: 1.2,
          label: { show: true },
          lineStyle: { opacity: 0.78, width: 2.4 },
        },
        blur: {
          itemStyle: { opacity: 0.24 },
          lineStyle: { opacity: 0.08 },
          label: { opacity: 0.18 },
        },
      },
    ],
  };
}

function UploadProgressView({ progress, busy }: { progress: UploadProgress; busy: boolean }) {
  if (!progress.active && progress.percent === 0) {
    return (
      <section className="upload-progress idle">
        <div>
          <span>导入状态</span>
          <strong>等待上传</strong>
        </div>
        <div className="progress-track">
          <i style={{ width: "0%" }} />
        </div>
      </section>
    );
  }
  return (
    <section className={`upload-progress ${progress.percent === 100 ? "complete" : ""}`}>
      <div className="progress-head">
        <div>
          <span>{progress.filename || "教材文件"}</span>
          <strong>{progress.label}</strong>
        </div>
        <b>{progress.percent}%</b>
      </div>
      <div className="progress-track">
        <i style={{ width: `${progress.percent}%` }} />
      </div>
      {busy && <small>上传完成后后端会继续解析章节，完成时教材状态变为 completed。</small>}
    </section>
  );
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

function nodeScore(node: KnowledgeNode) {
  const frequency = Math.max(1, node.frequency || 1);
  const sourceDepth = Math.min(5, Math.ceil((node.definition?.length ?? 0) / 48));
  const categoryBonus = node.category.includes("核心") ? 2 : 0;
  return frequency * 4 + sourceDepth + categoryBonus;
}

function nodeSize(score: number, maxScore: number) {
  const normalized = Math.sqrt(score / maxScore);
  return Math.round(16 + normalized * 38);
}

function nodeColor(node: KnowledgeNode, colors: Map<string, string>) {
  const base = colors.get(node.textbook_id) ?? "#276c68";
  if ((node.frequency || 1) > 2) return "#1f5957";
  return base;
}

function relationColor(type: string) {
  if (type === "contains") return "#276c68";
  if (type === "prerequisite") return "#8f5f18";
  if (type === "applies_to") return "#465f90";
  return "#7c8b91";
}

function truncateLabel(name: string) {
  return name.length > 9 ? `${name.slice(0, 9)}…` : name;
}

function escapeHtml(value: string) {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
