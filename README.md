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
- 将内容拆解结果组织成知识目录、推荐学习路径和知识卡片。
- 支持选择知识点生成专题讲解、示例、练习和完成检查。
- 支持围绕当前学习计划和选中知识点连续提问。
- 支持知识库对话问答：结合知识库内容生成口语化、分步骤回答，涉及知识点自动附来源引用；知识库未覆盖时明确说明并引导进入学情诊断，不编造内容；模型平台不可用或超时时自动降级为本地知识库检索回答，对话不中断。
- 使用 Streamlit 提供工作流中心和统一学习工作台，支持知识学习、最终计划、AI 助教、过程详情和 Markdown 下载。

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
│     │  ├─ kb_store.py
│     │  ├─ github_importer.py
│     │  └─ student_memory.py
│     ├─ workflows/
│     │  ├─ study_plan/
│     │  │  ├─ workflow.py
│     │  │  ├─ agents.py
│     │  │  ├─ input_parser.py
│     │  │  ├─ schemas.py
│     │  │  ├─ prompts.py
│     │  │  ├─ knowledge_map.py
│     │  │  ├─ validator.py
│     │  │  └─ resource_rules.py
│     │  ├─ kb_qa/
│     │  │  ├─ workflow.py
│     │  │  ├─ rules.py
│     │  │  ├─ prompts.py
│     │  │  └─ schemas.py
│     │  ├─ topic_tutor/
│     │  │  ├─ workflow.py
│     │  │  ├─ prompts.py
│     │  │  └─ schemas.py
│     │  ├─ plan_chat/
│     │  │  ├─ workflow.py
│     │  │  ├─ prompts.py
│     │  │  └─ schemas.py
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

规划完成后提供两个按需交互工作流：

| 工作流 | 职责 |
| -- | -- |
| TopicTutor | 围绕选中的知识节点生成专题讲解、示例、练习和完成检查 |
| PlanChat | 携带学生信息、当前计划、知识点和资源进行连续问答，必要时按需搜索 |

另提供知识库对话问答工作流（kb_qa）：

| 工作流 | 职责 |
| -- | -- |
| KbQa | 结合知识库内容生成口语化、分步骤回答，附来源引用（标题+定位）；提问笼统时先引导选择方向（概念/代码/易错点）；知识库未覆盖时明确说明并建议进入学情诊断，不编造；模型平台不可用/超时自动降级为本地检索回答，对话不中断 |

知识库默认从空库开始（不再内置示例数据），导入的内容持久化到 `data/knowledge_base.json`（`tools/kb_store.py`），Streamlit 重启不丢失；侧栏支持**从 GitHub 仓库导入**（`tools/github_importer.py`：浅克隆 → 读取 .md/.txt/.rst/.ipynb 文档 → 分块入知识库，URL 白名单校验防注入），也支持**直接导入 .md/.txt 文件**与粘贴 Markdown 扩充，并可一键**清空知识库**。

知识库对话问答的模型调用优先走星辰平台（`XINGCHEN_*` 或 `OPENCODE_ZEN_*` 配置），未配置时回落 `OPENAI_*`；`OPENAI_MODEL` 支持逗号分隔的**多模型 fallback 链**（主模型限流/失败自动切换下一个）。

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
XINGCHEN_API_KEY=
XINGCHEN_BASE_URL=
XINGCHEN_MODEL=
```

说明：

- `OPENAI_API_KEY`：必填，用于调用 OpenAI 或兼容接口。
- `OPENAI_BASE_URL`：可选，默认示例为 DeepSeek OpenAI 兼容接口。
- `OPENAI_MODEL`：默认示例为 `deepseek-chat`。
- `TAVILY_API_KEY`：可选。未配置时系统会提示未启用联网搜索，并基于模型和学生输入继续生成学习计划。
- `XINGCHEN_API_KEY` / `XINGCHEN_BASE_URL` / `XINGCHEN_MODEL`：可选。知识库对话问答工作流专用，OpenAI 兼容接口；配置后优先走星辰平台，留空时自动回落 `OPENAI_*` 配置。
- `KB_QA_MOCK`：可选。对话问答演示模式开关——`true` 强制演示（不调模型，用知识库原文模拟生成讲解，回答会标注"演示模式"）；`false` 强制真实模型；留空自动判断（未配置任何模型 API key 时自动进入演示模式，开箱即可完整体验）。

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

页面分为工作流中心和统一工作台两个主层级。学习规划工作台包含学习概览、知识学习和完整计划三个视图；AI 助教与运行过程通过辅助弹窗打开。知识学习采用推荐路径、分类目录和宽版知识点详情，支持状态标记与按需专题讲解；运行过程展示需求分析、内容拆解、搜索结果、资源评估、练习设计、规则校验和 Reviewer 检查结果。

## 后续扩展

当前项目已经预留以下扩展点：

- `src/edu_agent/tools/course_kb.py`：已实现最小本地课程知识库（Markdown 分块 + 纯 Python 关键词检索），后续可替换为 LlamaIndex/向量检索实现，接口不变。
- `src/edu_agent/tools/student_memory.py`：后续可接入学生错题、练习记录和学习历史。
- `src/edu_agent/workflows/mistake_reflection/`：后续可扩展错题反思工作流。
- `src/edu_agent/workflows/quiz_generation/`：后续可扩展练习生成工作流。
- `src/edu_agent/workflows/learning_report/`：后续可扩展学情分析工作流。

整体原则：共享能力放在 `tools/` 和 `core/`，具体业务流程放在 `workflows/`。每个 workflow 可以独立维护自己的 `workflow.py`、`agents.py`、`schemas.py` 和 `prompts.py`。
