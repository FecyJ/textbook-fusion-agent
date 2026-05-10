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
  Trash2,
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
  quality_score?: number;
  extraction_method?: string;
  warnings?: string[];
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

const LABEL_ZOOM_THRESHOLD = 1.2;
const EMPTY_PROGRESS: OperationProgress = { active: false, percent: 0, label: "等待任务", detail: "" };

type OperationProgress = {
  active: boolean;
  percent: number;
  label: string;
  detail: string;
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
  const [query, setQuery] = useState("这个概念的核心定义是什么？");
  const [feedback, setFeedback] = useState("请保留这个关键知识点");
  const [report, setReport] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [removingTextbookId, setRemovingTextbookId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [useLlm, setUseLlm] = useState(true);
  const [graphZoom, setGraphZoom] = useState(1);
  const [uploadProgress, setUploadProgress] = useState<UploadProgress>({
    active: false,
    percent: 0,
    label: "等待教材",
    filename: "",
  });
  const [graphProgress, setGraphProgress] = useState<OperationProgress>(EMPTY_PROGRESS);
  const [integrationProgress, setIntegrationProgress] = useState<OperationProgress>(EMPTY_PROGRESS);
  const chartRef = useRef<HTMLDivElement | null>(null);
  const graphZoomRef = useRef(1);

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
    graphZoomRef.current = 1;
    setGraphZoom(1);
    const option = buildGraphOption(graph, textbookColor, graphZoomRef.current);
    chart.setOption(option);
    chart.on("click", (params) => {
      const data = params.data as KnowledgeNode | undefined;
      if (data?.id) setSelectedNode(data);
    });
    chart.on("graphRoam", (params: unknown) => {
      const roam = params as { zoom?: unknown };
      if (typeof roam.zoom === "number") {
        const nextZoom = clampZoom(graphZoomRef.current * roam.zoom);
        graphZoomRef.current = nextZoom;
        setGraphZoom(nextZoom);
        chart.setOption({
          series: [
            {
              data: buildGraphSeriesData(graph, textbookColor, nextZoom),
            },
          ],
        });
      }
    });
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
    };
  }, [graph, textbookColor]);

  async function refreshAll(options: { preserveGraph?: boolean } = {}) {
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
    if (!options.preserveGraph && integrationResponse.data.nodes.length) {
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

  async function removeTextbook(textbookId: string) {
    setRemovingTextbookId(textbookId);
    setError(null);
    try {
      const response = await axios.delete<{
        textbooks: TextbookSummary[];
        graphs: GraphData[];
        integration: IntegrationState;
        rag_status: RagStatus;
      }>(`/api/textbooks/${textbookId}`);
      setTextbooks(response.data.textbooks);
      setIntegration(response.data.integration);
      setRagStatus(response.data.rag_status);
      setSelectedNode((current) => (current?.textbook_id === textbookId ? null : current));
      const nextGraph = response.data.integration.nodes.length
        ? { nodes: response.data.integration.nodes, edges: response.data.integration.edges }
        : response.data.graphs[0] ?? { nodes: [], edges: [] };
      setGraph(nextGraph);
      setGraphZoom(1);
    } catch (requestError) {
      setError(errorMessage(requestError));
    } finally {
      setRemovingTextbookId(null);
    }
  }

  async function buildGraphs() {
    setBusy("graph");
    setError(null);
    const targetIds = targetGraphTextbookIds(textbooks);
    startOperationProgress(
      setGraphProgress,
      "构建图谱",
      useLlm ? "清洗章节、调用 LLM 抽取节点与关系" : "使用本地候选抽取节点与关系",
      18,
    );
    try {
      const response = await axios.post<{ built: Array<{ textbook_id: string; nodes: number; edges: number; quality?: GraphQuality }>; graphs: GraphData[] }>(
        "/api/graphs/build",
        {
          textbook_ids: targetIds,
          use_llm: useLlm,
          llm_chapter_limit: useLlm ? 4 : 0,
          max_chapters: 80,
          build_timeout_seconds: 60,
        },
        { timeout: 150000 },
      );
      const builtIds = new Set(response.data.built.map((item) => item.textbook_id));
      const nextGraph = response.data.graphs.find((item) => item.textbook_id && builtIds.has(item.textbook_id)) ?? response.data.graphs[0];
      if (nextGraph) setGraph(nextGraph);
      completeOperationProgress(setGraphProgress, "图谱构建完成", `${nextGraph?.nodes.length ?? 0} 个节点 · ${nextGraph?.edges.length ?? 0} 条关系`);
      await refreshAll({ preserveGraph: true });
    } catch (requestError) {
      failOperationProgress(setGraphProgress, "图谱构建失败");
      setError(errorMessage(requestError));
    } finally {
      setBusy(null);
    }
  }

  async function runIntegration() {
    setBusy("integration");
    setError(null);
    startOperationProgress(setIntegrationProgress, "整合图谱", "对齐重复知识点、重映射关系并计算压缩比", 22);
    try {
      const response = await axios.post<IntegrationState>("/api/integration/run");
      setIntegration(response.data);
      setGraph({ nodes: response.data.nodes, edges: response.data.edges });
      setActiveTab("integration");
      completeOperationProgress(
        setIntegrationProgress,
        "整合完成",
        `${response.data.stats.original_nodes}→${response.data.stats.integrated_nodes} 节点 · 压缩比 ${formatPercent(response.data.stats.compression_ratio)}`,
      );
    } catch (requestError) {
      failOperationProgress(setIntegrationProgress, "整合失败");
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
  const graphQuality = useMemo(() => summarizeGraphQuality(graph), [graph]);

  return (
    <main className="workspace">
      <aside className="left-rail">
        <header className="brand">
          <span>Textbook Fusion</span>
          <strong>教材知识整合智能体</strong>
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
          <Metric label="平均质量" value={graphQuality.avgQuality ? graphQuality.avgQuality.toFixed(2) : "-"} />
        </section>

        <section className="visual-legend">
          <div className="section-title">
            <Activity size={16} />
            <span>图谱编码</span>
          </div>
          <div className="legend-row">
            <i className="node-dot major" />
            <span>大节点：高连接/高频/多来源概念</span>
          </div>
          <div className="legend-row">
            <i className="node-dot minor" />
            <span>黄色小节点：低连接章节局部概念</span>
          </div>
          <div className="legend-row">
            <i className="node-dot warning" />
            <span>描边节点：低质量或含抽取警告</span>
          </div>
          <div className="relation-legend">
            <span><i style={{ background: relationColor("prerequisite") }} />前置依赖 A→B</span>
            <span><i style={{ background: relationColor("contains") }} />包含 A→B</span>
            <span><i style={{ background: relationColor("applies_to") }} />应用 A→B</span>
            <span><i style={{ background: relationColor("parallel") }} />并列</span>
          </div>
          <div className="legend-row">
            <i className="label-pill-demo">概念名</i>
            <span>放大到 {LABEL_ZOOM_THRESHOLD.toFixed(1)}x 后显示概念名</span>
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
              <div className="book-actions">
                <StatusPill status={textbook.status} />
                <button
                  aria-label={`移除 ${textbook.title}`}
                  className="icon-button danger"
                  disabled={!!busy || removingTextbookId === textbook.textbook_id}
                  title="移除教材"
                  onClick={() => void removeTextbook(textbook.textbook_id)}
                >
                  {removingTextbookId === textbook.textbook_id ? <Loader2 className="spin" size={15} /> : <Trash2 size={15} />}
                </button>
              </div>
            </article>
          ))}
        </section>
      </aside>

      <section className="graph-stage">
        <div className="topbar">
          <div>
            <span className="eyebrow">Knowledge Graph</span>
            <h1>跨教材知识结构</h1>
            <span className="graph-meta">
              {graphNodeCount} nodes · {graphEdgeCount} relations · {graphQuality.warningCount} warnings · click node to inspect
            </span>
          </div>
          <div className="actions">
            <label className="switch">
              <input checked={useLlm} type="checkbox" onChange={(event) => setUseLlm(event.target.checked)} />
              <span>LLM 章节抽取</span>
            </label>
            <button onClick={buildGraphs} disabled={!!busy || completedCount === 0}>
              {busy === "graph" ? <Loader2 className="spin" size={16} /> : <Network size={16} />}
              构建图谱
            </button>
            <button onClick={runIntegration} disabled={!!busy || graphNodeCount === 0}>
              {busy === "integration" ? <Loader2 className="spin" size={16} /> : <GitMerge size={16} />}
              整合
            </button>
            <button onClick={() => void refreshAll()} disabled={!!busy}>
              <RefreshCw size={16} />
            </button>
          </div>
        </div>

        {error && <div className="error-bar">{error}</div>}
        <div className="graph-shell">
          <div className="graph-toolbar">
            <span>节点尺寸 = 连接度 + 频次 + 质量分；低质量节点会降权</span>
            <span>当前缩放 {graphZoom.toFixed(1)}x · {graphZoom >= LABEL_ZOOM_THRESHOLD ? "显示标签" : "隐藏标签"}</span>
          </div>
          <OperationProgressView progress={busy === "integration" ? integrationProgress : graphProgress} />
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
                <div className="node-badges">
                  <span>{selectedNode.category}</span>
                  <span>{selectedNode.extraction_method || "heuristic"}</span>
                  <span>质量 {(selectedNode.quality_score ?? 1).toFixed(2)}</span>
                  {!!selectedNode.warnings?.length && <span className="warn">{selectedNode.warnings.length} warning</span>}
                </div>
              </div>
              <p>{selectedNode.definition}</p>
              <span>{selectedNode.chapter}<br />{selectedNode.source_text}</span>
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

        <div className="tab-content">
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
        </div>
      </aside>
    </main>
  );
}

