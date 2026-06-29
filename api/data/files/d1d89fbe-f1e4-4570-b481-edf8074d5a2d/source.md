# LoFTR: Detector-Free Local Feature Matching with Transformers

> **论文**：LoFTR: Detector-Free Local Feature Matching with Transformers  
> **作者**：Jiaming Sun, Zehong Shen, Yuang Wang, Hujun Bao, Xiaowei Zhou（浙江大学，商汤研究院）  
> **会议**：CVPR 2021  
> **arXiv**：2104.00680

---

## 1. 核心思想

传统局部特征匹配采用**检测 → 描述 → 匹配**的三阶段流水线（如 SIFT、ORB、SuperPoint）。LoFTR 提出**无检测器**方案：

1. 直接在**粗粒度**（1/8 分辨率）建立**像素级密集匹配**
2. 通过**置信度筛选 + 互最近邻**选出高置信度匹配
3. 用**细粒度模块**将粗匹配**细化到亚像素级**

> **关键洞察**：传统检测器在弱纹理、重复模式、运动模糊区域无法提取可重复的兴趣点。LoFTR 借助 Transformer 的**全局感受野**，即使在这些区域也能找到对应关系。

---

## 2. 网络架构

整体由 **4 个模块**组成：

| 模块                       | 功能                | 输出                                                           |
| ------------------------ | ----------------- | ------------------------------------------------------------ |
| 1. Local Feature CNN     | 提取粗/细两级特征图        | $\tilde{F}^A, \tilde{F}^B$（1/8）; $\hat{F}^A, \hat{F}^B$（1/2） |
| 2. LoFTR Module          | Transformer 处理粗特征 | $\tilde{F}^A_{tr}, \tilde{F}^B_{tr}$（位置/上下文相关的特征）            |
| 3. Matching Module       | 匹配变换后的特征          | 置信度矩阵 $P_c$ → 粗匹配 $M_c$                                      |
| 4. Coarse-to-Fine Module | 亚像素级细化            | 细匹配 $M_f$                                                    |

### 2.1 Local Feature CNN

- **Backbone**：ResNet-18 + FPN
- **粗粒度特征**：$\tilde{F}^A, \tilde{F}^B$，$1/8$ 原始分辨率
- **细粒度特征**：$\hat{F}^A, \hat{F}^B$，$1/2$ 原始分辨率

CNN 的平移等变性和局部性适合提取局部特征，同时下采样降低了后续 Transformer 的输入长度，保证计算可控。

### 2.2 LoFTR Module（核心）

粗特征展平为 1D 序列后，加入 **2D 正弦位置编码**（DETR 风格，但只在 backbone 输出后加一次），然后通过交替的自注意力和交叉注意力层。

#### Self-Attention vs Cross-Attention

| 类型 | Q / K / V 来源 | 作用 |
|---|---|---|
| Self-Attention | 同一图像的特征（$\tilde{F}^A$ 或 $\tilde{F}^B$） | 聚合图像内部全局上下文 |
| Cross-Attention | Q 来自 A，K/V 来自 B（或反之） | 建立两图之间的对应关系 |

交替堆叠 $N_c = 4$ 次，让特征逐步变为"易匹配"的表示。

#### Linear Attention（降复杂度）

标准 Transformer 的**点积注意力**（Dot-Product Attention）计算为：

$$\text{Attention}(Q, K, V) = \text{softmax}(Q K^T) V$$

其复杂度为 $O(N^2 D)$（$N$ 为序列长度，$D$ 为特征维度），因为 $Q K^T$ 产生 $N \times N$ 的相似度矩阵。对于图像像素级密集匹配，$N$ 可达数万，计算不可行。

##### Linear Attention 的核心思想

Linear Attention（Katharopoulos et al., ICML 2020）将 softmax 中的指数核替换为**特征映射（feature map）**的点积：

$$\text{sim}(q_i, k_j) = \phi(q_i)^T \phi(k_j)$$

其中 $\phi: \mathbb{R}^D \to \mathbb{R}^M$ 是一个非线性映射（$M$ 通常 $\approx D$）。LoFTR 中：

$$\phi(x) = \text{elu}(x) + 1$$

##### 从 $O(N^2)$ 降到 $O(N)$ 的推导

标准注意力输出为：

$$o_i = \frac{\sum_{j=1}^N \text{sim}(q_i, k_j) \cdot v_j}{\sum_{j=1}^N \text{sim}(q_i, k_j)}$$

