四个模块：Local Feature CNN做特征提取，LoFTR Module用Transformer处理粗特征，Matching Module粗匹配，Coarse-to-Fine Module细化匹配


| 模块 | 参数量 | 占比 |
|------|--------|------|
| **backbone** | 5,915,888 (5.92M) | 51.2% |
| **loftr_coarse** | 5,251,072 (5.25M) | 45.4% |
| **loftr_fine** | 328,704 (0.33M) | 2.8% |
| **fine_preprocess** | 65,792 (0.07M) | 0.6% |
| pos_encoding | 0 | 0% |
| coarse_matching | 0 | 0% |
| fine_matching | 0 | 0% |
| **总计** | **11,561,456 (11.56M)** | **100%** |


**说明：**

- **backbone** (51.2%)：ResNet+FPN 特征提取网络，占比最大
- **loftr_coarse** (45.4%)：8层 Coarse Transformer，参数量也大
- **loftr_fine** (2.8%)：1层 Fine Transformer，参数量小很多
- **fine_preprocess** (0.6%)：可选的细粒度预处理投影层
- **Matching 模块** (0%)：CoarseMatching 和 FineMatching 没有可训练参数，纯算法