function buildGraphOption(graph: GraphData, colors: Map<string, string>, zoom: number) {
  const scoredNodes = scoreGraphNodes(graph);
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
        data: mapGraphNodes(scoredNodes, colors, zoom),
        links: graph.edges.map(mapGraphEdge),
        force: { repulsion: 310, edgeLength: [92, 166], gravity: 0.045, friction: 0.6 },
        edgeSymbol: ["none", "arrow"],
        edgeSymbolSize: 7,
        nodeScaleRatio: 0.26,
        labelLayout: { hideOverlap: true },
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

function buildGraphSeriesData(graph: GraphData, colors: Map<string, string>, zoom: number) {
  return mapGraphNodes(scoreGraphNodes(graph), colors, zoom);
}

function mapGraphEdge(edge: GraphEdge) {
  const style = relationStyle(edge.relation_type);
  return {
    source: edge.source,
    target: edge.target,
    label: { show: false },
    lineStyle: {
      color: style.color,
      opacity: style.opacity,
      width: style.width,
      type: style.type,
      curveness: style.curveness,
    },
    edgeSymbol: edge.relation_type === "parallel" ? ["none", "none"] : ["none", "arrow"],
    edgeSymbolSize: style.arrow,
    tooltip: {
      formatter: relationLabel(edge.relation_type),
    },
  };
}

function startOperationProgress(
  setter: React.Dispatch<React.SetStateAction<OperationProgress>>,
  label: string,
  detail: string,
  percent: number,
) {
  setter({ active: true, percent, label, detail });
  window.setTimeout(() => setter((current) => (current.active ? { ...current, percent: Math.max(current.percent, 42), detail } : current)), 500);
  window.setTimeout(() => setter((current) => (current.active ? { ...current, percent: Math.max(current.percent, 68), detail } : current)), 1600);
  window.setTimeout(() => setter((current) => (current.active ? { ...current, percent: Math.max(current.percent, 88), detail } : current)), 4200);
}

function completeOperationProgress(
  setter: React.Dispatch<React.SetStateAction<OperationProgress>>,
  label: string,
  detail: string,
) {
  setter({ active: false, percent: 0, label, detail });
}

function failOperationProgress(setter: React.Dispatch<React.SetStateAction<OperationProgress>>, label: string) {
  setter((current) => ({ ...current, active: false, label, detail: "请查看错误提示", percent: Math.max(current.percent, 12) }));
}

function OperationProgressView({ progress }: { progress: OperationProgress }) {
  if (!progress.active && progress.percent === 0) return null;
  return (
    <section className={`operation-progress ${progress.percent === 100 ? "complete" : ""}`}>
      <div>
        <strong>{progress.label}</strong>
        <span>{progress.detail}</span>
      </div>
      <b>{progress.percent}%</b>
      <i style={{ width: `${progress.percent}%` }} />
    </section>
  );
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

function targetGraphTextbookIds(textbooks: TextbookSummary[]) {
  const completed = textbooks.filter((item) => item.status === "completed");
  if (!completed.length) return [];
  return [completed[completed.length - 1].textbook_id];
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

type ScoredNode = {
  node: KnowledgeNode;
  degree: number;
  score: number;
  normalized: number;
  size: number;
  layout?: { x: number; y: number; fixed?: boolean };
};

type GraphQuality = {
  avg_quality: number;
  warning_count: number;
  methods: Record<string, number>;
};

function summarizeGraphQuality(graph: GraphData) {
  if (!graph.nodes.length) return { avgQuality: 0, warningCount: 0 };
  const qualitySum = graph.nodes.reduce((sum, node) => sum + (node.quality_score ?? 1), 0);
  const warningCount = graph.nodes.reduce((sum, node) => sum + (node.warnings?.length ?? 0), 0);
  return {
    avgQuality: qualitySum / graph.nodes.length,
    warningCount,
  };
}

function scoreGraphNodes(graph: GraphData): ScoredNode[] {
  const degree = new Map<string, number>();
  graph.edges.forEach((edge) => {
    degree.set(edge.source, (degree.get(edge.source) ?? 0) + 1);
    degree.set(edge.target, (degree.get(edge.target) ?? 0) + 1);
  });

  const rawScores = graph.nodes.map((node) => {
    const nodeDegree = degree.get(node.id) ?? 0;
    const frequency = Math.max(1, node.frequency || 1);
    const definitionDepth = Math.min(8, Math.log2((node.definition?.length ?? 0) + 8));
    const sourceDepth = Math.min(6, Math.log2((node.source_text?.length ?? 0) + 8));
    const categoryBonus = node.category.includes("核心") ? 3 : 0;
    const quality = Math.max(0.35, Math.min(1, node.quality_score ?? 1));
    const warningPenalty = (node.warnings?.length ?? 0) * 5;
    const score = (nodeDegree * 10 + Math.log2(frequency + 1) * 14 + definitionDepth * 2.2 + sourceDepth + categoryBonus) * quality - warningPenalty;
    return { node, degree: nodeDegree, score };
  });

  const scores = rawScores.map((item) => item.score);
  const minScore = scores.length ? Math.min(...scores) : 0;
  const maxScore = scores.length ? Math.max(...scores) : 1;
  const spread = maxScore - minScore;
  const rankedIds = [...rawScores].sort((a, b) => a.score - b.score).map((item) => item.node.id);

  const containmentLayout = buildContainmentLayout(graph);
  return rawScores.map((item) => {
    const rank = rankedIds.indexOf(item.node.id);
    const rankFallback = rawScores.length > 1 ? rank / (rawScores.length - 1) : 0.5;
    const normalized = spread > 0.001 ? (item.score - minScore) / spread : rankFallback;
    const layout = containmentLayout.get(item.node.id);
    return {
      ...item,
      normalized,
      size: Math.round(12 + Math.pow(normalized, 0.72) * 48),
      layout,
    };
  });
}

function mapGraphNodes(nodes: ScoredNode[], colors: Map<string, string>, zoom: number) {
  const labelsVisible = zoom >= LABEL_ZOOM_THRESHOLD;
  return nodes.map(({ node, score, degree, normalized, size, layout }) => ({
    ...node,
    value: score,
    degree,
    symbol: "circle",
    symbolSize: size,
    x: layout?.x,
    y: layout?.y,
    fixed: layout?.fixed,
    itemStyle: {
      color: nodeColor(node, colors, normalized),
      borderColor: "#f7fbfa",
      borderWidth: (node.warnings?.length ?? 0) > 0 || (node.quality_score ?? 1) < 0.68 ? 4 : normalized > 0.58 ? 3 : 2,
      borderType: (node.warnings?.length ?? 0) > 0 || (node.quality_score ?? 1) < 0.68 ? "dashed" : "solid",
      shadowBlur: 7 + normalized * 18,
      shadowColor: "rgba(31,76,78,.22)",
    },
    label: {
      show: labelsVisible,
      formatter: truncateLabel(node.name),
      position: "right",
      distance: 8 + Math.round(normalized * 8),
      color: "#17242b",
      fontSize: normalized > 0.7 ? 13 : 11,
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
  }));
}

function nodeColor(node: KnowledgeNode, colors: Map<string, string>, normalized: number) {
  const base = colors.get(node.textbook_id) ?? "#276c68";
  if ((node.frequency || 1) > 2 || normalized > 0.72) return "#1f5957";
  if (normalized < 0.34) return "#d49b2a";
  return base;
}

function buildContainmentLayout(graph: GraphData) {
  const layout = new Map<string, { x: number; y: number; fixed?: boolean }>();
  const childrenByParent = new Map<string, string[]>();
  graph.edges.forEach((edge) => {
    if (edge.relation_type !== "contains") return;
    const children = childrenByParent.get(edge.source) ?? [];
    children.push(edge.target);
    childrenByParent.set(edge.source, children);
  });
  const groups = Array.from(childrenByParent.entries())
    .filter(([, children]) => children.length >= 2)
    .sort((left, right) => right[1].length - left[1].length)
    .slice(0, 10);
  groups.forEach(([parentId, childIds], groupIndex) => {
    const column = groupIndex % 3;
    const row = Math.floor(groupIndex / 3);
    const centerX = (column - 1) * 420;
    const centerY = row * 320 - 210;
    const radius = 150 + Math.min(80, childIds.length * 12);
    layout.set(parentId, { x: centerX, y: centerY, fixed: true });
    childIds.slice(0, 18).forEach((childId, childIndex) => {
      const angle = -Math.PI / 2 + (Math.PI * 2 * childIndex) / Math.max(3, Math.min(18, childIds.length));
      layout.set(childId, {
        x: centerX + Math.cos(angle) * radius,
        y: centerY + Math.sin(angle) * radius,
        fixed: true,
      });
    });
  });
  return layout;
}

function clampZoom(value: number) {
  return Math.max(0.25, Math.min(4, value));
}

function relationColor(type: string) {
  return relationStyle(type).color;
}

function relationStyle(type: string) {
  if (type === "contains") return { color: "#1f6f64", width: 2.6, opacity: 0.66, type: "solid", curveness: 0.02, arrow: 9 };
  if (type === "prerequisite") return { color: "#b46d1a", width: 2.2, opacity: 0.68, type: "solid", curveness: 0.14, arrow: 9 };
  if (type === "applies_to") return { color: "#3f65a7", width: 2.0, opacity: 0.64, type: "dotted", curveness: -0.12, arrow: 8 };
  return { color: "#7c8b91", width: 1.15, opacity: 0.3, type: "dashed", curveness: 0.08, arrow: 0 };
}

function relationLabel(type: string) {
  if (type === "contains") return "contains：A 包含 B";
  if (type === "prerequisite") return "prerequisite：A 是 B 的前置知识";
  if (type === "applies_to") return "applies_to：A 应用于 B";
  return "parallel：同层级并列知识点";
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
