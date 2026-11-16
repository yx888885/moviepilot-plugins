# PT优选同步中兴Hosts（ptrouterhosts）

MoviePilot V3 插件：从 PT-Accelerator 实时拉取 CF 优选 Hosts，自动同步到中兴问天路由器自定义 Hosts。

## 功能

- 每次运行调用 PT-Accelerator 的 `/api/current-hosts` 拿最新优选结果（**不用容器里的旧 /etc/hosts**，那是创建时的快照，永远不更新）
- 读取中兴问天（ZXSLC SR7410 系）路由器当前自定义 Hosts
- 用优选结果**覆盖同名域名**，路由器上其它条目原样保留
- 支持「仅 PT 站点段」或「PT 段 + GitHub/TMDB 段」两种同步范围
- 写回后回读校验，未生效会明确报失败
- 写后结果可发送 MP 通知

## 安装

在 MoviePilot V3 的 **系统设置 → 插件市场** 添加本仓库地址：

```
https://github.com/yx888885/moviepilot-plugins
```

然后在插件市场安装「PT优选同步中兴Hosts」。

## 配置说明

| 配置项 | 说明 |
| --- | --- |
| 启用插件 | 开启后按 cron 定时同步 |
| 发送通知 | 同步结果是否推送 MP 通知 |
| 立即运行一次 | 保存后 5 秒执行一次 |
| 同步范围 | 仅 PT 站点段 / PT 段 + GitHub/TMDB 段 |
| 执行周期（cron） | 默认 `20 7 * * *`，即每天 07:20（等 pt-accelerator 07:00 优选跑完） |
| PT-Accelerator 地址 | 如 `http://NAS的IP:23333` |
| 路由器地址 | 如 `http://192.168.5.1` |
| 路由器管理密码 | **只在插件配置页填写，不写入代码、不进仓库** |

## 注意事项

- 中兴问天路由器自定义 Hosts 上限 512 条，只收 `IP 域名` 两列，**不支持带端口域名**
- 路由器密码、PT-Accelerator 地址等敏感信息请只在 MP 插件配置页填写，不要提交到代码或仓库
- 优选 IP 变化后，等下一次定时同步（或点「立即运行一次」）即可刷新路由器
