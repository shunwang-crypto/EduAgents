"""练习题模块：自适应学习闭环的"练习"执行器。

自适应出题机制（核心）：
- **p 值即难度控制器**：p < 0.4 出基础题，0.4-0.7 出标准题，> 0.7 出进阶题；
- 答题后 ``update_mastery`` 改变 p → 下一题难度**自动升降**，无需额外难度状态：
    答对 → p 升 → 下一题更难；答错 → p 降 → 下一题更简单；
- 知识点选择：弱项（p 低）优先；
- 判题是确定性规则比对，LLM 不参与。

用法（前端接线示例）：
    quiz = generate_quiz(mastery, learning_sequence, k=3)
    for item in quiz:
        correct = (user_answer == item["answer"])
        update_mastery(mastery, item["node_id"], correct)
"""

from __future__ import annotations

from typing import Dict, List, Optional

from edu_agent.core.mastery import get_p, update_mastery

BASIC = "basic"
STANDARD = "standard"
ADVANCED = "advanced"
_LEVEL_ORDER = (BASIC, STANDARD, ADVANCED)


def _level_for_p(p: float) -> str:
    """按掌握度 p 选难度档：低 p 基础题，高 p 进阶题。"""
    if p < 0.4:
        return BASIC
    if p < 0.7:
        return STANDARD
    return ADVANCED