将 $\text{sim}(q_i, k_j) = \phi(q_i)^T \phi(k_j)$ 代入分子：

$$o_i = \frac{\phi(q_i)^T \sum_{j=1}^N \phi(k_j) \cdot v_j}{\phi(q_i)^T \sum_{j=1}^N \phi(k_j)}$$

注意到 $\phi(q_i)^T$ 可以**提到求和号外面**——利用矩阵乘法**结合律**改变计算顺序：

- **先算**：$\sum_{j=1}^N \phi(k_j)^T v_j \in \mathbb{R}^{M \times D_v}$（所有序列只算一次）
- **再算**：每个 $q_i$ 与该累加矩阵相乘

这样避免了显式构造 $N \times N$ 的相似度矩阵，复杂度降为 **$O(N D^2)$**。当 $D \ll N$ 时，这相当于线性复杂度 $O(N)$。

##### 与标准 Attention 的对比

| | Dot-Product Attention | Linear Attention |
|---|---|---|
| 相似度计算 | $\exp(q_i^T k_j)$ | $\phi(q_i)^T \phi(k_j)$ |
| 矩阵 | $N \times N$ | 不显式构造 |
| 复杂度 | $O(N^2 D)$ | $O(N D^2)$ |
| 是否需要 softmax | 是 | 否（特征映射 + 归一化替代） |
| 关注模式 | 可形成稀疏/尖锐的注意力分布 | 更平滑的全局聚合 |

##### 代价

Linear Attention 的代价是**注意力的"稀疏聚焦"能力变弱**：
- 标准 softmax 可以让少数位置的注意力权重接近 1，其余接近 0（形成锐利的关注）
- Linear Attention 由于 $\phi$ 的值域为正，注意力分布更均匀、更平滑
- 对图像匹配任务而言，这种"全局平滑聚合"反而有益——每个像素需要综合全局上下文信息

其中 **ELU（Exponential Linear Unit）**是一种激活函数：

$$\text{elu}(x) = \begin{cases} x & x \geq 0 \\ \alpha(e^x - 1) & x < 0 \end{cases}$$

因此 $\phi(x) = \text{elu}(x) + 1$ 满足：
- $x \geq 0$ 时，$\phi(x) = x + 1$（线性，且 $\phi(x) \geq 1$）
- $x < 0$ 时，$\phi(x) = \alpha e^x + (1-\alpha)$（指数衰减但始终为正）

> **为什么选 ELU + 1？** 作为核函数，要求输出恒为正且保留非线性。ELU+1 满足正定性，且 $x \geq 0$ 区域梯度为 1，避免梯度消失。通常取 $\alpha = 1$。

利用矩阵乘法结合律，先算 $\phi(K)^T V$，复杂度降至 **$O(N)$**。

#### Positional Encoding（位置编码）

LoFTR 使用**标准正弦位置编码的 2D 扩展**（DETR 风格），是 Transformer 架构中的关键设计。

##### 为什么需要位置编码？

Transformer 的自注意力机制本身是**置换不变的**（permutation-invariant）——即打乱输入序列的顺序，注意力输出不会改变（忽略 positional encoding 的话）。这意味着：

- 两个像素即使 RGB 完全相同，只要它们分别位于图像的不同位置，网络也**无法区分**
- 对于弱纹理区域（如白墙、天空），所有像素的 RGB 特征几乎一致，不加位置信息就无法建立有意义的匹配

##### 公式

对特征图上坐标 $(x, y)$ 处的像素，位置编码为：

$$\text{PE}(x, 2i) = \sin\left(\frac{x}{10000^{2i/d}}\right), \quad \text{PE}(x, 2i+1) = \cos\left(\frac{x}{10000^{2i/d}}\right)$$

$$\text{PE}(y, 2i) = \sin\left(\frac{y}{10000^{2i/d}}\right), \quad \text{PE}(y, 2i+1) = \cos\left(\frac{y}{10000^{2i/d}}\right)$$

其中 $d$ 是特征维度，$i \in [0, d/4)$。X 和 Y 各占一半维度，拼接后形成完整的位置编码向量。

##### 使用方式

```
Backbone 输出特征 F̃  (H/8 × W/8 × d)
        ↓
    +  PE(x, y)        ← 只加一次（不同于 DETR 每层都加）
        ↓
  进入 N 层 Transformer
```

