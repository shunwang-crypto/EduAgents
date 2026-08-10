# GPT-2 与 Transformer 深度解析

> 本文系统讲解 GPT-2 所用到的 Transformer 架构，重点覆盖多头注意力机制、Q/K/V 向量、自注意力、位置编码、层归一化、BPE 分词等概念，适合从零理解 GPT-2 的实现方式。

## 第 1 章 引言：GPT-2 与 Transformer 的关系

GPT-2（Generative Pre-trained Transformer 2）是 OpenAI 于 2019 年发布的**自回归语言模型**。它的核心架构来自 2017 年的论文《Attention Is All You Need》提出的 Transformer，并且只使用了其中的 **Decoder（解码器）部分**，因此 GPT-2 也被称为 **Decoder-only** 架构。

与 BERT 等编码器模型不同，GPT-2 只能从左到右单向生成文本：每生成一个 token，它只能看到之前的所有 token（使用掩码自注意力实现），因此天然适合文本生成任务。

理解 GPT-2 的关键在于理解 Transformer 的四个核心组件：

1. **多头注意力（Multi-Head Attention）**：模型的核心，负责捕捉 token 之间的依赖关系；
2. **位置编码（Positional Encoding）**：给每个 token 标记位置信息；
3. **层归一化（LayerNorm）与残差连接**：稳定训练，让深层网络可以收敛；
4. **前馈网络（FFN）**：对每个位置独立做非线性变换。

## 第 2 章 Transformer 总体架构

标准的 Transformer 由两部分组成：**编码器（Encoder）** 和 **解码器（Decoder）**。

编码器用于理解输入（如 BERT），解码器用于生成输出（如 GPT 系列）。每个编码器/解码器层内部都包含：

- 一个**多头注意力子层**；
- 一个**前馈网络子层**；
- 每个子层外面都包裹**残差连接 + 层归一化**。

GPT-2 只保留了解码器部分，并且在注意力中使用**因果掩码（Causal Mask）**，保证每个位置只能看到当前位置及之前的位置，不能"偷看"未来。

## 第 3 章 多头注意力机制（核心）

### 3.1 自注意力（Self-Attention）

自注意力让序列中的**每个 token 都能关注序列中的其他所有 token**，并根据相关程度加权聚合信息。

给定输入序列，每个 token 的位置都会计算一个输出向量，该向量是其他所有位置值的加权求和，权重由 token 之间的"相关程度"决定。

### 3.2 Q、K、V 三个向量

自注意力的核心是三个向量：**查询（Query）、键（Key）、值（Value）**。

- **Q（Query，查询）**：当前 token 想要"找什么"；
- **K（Key，键）**：每个 token 的"身份标签"，用于被匹配；
- **V（Value，值）**：每个 token 携带的"实际信息内容"。

计算时，用当前 token 的 Q 与所有 token 的 K 做点积，得到注意力分数（谁跟谁相关）；分数经 Softmax 归一化成权重，再对 V 做加权求和，得到输出。

### 3.3 缩放点积注意力公式

自注意力的计算可写成：

```
Attention(Q, K, V) = softmax(Q · K^T / sqrt(d_k)) · V
```

其中：

- Q、K、V 由输入乘三个可学习的权重矩阵 W_Q、W_K、W_V 得到；
- `Q · K^T` 计算所有位置对之间的点积相似度；
- `除以 sqrt(d_k)`（d_k 是键的维度）是为了防止点积过大导致 Softmax 梯度消失，称为**缩放（Scale）**；
- Softmax 把分数变成概率分布；
- 最后与 V 加权求和。

### 3.4 为什么需要"多头"注意力

单个注意力头只能学习**一种**依赖模式。但自然语言中的依赖关系是多种多样的：有的词需要关注句法主语，有的需要关注指代对象，有的需要关注远处的修饰成分。

**多头注意力（Multi-Head Attention）**把 Q、K、V 分别拆成 h 个头（例如 GPT-2 使用 12 个头），每个头在**不同的子空间**中独立做注意力，最后把各头的结果拼接起来再线性投影。

这样做的好处：

1. **每个头可以学到不同类型的依赖关系**——有的头关注局部相邻词，有的头关注远程指代；
2. **表达能力更强**——不同子空间捕捉不同特征，综合起来更全面；
3. 是 Transformer 相对 RNN/LSTM 的关键优势之一，能并行计算所有位置。

### 3.5 多头注意力的实现方式（代码级）

多头注意力在实现上通常按以下步骤：

1. **线性投影**：输入 X 分别乘 W_Q、W_K、W_V，得到 Q、K、V；
2. **拆头（Reshape）**：把 Q、K、V 的最后一维按头数拆开，例如形状从 `(batch, seq_len, d_model)` 变成 `(batch, num_heads, seq_len, head_dim)`，每个头独立计算；
3. **缩放点积注意力**：对每个头并行执行 `softmax(Q·K^T/sqrt(d_k))·V`；
4. **拼接（Concat）**：把所有头的输出拼接回 `(batch, seq_len, d_model)`；
5. **输出投影**：乘 W_O 做一次线性变换得到最终输出。

以 PyTorch 为例，核心代码片段：