# 预设题库：每个知识点 3 档难度（keywords 匹配节点标题，level 决定难度）。
QUESTIONS: List[dict] = [
    # Transformer 整体
    {
        "keywords": ["transformer", "注意力机制", "attention"],
        "level": BASIC,
        "question": "Transformer 的核心机制是？",
        "options": ["自注意力机制", "卷积运算", "循环传递"],
        "answer": 0,
    },
    {
        "keywords": ["transformer", "attention"],
        "level": STANDARD,
        "question": "Transformer 相比 RNN 的主要优势是？",
        "options": ["可并行计算且能捕捉长距离依赖", "参数更少", "不需要训练数据"],
        "answer": 0,
    },
    {
        "keywords": ["transformer", "attention"],
        "level": ADVANCED,
        "question": "标准自注意力的时间复杂度是？",
        "options": ["O(n²d)", "O(nd)", "O(n)"],
        "answer": 0,
    },
    # 自注意力（Q/K/V 等）
    {
        "keywords": ["自注意力", "self-attention", "self attention", "qkv", "q、k、v"],
        "level": BASIC,
        "question": "自注意力中 Q、K、V 分别代表？",
        "options": ["查询、键、值", "值、查询、键", "键、值、查询"],
        "answer": 0,
    },
    {
        "keywords": ["自注意力", "self-attention", "self attention"],
        "level": STANDARD,
        "question": "自注意力让每个词关注什么？",
        "options": ["序列中所有其他词", "仅前一个词", "仅相邻词"],
        "answer": 0,
    },
    {
        "keywords": ["自注意力", "self-attention", "self attention"],
        "level": ADVANCED,
        "question": "缩放点积注意力为什么要除以 √d_k？",
        "options": ["防止点积过大导致梯度消失", "增加计算量", "让矩阵可逆"],
        "answer": 0,
    },
    # 多头注意力
    {
        "keywords": ["多头注意力", "multi-head", "multihead", "多头"],
        "level": BASIC,
        "question": "多头注意力的“头”是什么？",
        "options": ["多组独立的 Q/K/V 投影", "多个注意力层堆叠", "多个词向量"],
        "answer": 0,
    },
    {
        "keywords": ["多头注意力", "multi-head", "multihead", "多头"],
        "level": STANDARD,
        "question": "多头注意力的输出如何合并？",
        "options": ["拼接后线性投影", "直接相加", "取平均"],
        "answer": 0,
    },
    {
        "keywords": ["多头注意力", "multi-head", "multihead", "多头"],
        "level": ADVANCED,
        "question": "多头注意力的主要好处是？",
        "options": ["让模型关注不同子空间的信息", "降低计算量", "减少参数量"],
        "answer": 0,
    },
    # 位置编码
    {
        "keywords": ["位置编码", "positional", "位置信息", "位置嵌入"],
        "level": BASIC,
        "question": "Transformer 为什么要加位置编码？",
        "options": ["自注意力本身不分词序", "为了加速收敛", "为了减少参数"],
        "answer": 0,
    },
    {
        "keywords": ["位置编码", "positional", "位置嵌入"],
        "level": STANDARD,
        "question": "Transformer 常用的位置编码形式是？",
        "options": ["正弦/余弦函数", "随机初始化", "常数"],
        "answer": 0,
    },
    {
        "keywords": ["位置编码", "positional", "位置嵌入"],
        "level": ADVANCED,
        "question": "正弦位置编码的优点之一是？",
        "options": ["可外推到比训练更长的序列", "完全消除参数", "不需要 embedding 层"],
        "answer": 0,
    },
    # BPE 分词
    {
        "keywords": ["bpe", "分词", "token", "词元"],
        "level": BASIC,
        "question": "BPE 分词的核心思想是？",
        "options": ["按出现频率合并子词", "按空格简单切分", "按随机位置切分"],
        "answer": 0,
    },
    {
        "keywords": ["bpe", "分词", "token", "词元"],
        "level": STANDARD,
        "question": "BPE 的词表如何构建？",
        "options": ["反复合并最频繁的相邻字符对", "按字典顺序排列字符", "随机挑选字符组合"],
        "answer": 0,
    },
    {
        "keywords": ["bpe", "分词", "token", "词元"],
        "level": ADVANCED,
        "question": "BPE 相比整词切分的主要优势是？",
        "options": ["平衡词表大小与罕见词覆盖", "分词速度更快", "无需训练语料"],
        "answer": 0,
    },
    # 递归
    {
        "keywords": ["递归", "recursion", "调用栈"],
        "level": BASIC,
        "question": "递归函数必须包含什么才能保证终止？",
        "options": ["终止条件（基线情形）", "全局变量", "循环语句"],
        "answer": 0,
    },
    {
        "keywords": ["递归", "recursion", "调用栈"],
        "level": STANDARD,
        "question": "递归调用使用的是哪种数据结构？",
        "options": ["调用栈", "队列", "哈希表"],
        "answer": 0,
    },
    {
        "keywords": ["递归", "recursion", "调用栈"],
        "level": ADVANCED,
        "question": "递归深度过大时可能发生什么？",
        "options": ["栈溢出", "内存泄漏", "死锁"],
        "answer": 0,
    },
    # 二叉树遍历
    {
        "keywords": ["二叉树", "binary tree", "tree", "遍历"],
        "level": BASIC,
        "question": "二叉树前序遍历的访问顺序是？",
        "options": ["根 → 左 → 右", "左 → 根 → 右", "左 → 右 → 根"],
        "answer": 0,
    },
    {
        "keywords": ["二叉树", "binary tree", "tree", "遍历"],
        "level": STANDARD,
        "question": "二叉树中序遍历的访问顺序是？",
        "options": ["左 → 根 → 右", "根 → 左 → 右", "左 → 右 → 根"],
        "answer": 0,
    },
    {
        "keywords": ["二叉树", "binary tree", "tree", "遍历"],
        "level": ADVANCED,
        "question": "前序遍历常用于什么场景？",
        "options": ["复制整棵树", "对二叉树排序", "统计叶子深度"],
        "answer": 0,
    },
    # 反向传播 / 训练
    {
        "keywords": ["反向传播", "backprop", "梯度", "梯度下降"],
        "level": BASIC,
        "question": "反向传播用来计算什么？",
        "options": ["损失对各参数的梯度", "激活函数的输出", "训练集的顺序"],
        "answer": 0,
    },
    {
        "keywords": ["反向传播", "backprop", "梯度", "梯度下降"],
        "level": STANDARD,
        "question": "反向传播的数学基础是？",
        "options": ["链式法则", "贝叶斯定理", "泰勒展开"],
        "answer": 0,
    },
    {
        "keywords": ["反向传播", "backprop", "梯度", "梯度下降"],
        "level": ADVANCED,
        "question": "梯度消失问题在深层网络中的表现是？",
        "options": ["浅层梯度接近 0，参数难更新", "梯度为无穷大", "损失函数不变"],
        "answer": 0,
    },
]


def _node_questions(node_title: str) -> List[dict]:
    title = (node_title or "").lower()
    return [item for item in QUESTIONS if any(kw.lower() in title for kw in item["keywords"])]


