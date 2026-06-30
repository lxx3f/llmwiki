

为什么要冻结batchnorm？
DETR 使用很小的 batch size（比如 2 张图/GPU），训练 BN 统计量不稳定。用 ImageNet 预训练的 BN 统计量冻结住，只保留 affine 变换。
```python
self.register_buffer("weight", torch.ones(n))
self.register_buffer("bias", torch.zeros(n))
self.register_buffer("running_mean", torch.zeros(n))
self.register_buffer("running_var", torch.ones(n))
```
从代码来看，BN的参数都冻结了，只做一个固定参数的仿射变换。


NestedTensor是什么？
把"一组尺寸不同的图像"嵌套（Nest）打包成一个统一的 batch tensor，`[B,C,W,H]`，取这组图像的最大宽高作为W和H。NestedTensor内部包含一个tensor和一个mask，把图像保存在tensor左上角，多于部分用0填充，mask用于标志哪些部分像素是填充的，不参与实际计算。

支持哪些backbone?

| backbone 参数值                 | hubconf 名称           | 说明          |
| ---------------------------- | -------------------- | ----------- |
| `resnet50` + dilation=False  | `detr_resnet50`      | **最常用**     |
| `resnet50` + dilation=True   | `detr_resnet50_dc5`  | 分割/更密特征     |
| `resnet101` + dilation=False | `detr_resnet101`     | 更深 backbone |
| `resnet101` + dilation=True  | `detr_resnet101_dc5` | 深 + 空洞      |
| `resnet18` / `resnet34`      | 无                    | 轻量实验用       |

关于backbone的输出：检测任务只用 layer4 一层，分割任务才开启中间层的特征输出（`return_interm_layers=True`）

---

和标准transformer的差异：
1. 位置编码在 MHA 内部加，而不是在输入前统一加。这样 query/key 可以分别加不同的位置信息（image pos vs query pos）
2. encoder 末尾去掉 LayerNorm。标准 Transformer 在 encoder 最后有 norm，DETR 去掉了
3. decoder 返回所有层的中间输出。用于 aux loss（decoder 每层都监督）

---

完整数据流汇总表

| 阶段              | 输入内容                 | 输入Shape                   | 输出内容         | 输出Shape                                |
| --------------- | -------------------- | ------------------------- | ------------ | -------------------------------------- |
| **Backbone**    | RGB图像 + padding mask | [B,3,H,W] + [B,H,W]       | 多尺度特征 + 位置编码 | [B,2048,H/32,W/32] + [B,256,H/32,W/32] |
| **Input Proj**  | 最后一层特征               | [B,2048,25,37]            | 通道压缩特征       | [B,256,25,37]                          |
| **Flatten**     | 空间特征图                | [B,256,25,37]             | 序列化token     | [925,B,256]                            |
| **Encoder×6**   | 视觉token + pos + mask | [925,B,256]               | 全局编码特征       | [925,B,256]                            |
| **Decoder×6**   | query + memory + pos | [100,B,256] + [925,B,256] | 多层解码输出       | [6,100,B,256]                          |
| **Class Head**  | decoder最后一层          | [B,100,256]               | 类别logits     | [B,100,92]                             |
| **BBox Head**   | decoder最后一层          | [B,100,256]               | 框坐标          | [B,100,4]                              |
| **Mask Head**   | 特征+注意力+FPN           | [200,264,25,37]           | 分割掩码         | [B,100,H/4,W/4]                        |
| **Matcher**     | 预测 + GT              | [100,4]+[N,4]             | 匹配索引         | [(pred_idx,gt_idx)]                    |
| **Criterion**   | 预测 + 匹配结果            | -                         | 各项损失         | scalar dict                            |
| **PostProcess** | 原始输出 + 图像尺寸          | [B,100,92]+[B,100,4]      | 检测结果         | List[dict]                             |

理论上模型应该支持任意size的图片，为什么要缩放？
- size越大计算量越大
- 极端值会导致显存和计算浪费
- backbone预训练是基于小size的数据集


为什么可以并行解码？
我们用100个query同时输入decoder计算，因为不同query针对不同类型的物体进行识别，不同query之间没有依赖，不像文本序列类的任务需要自回归生成，所以可以并行计算。
