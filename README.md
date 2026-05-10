# Textbook Fusion Agent

AI 全栈黑客松项目：面向多本教材的知识整合、知识图谱、RAG 问答与整合报告生成。

## 环境依赖

- Python 3.10+
- Node.js 18+
- npm 9+

## 本地配置

1. 复制环境变量模板：

   ```bash
   cp .env.example .env
   ```

2. 在 `.env` 中填写大模型服务配置。当前项目默认读取：

- `DEEPSEEK_API_KEY`
- `DEEPSEEK_API_BASE_URL`
- `DEEPSEEK_MODEL`
- `TEXTBOOK_FUSION_DATA_DIR`（可选，默认 `data/`）

## 安装依赖

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
npm install
npm --prefix src/frontend install
```

## 启动

```bash
npm run dev
```

- 后端 API: http://localhost:8000
- 前端页面: http://localhost:5173
- 健康检查: http://localhost:8000/api/health

## UI 截图验证

项目已配置 Playwright，用于后续 UI 改进时截图回归。

```bash
npx playwright install chromium
npm run shot:ui
```

截图输出到 `artifacts/screenshots/workspace-1440x900.png`，测试报告输出到 `playwright-report/`。这些生成物不会提交到 Git。

## 使用流程

1. 打开前端页面，上传 PDF / Markdown / TXT / DOCX 教材。
2. 等待教材状态变为 `completed`，确认章节数和字符数。
3. 点击“构建图谱”，生成单本教材知识图谱。
4. 点击“整合”，生成跨教材 merge / keep / remove 决策和压缩统计。
5. 在 RAG 面板点击“建立索引”，输入问题后查看带引用回答。
6. 在教师反馈面板输入“请保留……”或“拆分……”来覆盖整合决策。
7. 在报告面板生成 `report/整合报告.md`。

## 主要接口

- `POST /api/textbooks/upload`
- `GET /api/textbooks`
- `POST /api/graphs/build`
- `POST /api/integration/run`
- `POST /api/rag/index`
- `POST /api/rag/query`
- `POST /api/integration/feedback`
- `GET /api/report/integration`

## 数据说明

教材 PDF 不提交到 GitHub。请通过前端上传教材，或在本地开发时放入 `textbooks/` 目录。

运行数据写入 `data/` 下的忽略目录；`.env` 中的密钥不会提交。
