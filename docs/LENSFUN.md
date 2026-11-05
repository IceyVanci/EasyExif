# Lensfun 数据说明

EasyExif 不内置镜头/设备数据库。界面中的“镜头库”来自可选的 Lensfun XML 数据包。

## 启用方式

把 Lensfun XML 数据放到以下任一位置：

~~~text
%CD%\lensfun
%USERPROFILE%\EasyExif\lensfun
~~~

或设置环境变量：

~~~text
EASYEXIF_LENSFUN_DIR=F:\path\to\lensfun-data
~~~

目录及其子目录中的 .xml 文件会被读取。没有数据时，界面显示“未加载”，不会产生镜头范围警告。

## 用途

- 相机/镜头匹配
- 焦距范围和最大光圈提示
- 等效焦距、广角/标准/长焦分类
- 可选：后续接入畸变/暗角等校准数据

镜头范围提示只作为设备信息展示，不改变 13 项原图可信度评分。

## 许可证

Lensfun 数据库通常采用 Creative Commons Attribution-ShareAlike 3.0（CC BY-SA 3.0），
Lensfun 库本身采用 LGPL。具体以数据包和官方仓库中的 LICENSE 为准。

请把 Lensfun 数据作为独立数据包分发，保留署名、许可证和来源说明；不要把数据
直接混入 EasyExif 的 MIT 源代码。

- https://lensfun.github.io/
- https://github.com/lensfun/lensfun
