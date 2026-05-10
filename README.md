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

## 数据说明

教材 PDF 不提交到 GitHub。请通过前端上传教材，或在本地开发时放入 `textbooks/` 目录。