```python
import torch
import torch.nn as nn

class MultiHeadAttention(nn.Module):
    def __init__(self, d_model, num_heads):
        super().__init__()
        assert d_model % num_heads == 0
        self.d_model = d_model
        self.num_heads = num_heads
        self.head_dim = d_model // num_heads

        self.wq = nn.Linear(d_model, d_model)
        self.wk = nn.Linear(d_model, d_model)
        self.wv = nn.Linear(d_model, d_model)
        self.wo = nn.Linear(d_model, d_model)

    def forward(self, x, mask=None):
        batch, seq_len, _ = x.shape
        # 1. 线性投影
        q = self.wq(x)
        k = self.wk(x)
        v = self.wv(x)
        # 2. 拆头：变成 (batch, num_heads, seq_len, head_dim)
        q = q.view(batch, seq_len, self.num_heads, self.head_dim).transpose(1, 2)
        k = k.view(batch, seq_len, self.num_heads, self.head_dim).transpose(1, 2)
        v = v.view(batch, seq_len, self.num_heads, self.head_dim).transpose(1, 2)
        # 3. 缩放点积注意力
        scores = q @ k.transpose(-2, -1) / (self.head_dim ** 0.5)
        if mask is not None:
            scores = scores.masked_fill(mask == 0, float("-inf"))
        attn = torch.softmax(scores, dim=-1)
        out = attn @ v
        # 4. 拼接：还原成 (batch, seq_len, d_model)
        out = out.transpose(1, 2).contiguous().view(batch, seq_len, self.d_model)
        # 5. 输出投影
        return self.wo(out)
```

GPT-2 中的实现与上述一致，关键差异是**因果掩码**：mask 为下三角矩阵，保证位置 i 只能 attend 到位置 <= i 的 token。

## 第 4 章 GPT-2 中的 Transformer 细节

### 4.1 Decoder-only 与因果掩码

GPT-2 只使用解码器，并使用**因果掩码（Causal Mask）**：在计算注意力分数时，把未来位置的分数设为负无穷，Softmax 后权重为 0，保证生成时不会泄漏未来信息。这是 GPT-2 与 BERT 最核心的区别之一。

### 4.2 位置编码（Positional Embedding）

注意力机制本身**不包含任何位置信息**——如果把 token 顺序打乱，自注意力的计算结果不变。因此必须显式加入位置信息。

GPT-2 使用**可学习的绝对位置编码**：为每个位置维护一个可训练向量，加到 token 的嵌入向量上。与原始 Transformer 使用的正弦/余弦固定编码不同，GPT-2 的位置编码是训练出来的。

### 4.3 层归一化与残差连接

GPT-2 在**每个注意力/前馈子层之前**先做 LayerNorm（Pre-Norm），再进入子层，最后加残差连接。这种 Pre-Norm + 残差的设计：

- 让梯度在深层网络中更容易传播，避免梯度消失；
- 层归一化对每个 token 的特征维度做归一化，稳定训练；
- GPT-2 在最终输出前还会再做一次 LayerNorm。

### 4.4 前馈网络（FFN）

每个 Transformer 层包含一个**逐位置的前馈网络**：对序列中每个位置独立执行两次线性变换，中间夹一个 GELU 激活函数：

```
FFN(x) = Linear2(GELU(Linear1(x)))
```

其中 Linear1 把维度从 d_model 放大到 4 倍（如 768 -> 3072），Linear2 再缩回。

## 第 5 章 训练与推理

### 5.1 BPE 分词

GPT-2 使用 **BPE（Byte Pair Encoding）** 分词：先把文本切到字节/字符级别，然后反复合并**出现频率最高**的相邻字符对，生成一个子词词表。这样：

- 罕见词可以被拆成常见子词，避免 OOV（未登录词）问题；
- 词表大小可控（GPT-2 约 50257 个 token）；
- 任何文本都能被编码，包括没见过的词。

### 5.2 自回归生成

GPT-2 生成文本是**自回归**的：输入前 n 个 token，预测第 n+1 个 token 的概率分布；把预测出的 token 拼到末尾，再继续预测下一个，循环往复。

### 5.3 损失函数与预训练

GPT-2 的预训练目标是**语言建模**：最大化给定前文、预测下一个 token 的对数似然，损失函数为交叉熵损失。预训练数据来自大规模网页文本（WebText）。预训练完成后，GPT-2 可以通过**零样本（zero-shot）**或少量提示（prompt）直接完成下游任务，无需任务特定的微调数据。

## 第 6 章 常见问题解答（FAQ）

**问：多头注意力和单头注意力的区别？**

单头注意力只能捕捉一种依赖模式；多头把注意力拆到多个子空间并行计算，每个头可学习不同的依赖关系，最后拼接融合，表达能力更强。

**问：为什么 GPT-2 没有编码器？**

GPT-2 是生成模型，只需从左到右生成，Decoder 的因果掩码正好满足单向依赖；不需要像 BERT 那样双向理解上下文，所以省略了编码器。

**问：什么是因果掩码（Causal Mask）？**

一个下三角矩阵，保证注意力只能关注当前位置及之前的位置，防止生成时"偷看"未来 token。

**问：上下文窗口是什么？**

GPT-2 能处理的最大 token 数（如 1024）。因为位置编码是有限的，超过窗口的文本无法处理，这也是大模型的关键限制之一。

**问：注意力分数为什么要除以 sqrt(d_k)？**

d_k 较大时点积数值会偏大，Softmax 会进入饱和区导致梯度极小；除以 sqrt(d_k) 让分数尺度稳定，训练更顺利。

**问：多头注意力的参数量如何计算？**

每个头有独立的 W_Q、W_K、W_V（每个形状 d_model × head_dim），所有头共享 W_O（d_model × d_model）。多头相比单头的总参数量基本不变，只是权重被拆分使用。