**关键设计**：只在 backbone 输出后加**一次**，后续 Transformer 层不再重复加。消融实验（论文 Table 3）表明每层都加反而性能下降（AUC@5° 从 20.06 降至 18.02）。原因可能是：逐层叠加位置信息会使位置信号过度放大，淹没了特征本身的语义信息。

##### 为什么有效：位置签名

正弦位置编码给每个像素赋予一个**全局唯一的三角函数签名**。效果如下：

```
纯白墙面 (RGB均匀)                 加上 PE 后 (PCA 可视化)
┌──────────────────┐              ┌──────────────────┐
│  ░░░░░░░░░░░░░░  │              │ 红 橙 黄 绿 蓝 … │
│  ░░░░░░░░░░░░░░  │     →        │ 紫 靛 青 碧 翠 … │
│  ░░░░░░░░░░░░░░  │              │ 粉 玫 绯 绛 赭 … │
│  无法区分位置      │              │  每个位置有唯一颜色  │
└──────────────────┘              └──────────────────┘
```

> 论文图 4(c) 的 PCA 可视化显示：即使输入是纯白墙面（RGB 均匀），经过 Positional Encoding + Transformer 后的特征 $\tilde{F}^A_{tr}$ 也呈现出**平滑的颜色梯度**——相邻像素颜色相近，远处的像素颜色不同。这是 LoFTR 能在弱纹理区域匹配的**核心机制**。

##### PE 与特征的关系：加法融合的直觉

PE 通过**加法**（而非拼接）注入特征：

$$F' = F + \text{PE}(x, y)$$

这种设计使得：
- 纹理丰富区域：$F$ 的语义特征主导，PE 提供辅助的空间锚定
- 弱纹理区域：$F \approx \text{常数}$，PE 成为唯一区分信号，保证每个位置仍有独特表示
- Transformer 在全局范围内计算注意力时，能利用 PE 中的距离信息（频率不同的 sin/cos 天然编码了相对距离关系）

##### 位置编码的局限性

| 局限 | 说明 |
|------|------|
| **绝对位置依赖** | 编码依赖于 $(x, y)$ 的绝对坐标，对图像平移、裁剪敏感 |
| **无旋转不变性** | sin/cos 编码不蕴含旋转等变性质 |
| **跨图位置不对齐** | 两幅图中对应点的绝对坐标可能相差很大，但 PE 值是相同的（因为只看自图坐标）——这意味着 PE 只能帮助**图内**的空间推理，**图间**匹配完全依赖特征相似度 |

EfficientLoFTR 用 **2D RoPE**（相对位置编码）替代了这种绝对 PE，使得位置信息通过 $\Delta x, \Delta y$ 的相对位移来编码，对几何变换更鲁棒——详见 EfficientLoFTR 笔记的 3.3.3 节步骤 4。

### 2.3 Matching Module（粗匹配）

计算变换后特征的分数矩阵：

$$S(i, j) = \frac{1}{\tau} \langle \tilde{F}^A_{tr}(i), \tilde{F}^B_{tr}(j) \rangle$$

#### Dual-Softmax (DS)

**动机**：图像 A 中的每个点 $i$ 应该唯一匹配到图像 B 中的一个点 $j$，反之亦然。Dual-Softmax 用概率方式编码这种**双向唯一性约束**。

**计算步骤**：

1. **分数矩阵**（余弦相似度 + 温度缩放）：

$$S(i, j) = \frac{1}{\tau} \langle \tilde{F}^A_{tr}(i), \tilde{F}^B_{tr}(j) \rangle$$

其中 $\tau$ 为温度参数（温度越高，分布越平滑）。

2. **行方向 Softmax**（从 A 到 B 的匹配概率）：

$$P_{A \to B}(i, j) = \text{softmax}_j(S(i, \cdot))_j = \frac{\exp S(i, j)}{\sum_k \exp S(i, k)}$$

3. **列方向 Softmax**（从 B 到 A 的匹配概率）：

$$P_{B \to A}(i, j) = \text{softmax}_i(S(\cdot, j))_i = \frac{\exp S(i, j)}{\sum_k \exp S(k, j)}$$

4. **逐元素相乘**（双向一致的置信度）：

$$P_c(i, j) = P_{A \to B}(i, j) \cdot P_{B \to A}(i, j)$$

**为什么这样做有效？**

