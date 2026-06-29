# 学习计划工作流

学习计划工作流是 EduAgents 当前实现的核心能力，面向教育场景中的个性化学习规划问题。学生输入学习内容、当前基础、学习周期、每天学习时间和学习目标后，系统会通过多智能体协作生成一份结构化、可执行、可检查的 Markdown 学习计划。

这个项目不是简单的聊天式学习建议生成器，而是把学习规划拆成多个步骤：先解析输入和分析需求，再拆解学习内容，随后检索并筛选资料，最后生成学习路线、练习任务和验收标准。

## 功能特性

- 支持一句话学习需求解析，并自动填入结构化表单。
- 支持学习内容、当前基础、学习周期、每日时间和学习目标输入。
- 使用 LangChain 调用 OpenAI 兼容模型，默认适配 DeepSeek。
- 使用 Tavily 进行联网搜索；未配置 Tavily 时可降级运行。
- 使用多个 Agent 进行需求分析、内容拆解、资料整理、资源评估、计划生成、练习设计和最终优化。
- 使用规则校验器检查计划结构、天数、任务完整性、空泛表达和资源链接。
- 使用 Streamlit 提供正式页面，支持最终计划展示、过程详情查看和 Markdown 下载。

## 技术栈

- Python
- Streamlit
- LangChain
- langchain-openai
- langchain-tavily
- Pydantic
- python-dotenv
- pytest

## 项目结构

```text
EduAgents/
├─ app/
│  └─ streamlit_app.py
├─ src/
│  └─ edu_agent/
│     ├─ config/
│     │  └─ settings.py
│     ├─ core/
│     │  ├─ llm.py
│     │  ├─ agent_runner.py
│     │  └─ exceptions.py
│     ├─ tools/
│     │  ├─ web_search.py
│     │  ├─ course_kb.py
│     │  └─ student_memory.py
│     ├─ workflows/
│     │  ├─ study_plan/
│     │  │  ├─ workflow.py
│     │  │  ├─ agents.py
│     │  │  ├─ input_parser.py
│     │  │  ├─ schemas.py
│     │  │  ├─ prompts.py
│     │  │  ├─ validator.py
│     │  │  └─ resource_rules.py
│     │  ├─ mistake_reflection/
│     │  ├─ quiz_generation/
│     │  └─ learning_report/
│     └─ router/
│        └─ workflow_router.py
├─ .env.example
├─ requirements.txt
└─ README.md
```

## 工作流

当前学生学习规划工作流如下：

```text
用户输入
→ Input Parser
→ Analyzer
→ Decomposer
→ Researcher
→ ResourceEvaluator
→ Planner
→ PracticeDesigner
→ PlanValidator
→ Reviewer
→ 最终学习计划
```

各模块职责：

| 模块 | 职责 |
| -- | -- |
| Input Parser | 将一句话学习需求解析为结构化表单字段 |
| Analyzer | 分析学习主题、当前基础、学习目标和搜索关键词 |
| Decomposer | 拆解前置知识、核心知识点、学习顺序和难点 |
| Researcher | 根据搜索关键词调用联网搜索并整理资料 |
| ResourceEvaluator | 对搜索资源进行类型识别、评分和阶段适配 |
| Planner | 生成阶段路线、每日计划、推荐资源和验收标准 |
| PracticeDesigner | 设计练习任务、阶段检查和综合实践 |
| PlanValidator | 使用规则检查计划结构、天数、任务完整性和空泛表达 |
| Reviewer | 根据校验结果生成最终优化后的学习计划 |

## 环境变量

复制 `.env.example` 为 `.env`：

```bash
cp .env.example .env
```

然后填写：

```env
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-chat
TAVILY_API_KEY=
```

说明：

- `OPENAI_API_KEY`：必填，用于调用 OpenAI 或兼容接口。
- `OPENAI_BASE_URL`：可选，默认示例为 DeepSeek OpenAI 兼容接口。
- `OPENAI_MODEL`：默认示例为 `deepseek-chat`。
- `TAVILY_API_KEY`：可选。未配置时系统会提示未启用联网搜索，并基于模型和学生输入继续生成学习计划。

## 安装依赖

推荐使用独立 Python 环境：

```bash
cd /home/shunw/EduAgents
pip install -r requirements.txt
```

如果使用 conda：

```bash
conda create -n EduAgent python=3.11 -y
conda activate EduAgent
cd /home/shunw/EduAgents
pip install -r requirements.txt
```

## 运行

```bash
cd /home/shunw/EduAgents
streamlit run app/streamlit_app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true --browser.gatherUsageStats false
```

访问：

```text
http://127.0.0.1:8501
```

如果端口被占用，可以换端口：

```bash
streamlit run app/streamlit_app.py --server.address 0.0.0.0 --server.port 8502 --server.headless true --browser.gatherUsageStats false
```


## 示例输入

一句话输入示例：

```text
我想在 14 天内学习 Python 数据分析，基础是会基础 Python，但不熟悉 pandas 和可视化，每天 1.5 小时，目标是完成一个数据清洗、分析和可视化报告。
```

表单输入示例：

| 字段 | 示例 |
| -- | -- |
| 学习内容 | Python 数据分析 |
| 当前基础 | 会基础 Python，但不熟悉 pandas 和可视化 |
| 学习周期 | 14 天 |
| 每天学习时间 | 1.5 小时 |
| 学习目标 | 能独立完成一个数据清洗、分析和可视化报告 |

## 输出内容

最终学习计划会以 Markdown 形式展示，主要包含：

- 计划摘要
- 学习路线概览
- 阶段安排
- 每日学习计划
- 练习任务
- 推荐资源
- 最终验收标准
- 执行建议

页面还会在过程详情中展示需求分析、内容拆解、搜索结果、资源评估、练习设计、规则校验和 Reviewer 检查结果。

## 后续扩展

当前项目已经预留以下扩展点：

- `src/edu_agent/tools/course_kb.py`：后续可接入 LlamaIndex 或其他课程知识库。
- `src/edu_agent/tools/student_memory.py`：后续可接入学生错题、练习记录和学习历史。
- `src/edu_agent/workflows/mistake_reflection/`：后续可扩展错题反思工作流。
- `src/edu_agent/workflows/quiz_generation/`：后续可扩展练习生成工作流。
- `src/edu_agent/workflows/learning_report/`：后续可扩展学情分析工作流。

整体原则：共享能力放在 `tools/` 和 `core/`，具体业务流程放在 `workflows/`。每个 workflow 可以独立维护自己的 `workflow.py`、`agents.py`、`schemas.py` 和 `prompts.py`。
