# Local RAG · AI 应用中台

Local RAG 将资料导入、知识检索、应用调试、评测和发布放在同一个工作空间。前端使用 React 和 Vite，后端使用 FastAPI，本地运行使用 SQLite。

## 快速开始

准备 Python 3.11–3.13、Node.js 22.12+ 和 pnpm。在仓库根目录执行：

```sh
python3 scripts/setup-local.py
python3 scripts/start-local.py
```

打开 [工作台](http://127.0.0.1:4173/) 或 [API 文档](http://127.0.0.1:8001/docs)。本地默认免登录，服务仅监听本机。保持启动终端运行，按 Ctrl+C 停止服务。

## 使用流程

1. 在「工具 → 模型」接入对话模型和索引模型。需要调用外部模型时，在「设置 → 本地环境」按需开启云端处理。
2. 在知识库导入文件、网页或文本，预览分块后构建索引。已有分块但尚无向量索引时，可先使用全文检索。
3. 创建简易应用或 Agent，关联知识库、配置提示词，再在草稿中调试并核对引用。
4. 为评测用例填写判定标准。评测区分执行可用性和回答质量，发布门禁需要基于当前草稿和判定标准运行。
5. 发布后从工作台使用应用，在看板查看运行记录、引用和反馈。

## 目录

| 路径 | 用途 |
| --- | --- |
| `platform/src/` | 当前前端 |
| `platform/backend/` | 当前 API、数据库迁移及后端依赖 |
| `scripts/` | 安装、启动及旧版资料迁移 |
| `frontend/`、`backend/` | 旧版源码 |

本地运行生成的资料、模型配置及数据库保存在运行机器上。已有旧版资料时，可使用 `python3 scripts/migrate-local.py` 迁移支持的内容。

当前平台基于 [zhishu-rag-platform 的固定提交](https://github.com/chusimin/zhishu-rag-platform/tree/b2f28438bb8c955e3ffda6f84a1c291e6a620644) 适配。
