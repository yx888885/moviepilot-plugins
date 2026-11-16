# PT 优选加速一条龙部署教程

本教程把「Cloudflare 优选 → NAS hosts → 中兴问天路由器」整条链路串起来，从零部署到全家终端生效。

## 整体架构

```
┌─────────────────────────────────────────────────────────────┐
│ ① pt-accelerator 镜像容器（数据源，必须先装）               │
│    · 每日 07:00 跑 CloudflareST 优选 CF 节点 IP              │
│    · 把优选结果写进 NAS 的 /etc/hosts（PT-Accelerator 段）  │
│    · 提供 HTTP 接口 :23333/api/current-hosts（免认证）      │
└──────────────────────────────┬──────────────────────────────┘
                               │ 实时拉取
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ ② MP 插件 ptrouterhosts（本仓库，装在 MoviePilot V3）        │
│    · 每日 07:20 定时，等上面优选跑完再拉                     │
│    · 覆盖同名域名、保留路由器其它条目、写后回读校验           │
└──────────────────────────────┬──────────────────────────────┘
                               │ 写自定义 Hosts
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ ③ 中兴问天路由器 自定义 Hosts（上限 512 条）                 │
│    · 对全家走路由器 DNS 的终端生效                            │
└─────────────────────────────────────────────────────────────┘
```

> 注意：镜像容器叫 **pt-accelerator**（上游项目 `eternalcurse/pt-accelerator`），
> **PTRouterHosts / ptrouterhosts 是 MP 插件的名字**，两者不是一回事。

---

## 第一步：部署 pt-accelerator 镜像容器

这是整套方案的数据源，**必须先装**。

### 1. 准备目录

```bash
mkdir -p /你的docker目录/pt-accelerator/{config,logs}
```

### 2. 编写 docker-compose.yml

在 `/你的docker目录/pt-accelerator/` 下新建 `docker-compose.yml`：

```yaml
services:
  pt-accelerator:
    image: eternalcurse/pt-accelerator:latest
    container_name: pt-accelerator
    restart: unless-stopped
    network_mode: "host"
    environment:
      - TZ=Asia/Shanghai
      - APP_PORT=23333
    volumes:
      # 配置持久化（防止重启丢设置）
      - /你的docker目录/pt-accelerator/config:/app/config
      # 日志持久化
      - /你的docker目录/pt-accelerator/logs:/app/logs
      # 关键！挂载宿主机 /etc/hosts，容器才有权限改写它
      - /etc/hosts:/etc/hosts
```

> 路径 `/你的docker目录/` 换成你自己的实际目录。
> 网络用 host 模式；`APP_PORT` 默认 23333，可改。

### 3. 启动

```bash
cd /你的docker目录/pt-accelerator
docker compose up -d
```

### 4. 打开 Web 界面

浏览器访问 `http://NAS的IP:23333`，进入配置页（若开了认证需登录）。

---

## 第二步：配置 pt-accelerator（Web 界面）

所有配置在 Web 界面实时生效，无需手改 yaml。建议配这几项：

1. **Cloudflare 优选**：`enable` 打开，`cron` 设 `0 7 * * *`（每天 07:00）。
2. **PT Tracker 列表**：逐个添加你要加速的 PT 站点 tracker 域名（Cloudflare 托管的才会被优选，非 CF 站点会自动过滤）。
3. **Hosts 源**：按需启用 GitHub / TMDB 等加速源（默认已带一批）。
4. **下载器导入**（可选）：把 qBittorrent / Transmission 加进来，用于 tracker 批量管理。
5. **认证**（可选）：开启后访问 Web 界面需要账号密码。

配置完等一次优选执行（或手动触发），确认 NAS `/etc/hosts` 里出现 `PT-Accelerator START / END` 段，且 `:23333/api/current-hosts` 能返回数据即可。

---

## 第三步：安装 MP 插件 ptrouterhosts

1. 打开 MoviePilot V3 → **系统设置 → 插件市场**。
2. 添加仓库地址：

```
https://github.com/yx888885/moviepilot-plugins
```

3. 在插件市场搜索「PT优选」，安装 **PT优选同步中兴Hosts**。

---

## 第四步：配置插件

进插件设置页，填：

| 配置项 | 填什么 |
| --- | --- |
| 启用插件 | 打开 |
| 同步范围 | 默认「仅 PT 站点段」；要连 GitHub/TMDB 一起同步就选「全部」 |
| 执行周期（cron） | `20 7 * * *`（每天 07:20，等优选 07:00 跑完） |
| PT-Accelerator 地址 | `http://NAS的IP:23333` |
| 路由器地址 | `http://192.168.5.1`（或你的路由器 IP） |
| 路由器管理密码 | 你的中兴路由器后台密码 |

> ⚠️ **路由器密码只填在这个配置页里**，插件只读配置、不写代码、不进仓库、不上传任何地方。

保存后点「立即运行一次」测试。

---

## 第五步：验证是否生效

在 NAS 上查路由器 DNS（别只看本机，要直接问路由器）：

```bash
dig +short @192.168.5.1 tracker.m-team.cc
dig +short @192.168.5.1 ptzone.xyz
dig +short @192.168.5.1 api.tmdb.org
```

返回的 IP 应是优选出来的 CF 节点 IP（而不是默认解析），就说明整条链路打通了。

---

## 常见问题

- **路由器 Hosts 上限 512 条**，且只收 `IP 域名` 两列，**不支持带端口域名**（如 `tracker.xxx.org:2910` 这类要先去端口）。
- **优选 IP 变了怎么办？** 等下一次定时同步，或点插件里的「立即运行一次」。
- **写失败？** 看 MP 插件日志，常见原因：路由器密码错、地址填错、回读校验不通过（详见插件说明）。
- **为什么不用容器里的 /etc/hosts？** 那只是创建容器时的旧快照，永远不更新；插件走的是 `:23333/api/current-hosts` 实时接口。

---

## 敏感信息提醒

本仓库源码**不含任何密码、token 或内网地址**。所有敏感信息（路由器密码、下载器密码、认证账号）只存在你自己的本地配置里，切勿提交到任何公开仓库。
