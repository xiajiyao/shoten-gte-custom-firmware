# 第三方资料与许可范围

## SHOTEN / 焦点工房

本项目的成品 BIN 包含官方 Ver.04 原版代码及自定义扩展。原版代码的著作权和相关权利归原权利人；本项目不替厂商授予许可，也不声明厂商代码采用 MIT 许可。仓库不附单独的原版镜像；构建时从厂商取得并校验。

- [官方支持页](https://stkb.co.jp/support.html#gte)
- [Ver.04 输入镜像](https://stkb.co.jp/file/Ver.04.bin)
- [USB 更新说明](https://stkb.co.jp/file/GTE_dl_manual.pdf)
- [GTE 产品与镜头登记说明](https://www.stkb.jp/shopdetail/000000001523/)

## EA9 实现与协议研究

感谢 Aylwin Wei 的 [E-mount-impl-on-Techart-EA9](https://github.com/weiziqian/E-mount-impl-on-Techart-EA9) 和 [E-mount-protocol-RE](https://github.com/weiziqian/E-mount-protocol-RE)。本项目参考其协议研究、身份/光学文件布局和经验性光学参数表达，并针对 GTE 原版地址、马达和存储布局另写桥接逻辑；不是将 EA9 成品固件移植到 GTE。

开发时检查的 EA9 源码快照：

- `51ce0a5716a148a3ff092fe1ffcd65678bac4371`
- v2.4 快照 `4ab7b992ecdf38346e9b49965c65282cb420038e`

EA9 项目的 MIT 文本及 `Copyright (c) 2026 Aylwin Wei` 完整保留于 [third_party/licenses/EA9-MIT.txt](third_party/licenses/EA9-MIT.txt)。该文本仅覆盖适用的第三方内容，不自动覆盖厂商原版或整个混合镜像。

## ZEISS 光学规格

镜头实际焦距、后焦距和出瞳相关几何数据参考 ZEISS 历史 Contax G 数据表。资料用于近似生成预设，没有实际标定光学行程或边缘参数。数据表本身未捆绑在仓库：

- [Biogon 21/2.8](https://www.zeiss.com/content/dam/consumer-products/downloads/historical-products/photography/contax-g/en/datasheet-zeiss-biogon-2821-en.pdf)
- [Biogon 28/2.8](https://www.zeiss.com/content/dam/consumer-products/downloads/historical-products/photography/contax-g/en/datasheet-zeiss-biogon-2828-en.pdf)
- [Planar 35/2](https://www.zeiss.com/content/dam/consumer-products/downloads/historical-products/photography/contax-g/en/datasheet-zeiss-planar-235-en.pdf)
- [Planar 45/2](https://www.zeiss.com/content/dam/consumer-products/downloads/historical-products/photography/contax-g/en/datasheet-zeiss-planar-245-en.pdf)
- [Sonnar 90/2.8](https://www.zeiss.com/content/dam/consumer-products/downloads/historical-products/photography/contax-g/en/datasheet-zeiss-sonnar-2890-en.pdf)
- [Vario-Sonnar 35–70/3.5–5.6](https://www.zeiss.com/content/dam/consumer-products/downloads/historical-products/photography/contax-g/en/datasheet-zeiss-vario-sonnar-35563570-en.pdf)

## 构建依赖与本项目文件

Zig/ziglang 与 Unicorn 由使用者通过其分发渠道安装，依赖本体没有放进仓库，各自遵循其自身许可。

本次整理没有为本项目新增源码和文档另行指定统一的开源许可证。公开可读不等于对所有内容授予任意再分发或商用许可；如后续选定项目许可，应明确其只覆盖有权许可的新增内容。

SHOTEN、TECHART、Sony、Contax、ZEISS 等名称仅用于说明适配对象和资料来源，不表示任何厂商认可或担保本项目。