- $P_{A \to B}(i, j)$ 高 $\Rightarrow$ 对 A 中的 $i$ 而言，$j$ 是 B 中最匹配的
- $P_{B \to A}(i, j)$ 高 $\Rightarrow$ 对 B 中的 $j$ 而言，$i$ 是 A 中最匹配的
- 两者同时高 $\Rightarrow$ $(i, j)$ 是**互相最近邻**（Mutual Nearest Neighbor），置信度可信
- 任一方向低 $\Rightarrow$ 可能是歧义匹配或异常值，置信度被压低

**与 Softmax + 阈值的关系**：

Dual-Softmax 等价于 MNN（Mutual Nearest Neighbor）准则的**软概率版本**：

| 准则 | 硬决策 | 软决策（DS） |
|---|---|---|
| $i \to j$ 最近邻 | $\arg\max_j S(i, j) = j$ | $P_{A \to B}(i, j)$ 高 |
| $j \to i$ 最近邻 | $\arg\max_i S(i, j) = i$ | $P_{B \to A}(i, j)$ 高 |
| MNN | 两者同时满足 | $P_c(i, j)$ 高 |

#### Optimal Transport (OT)

将特征匹配建模为**最优传输问题**（Optimal Transport），最早由 SuperGlue 引入局部特征匹配领域。

##### 1. 基本设定

把图像 A 的 $N$ 个特征点和图像 B 的 $M$ 个特征点看作两个离散概率分布的支撑集：

- **源分布**：A 中的 $N$ 个点，质量为 $\mathbf{a} \in \mathbb{R}^N$
- **目标分布**：B 中的 $M$ 个点，质量为 $\mathbf{b} \in \mathbb{R}^M$

**代价矩阵**：$C(i, j) = -S(i, j)$ —— 分数越高，传输"代价"越低。

**目标**：寻找一个传输计划 $P \in \mathbb{R}^{N \times M}$（每个元素 $P(i,j)$ 表示从 A 的 $i$ 传输多少"质量"到 B 的 $j$），使得总代价最小：

$$\min_P \langle C, P \rangle = \min_P \sum_{i,j} C(i,j) P(i,j)$$

约束条件：
$$P \mathbf{1}_M = \mathbf{a}, \quad P^T \mathbf{1}_N = \mathbf{b}, \quad P \geq 0$$

##### 2. 部分最优传输（Partial OT）

现实中**并非所有点都能匹配**（遮挡、重复纹理、异常值等）。因此引入"垃圾桶"（dustbin）机制（来自 SuperGlue）：

- 每个 A 中的点可以**不匹配**（匹配到 dustbin）
- 每个 B 中的点可以**不被匹配**

这转化为**部分最优传输**：行和/列和 $\leq 1$，而不是恰好等于 1。等价于在代价矩阵的右下角加入一个 dustbin 维度。

##### 3. 熵正则化（Entropic Regularization）

原始 OT 是线性规划问题，最坏复杂度 $O(N^3)$。为了可扩展，引入**熵正则化**：

$$\min_P \langle C, P \rangle - \lambda H(P)$$

其中熵项 $H(P) = -\sum_{i,j} P(i,j) \log P(i,j)$，$\lambda > 0$ 为正则化系数。

**作用**：
- 使目标函数变为**严格凸优化**，有唯一全局最优解
- 熵项鼓励"平滑"的传输计划（非 0 即 1 的硬分配被软化）
- 可以用 Sinkhorn 迭代在 $O(N^2)$ 时间内高效求解

##### 4. Sinkhorn 算法（核心迭代）

熵正则化 OT 的解具有如下形式（由 KKT 条件导出）：

$$P(i, j) = \text{diag}(\mathbf{u}) \cdot K \cdot \text{diag}(\mathbf{v})$$

其中：
- $K(i, j) = \exp(-C(i, j) / \lambda)$ —— **Gibbs 核矩阵**
- $\mathbf{u} \in \mathbb{R}^N, \mathbf{v} \in \mathbb{R}^M$ —— 待求的行/列缩放向量

Sinkhorn 通过交替缩放行和列来求解 $\mathbf{u}, \mathbf{v}$：

**初始化**：$K(i, j) = \exp(S(i, j) / \lambda)$（注意 $C = -S$，所以 $-C/\lambda = S/\lambda$）

**每次迭代**：
1. **行归一化**：$\mathbf{u} = \mathbf{a} \oslash (K \mathbf{v})$（$\oslash$ 表示逐元素除法）
2. **列归一化**：$\mathbf{v} = \mathbf{b} \oslash (K^T \mathbf{u})$

**最终输出**：$P = \text{diag}(\mathbf{u}) \, K \, \text{diag}(\mathbf{v})$