def find_question(node_title: str) -> Optional[dict]:
    """按节点标题关键词返回第一道匹配题（无匹配返回 None）。"""
    questions = _node_questions(node_title)
    return questions[0] if questions else None


def pick_question(mastery: Dict[str, dict], node_id: str) -> Optional[dict]:
    """按节点当前 p 值选难度档的题（自适应核心：p 变则档位变）。

    优先选目标档位；若该档无题，向邻近档回退。
    """
    candidates = _node_questions(node_id)
    if not candidates:
        return None
    target = _level_for_p(get_p(mastery, node_id))
    for level in _LEVEL_ORDER[_LEVEL_ORDER.index(target):] + _LEVEL_ORDER[:_LEVEL_ORDER.index(target)]:
        for item in candidates:
            if item["level"] == level:
                return item
    return candidates[0]


def generate_quiz(
    mastery: Dict[str, dict],
    learning_sequence: List[str],
    k: int = 3,
) -> List[dict]:
    """按掌握度从低到高选 k 个「有题库匹配」的节点，每节点按 p 选难度档出题。"""
    scored = []
    for node_id in learning_sequence:
        question = pick_question(mastery, node_id)
        if question is None:
            continue
        scored.append((get_p(mastery, node_id), node_id, question))
    scored.sort(key=lambda item: item[0])  # p 低（弱项）在前

    quiz = []
    for _, node_id, question in scored[:k]:
        quiz.append(
            {
                "node_id": node_id,
                "level": question["level"],
                "question": question["question"],
                "options": question["options"],
                "answer": question["answer"],
            }
        )
    return quiz


def answer_quiz(
    mastery: Dict[str, dict],
    node_id: str,
    question: dict,
    answer_index: int,
) -> tuple[Dict[str, dict], bool]:
    """判题（确定性比对）+ 更新掌握度，返回 (新状态, 是否答对)。"""
    correct = bool(question.get("answer") == answer_index)
    return update_mastery(mastery, node_id, correct), correct


def generate_round(
    mastery: Dict[str, dict],
    learning_sequence: List[str],
    num_questions: int = 5,
) -> List[dict]:
    """生成一轮题（一次一组）：弱项优先选知识点，每个知识点尽量出一题。

    - 知识点按 p 升序（弱项优先），凑够 num_questions；
    - 每个节点优先出「目标档位且本轮未用过」的题，目标档用尽则向邻近档回退；
    - 同一位题在一轮中只出现一次（避免多个 Transformer 相关节点关键词重叠
      导致同一道题被选中多次）；
    - 轮次内的题在作答前定死（不因中途 p 变化而换题）。
    """
    scored = []
    for node_id in learning_sequence:
        candidates = _node_questions(node_id)
        if not candidates:
            continue
        scored.append((get_p(mastery, node_id), node_id, candidates))
    scored.sort(key=lambda item: item[0])  # p 低（弱项）在前

    quiz = []
    used_questions = set()
    for _, node_id, candidates in scored:
        if len(quiz) >= num_questions:
            break
        target = _level_for_p(get_p(mastery, node_id))
        picked = None
        for level in _LEVEL_ORDER[_LEVEL_ORDER.index(target):] + _LEVEL_ORDER[:_LEVEL_ORDER.index(target)]:
            for item in candidates:
                if item["level"] == level and item["question"] not in used_questions:
                    picked = item
                    break
            if picked is not None:
                break
        if picked is None:
            continue  # 该节点候选全被本轮用尽，跳过（极少见）
        used_questions.add(picked["question"])
        quiz.append(
            {
                "node_id": node_id,
                "level": picked["level"],
                "question": picked["question"],
                "options": picked["options"],
                "answer": picked["answer"],
            }
        )
    return quiz


def answer_round(
    mastery: Dict[str, dict],
    quiz: List[dict],
    answers: List[int],
) -> tuple[Dict[str, dict], List[dict]]:
    """批量作答一轮题：answers 顺序对应 quiz，每题独立判题并更新掌握度。

    返回 (更新后的 mastery, 带 correct 的每题结果)。
    """
    results = []
    for item, answer_index in zip(quiz, answers):
        update_mastery(mastery, item["node_id"], item["answer"] == answer_index)
        results.append({**item, "correct": item["answer"] == answer_index})
    return mastery, results
