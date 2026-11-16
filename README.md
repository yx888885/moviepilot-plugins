# moviepilot-plugins

MoviePilot V3 自定义插件仓库。

## 插件列表

| 插件 ID | 名称 | 说明 |
| --- | --- | --- |
| [ptrouterhosts](plugins.v3/ptrouterhosts/README.md) | PT优选同步中兴Hosts | 从 PT-Accelerator 拉取 CF 优选 Hosts，同步到中兴问天路由器 |

## 安装

在 MoviePilot V3 **系统设置 → 插件市场** 添加仓库地址：

```
https://github.com/yx888885/moviepilot-plugins
```

## 目录结构

```
package.v3.json                          # 插件清单
plugins.v3/<plugin_id>/__init__.py       # 插件源码
plugins.v3/<plugin_id>/README.md         # 插件说明
icons/                                   # 插件图标
```