##### 5. 从 Sinkhorn 输出到匹配置信度

Sinkhorn 得到的 $P(i,j)$ 具有以下性质：

- $P(i, j) \geq 0$，且行/列和满足约束
- $P(i, j)$ 越大 $\Rightarrow$ $(i, j)$ 之间的匹配代价越低 $\Rightarrow$ 特征越相似
- 可以直接将 $P(i, j)$ 作为匹配置信度

##### 6. LoFTR 中的具体实现

| 参数 | 值 | 说明 |
|---|---|---|
| Sinkhorn 迭代次数 | **3** | 少量迭代即可收敛到近似解 |
| 正则化系数 $\lambda$ | 与温度 $\tau$ 相关 | 控制熵正则化的强度 |
| 质量向量 $\mathbf{a}, \mathbf{b}$ | 均匀分布 + dustbin | 每个点的初始匹配概率相等 |
| 推理速度 | 130 ms | 比 DS 的 116 ms 稍慢 |

**为什么 3 次迭代就够了？**

Sinkhorn 在熵正则化下收敛是**指数级**的。对于特征匹配这种"大部分点只有少数几个潜在匹配"的稀疏场景，3-5 次迭代通常就能达到足够精度。

##### 7. OT vs Dual-Softmax 的本质区别

| 维度 | Dual-Softmax | Optimal Transport |
|---|---|---|
| **数学本质** | 两次独立的 softmax + 逐元素乘积 | 带约束的凸优化问题 |
| **约束** | 软约束（概率乘积自然衰减） | 硬约束（Sinkhorn 强制行/列和） |
| **全局性** | 局部（每个 $(i,j)$ 独立计算） | 全局（行归一化影响所有列，反之亦然） |
| **匹配唯一性** | 软保证 | 硬保证（通过 dustbin） |
| **计算** | 两次 softmax，$O(N^2)$ | Sinkhorn 迭代，$O(k N^2)$（$k=3$） |
| **收敛性** | 无迭代，一次性计算 | Sinkhorn 快速收敛 |

**直观理解**：

- DS 像"每个人都选自己最喜欢的对象"，然后看是否双向喜欢
- OT 像"计划经济"，通过全局优化找到一个总代价最小的匹配方案，确保没有两个 A 的点同时"抢"同一个 B 的点（除非 B 的容量允许）

**为什么 OT 在某些场景更优？**

在存在大量**歧义匹配**的场景（如重复纹理、对称结构），OT 的全局约束能更好地处理冲突：如果 A 中有两个点都高度相似于 B 中的同一个点，OT 会强制其中一个匹配到 dustbin（不匹配），而 DS 可能给两个匹配都分配中等置信度，导致误匹配。

#### 匹配筛选

两种方法最终都通过以下步骤筛选粗匹配：

1. **置信度阈值**：$P_c(i, j) \geq \theta_c = 0.2$
2. **互最近邻（MNN）**：进一步过滤可能的异常值

### 2.4 Coarse-to-Fine Module（细匹配）

对每对粗匹配 $(\tilde{i}, \tilde{j}) \in M_c$：

1. 在细粒度特征图 $\hat{F}^A, \hat{F}^B$ 上定位到 $(\hat{i}, \hat{j})$
2. 裁剪 $w \times w$ 局部窗口（$w = 5$）
3. 小 LoFTR 模块（$N_f = 1$）变换窗口内特征
4. 计算中心向量 $\hat{F}^A_{tr}(\hat{i})$ 与 $\hat{F}^B_{tr}(\hat{j})$ 窗口内所有向量的相关性，得到 heatmap
5. 对概率分布求**期望**，得到亚像素级位置 $\hat{j}'$

---

## 3. 训练

### 数据集

| 场景 | 数据集 | 说明 |
|---|---|---|
| 室内 | ScanNet | 1613 序列，640×480，训练 230M 对 |
| 室外 | MegaDepth | 互联网照片，长边 840/1200 |

### 损失函数

$$\mathcal{L} = \mathcal{L}_c + \mathcal{L}_f$$

**粗粒度损失**（负对数似然）：
- 用相机位姿和深度图计算 1/8 分辨率网格的真值匹配 $M_c^{gt}$
- 最小化真值匹配上的负对数似然

**细粒度损失**（加权 L2）：

$$\mathcal{L}_f = \frac{1}{|M_f|} \sum_{(\hat{i}, \hat{j}') \in M_f} \frac{1}{\sigma^2(\hat{i})} \|\hat{j}' - \hat{j}'_{gt}\|_2$$

- 用真值位姿和深度 warp 计算参考位置 $\hat{j}'_{gt}$
- $\sigma^2(\hat{i})$ 是 heatmap 总方差（不确定性），作为权重——**低不确定性匹配损失权重更高**

### 训练设置

- 优化器：Adam，初始 lr = $1 \times 10^{-3}$
- Batch size：64
- 硬件：64 × GTX 1080Ti，收敛约 24 小时
- 模型端到端训练，随机初始化

### 推理速度

| 配置 | 时间（640×480 图像对） |
|---|---|
| Dual-Softmax | 116 ms（RTX 2080Ti） |
| Optimal Transport（3次 Sinkhorn） | 130 ms |

---

## 4. 实验结果

### 4.1 HPatches 单应性估计

| 方法 | AUC@3px | AUC@5px | AUC@10px |
|---|---|---|---|
| SP + SuperGlue | 53.9 | 68.3 | 81.7 |
| DRC-Net | 50.6 | 56.2 | 68.3 |
| **LoFTR-DS** | **65.9** | **75.6** | **84.6** |

LoFTR 在所有阈值下大幅领先，且阈值越严格优势越大。

### 4.2 相对位姿估计

**ScanNet（室内）：**

| 方法 | AUC@5° | AUC@10° | AUC@20° |
|---|---|---|---|
| SP + SuperGlue | 16.16 | 33.81 | 51.84 |
| DRC-Net | 7.69 | 17.93 | 30.49 |
| **LoFTR-DS** | **22.06** | **40.8** | **57.62** |

**MegaDepth（室外）：**

| 方法 | AUC@5° | AUC@10° | AUC@20° |
|---|---|---|---|
| SP + SuperGlue | 42.18 | 61.16 | 75.96 |
| DRC-Net | 27.01 | 42.96 | 58.31 |
| **LoFTR-DS** | **52.8** | **69.19** | **81.18** |

室内场景优势尤其明显——正是弱纹理区域多的场景。

### 4.3 Visual Localization

| 基准 | LoFTR 表现 |
|---|---|
| Aachen Day-Night v1.1 | 本地特征赛道第一；手持设备赛道夜间与 SuperGlue 持平 |
| InLoc | **所有已发表方法中排名第一** |

### 4.4 消融实验

| 变体 | AUC@5° | AUC@10° | 说明 |
|---|---|---|---|
| 1) Transformer → 卷积 | 14.98 | 32.04 | 性能显著下降，验证 Transformer 必要性 |
| 2) 1/16 + 1/4 分辨率 | 16.75 | 34.82 | 速度略快(104ms)，精度下降 |
| 3) 每层都加位置编码 | 18.02 | 35.64 | DETR风格，性能反而下降 |
| 4) 更大模型 (Nc=8,Nf=2) | 20.87 | 40.23 | 几乎无提升，当前容量已足够 |
| **Full (Nc=4,Nf=1)** | **20.06** | **40.8** | 最佳配置 |

---

## 5. 关键洞察与总结

### 5.1 LoFTR vs SuperGlue

| | SuperGlue | LoFTR |
|---|---|---|
| 检测器依赖 | **依赖**（需要 SuperPoint 兴趣点） | **无检测器** |
| 注意力范围 | 仅限检测到的稀疏兴趣点 | **全图密集像素** |
| 弱纹理区域 | 无法匹配（没有兴趣点） | **可以匹配** |
| 感受野 | GNN 消息传递（局部） | Transformer **全局** |

### 5.2 核心优势

1. **全局感受野**：Linear Transformer 让每个像素能关注全图任意位置
2. **位置相关特征**：Positional Encoding 使弱纹理区域的每个像素有唯一表示
3. **粗到细**：先全局密集匹配定位大致区域，再局部细化到亚像素
4. **计算高效**：Linear Attention 将 $O(N^2)$ 降到 $O(N)$

### 5.3 局限

- 需要稠密计算，对大分辨率图像仍有挑战
- 依赖深度图和位姿进行监督训练（ScanNet/MegaDepth）
- 相比检测器方法输出匹配数量更多，后续 RANSAC 开销稍大

---

## 6. 与后续工作的关系

- **EfficientLoFTR**：后续工作，进一步优化效率和精度
- **COTR、GMFlow** 等：沿 Transformer + dense matching 方向继续发展
- 与光流估计（optical flow）的界限日益模糊

---

**代码**：https://zju3dv.github.io/loftr/
