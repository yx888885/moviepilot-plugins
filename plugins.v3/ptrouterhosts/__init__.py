import re
import html
import json
import hashlib
import urllib.request
import urllib.parse
import http.cookiejar
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.log import logger
from app.plugins import _PluginBase

# 路由器自定义 Hosts 上限
MAX_ITEMS = 512

# 永不写入路由器的条目（本机/容器/回环/组播名）
SKIP_HOSTS = {
    "localhost", "ip6-localhost", "ip6-loopback", "ip6-localnet",
    "ip6-mcastprefix", "ip6-allnodes", "ip6-allrouters",
    "Z4Pro", "Z4Pro-UZ1L", "Z4Pro-BA2G",
}

# 源段标记（pt-accelerator 往 /etc/hosts 写的时候的分隔注释）
SEG_PT_BEGIN = "PT站点加速开始"
SEG_PT_END = "PT站点加速结束"


class ptrouterhosts(_PluginBase):
    # 插件元信息
    plugin_name = "PT优选同步中兴Hosts"
    plugin_desc = "从 PT-Accelerator 实时拉取 CF 优选 Hosts，自动同步到中兴问天路由器自定义 Hosts。"
    plugin_icon = "https://raw.githubusercontent.com/yx888885/moviepilot-plugins/main/icons/ptrouterhosts.png"
    plugin_version = "1.0"
    plugin_author = "yx888885"
    author_url = "https://github.com/yx888885"
    plugin_config_prefix = "ptrouterhosts_"
    plugin_order = 64
    auth_level = 1

    # 运行态
    _enabled: bool = False
    _notify: bool = False
    _onlyonce: bool = False
    _cron: Optional[str] = None
    _accel_url: Optional[str] = None
    _router_url: Optional[str] = None
    _router_password: Optional[str] = None
    _sync_mode: str = "pt"
    _scheduler = None

    def init_plugin(self, config: Optional[dict] = None) -> None:
        config = config or {}
        self._enabled = bool(config.get("enabled"))
        self._notify = bool(config.get("notify"))
        self._onlyonce = bool(config.get("onlyonce"))
        self._cron = (config.get("cron") or "").strip()
        self._accel_url = (config.get("accel_url") or "").strip() 
        self._router_url = (config.get("router_url") or "").strip() 
        self._router_password = config.get("router_password") or ""
        self._sync_mode = config.get("sync_mode") or "pt"

        self.stop_service()

        if not self._enabled:
            logger.info("【PT优选同步中兴Hosts】未启用")
            return

        if self._onlyonce:
            from apscheduler.schedulers.background import BackgroundScheduler
            import pytz
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            self._scheduler.add_job(
                func=self.sync_hosts,
                trigger="date",
                run_date=datetime.now(tz=pytz.timezone(settings.TZ)) + timedelta(seconds=5),
                name="PT优选同步中兴Hosts",
            )
            self._scheduler.start()
            self._onlyonce = False
            cfg = dict(config)
            cfg["onlyonce"] = False
            self.update_config(cfg)

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        if self._enabled and self._cron:
            logger.info(f"【{self.plugin_name}】定时服务已注册，cron={self._cron}")
            return [{
                "id": "ptrouterhosts",
                "name": f"{self.plugin_name}服务",
                "trigger": CronTrigger.from_crontab(self._cron),
                "func": self.sync_hosts,
                "kwargs": {},
            }]
        return []

    def stop_service(self) -> None:
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._scheduler.shutdown()
                self._scheduler = None
        except Exception as e:
            logger.info(f"【{self.plugin_name}】stop_service: {e}")

    # ------------------------------------------------------------------ 表单

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "density": "comfortable",
                                            "title": "工作原理",
                                            "text": (
                                                "每次运行：① 调用 PT-Accelerator 的 /api/current-hosts "
                                                "拿到最新优选结果（不用容器里的旧 /etc/hosts）"
                                                "② 读取中兴路由器当前自定义 Hosts "
                                                "③ 用优选结果覆盖同名域名，路由器上其它条目原样保留 "
                                                "④ 写回并回读校验。"
                                            ),
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                                {"component": "VSwitch", "props": {"model": "enabled", "label": "启用插件", "color": "primary"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                                {"component": "VSwitch", "props": {"model": "notify", "label": "发送通知", "color": "info"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                                {"component": "VSwitch", "props": {"model": "onlyonce", "label": "立即运行一次", "color": "success"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [
                                {"component": "VSelect", "props": {
                                    "model": "sync_mode", "label": "同步范围", "density": "compact",
                                    "items": [
                                        {"title": "仅 PT 站点段（12 条）", "value": "pt"},
                                        {"title": "PT 段 + GitHub/TMDB 段（全部）", "value": "all"},
                                    ]}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12}, "content": [
                                {"component": "VTextField", "props": {
                                    "model": "cron", "label": "执行周期（cron）",
                                    "placeholder": "20 7 * * *",
                                    "hint": "建议 20 7 * * *，即每天 07:20，等 pt-accelerator 07:00 优选跑完",
                                    "persistent-hint": True}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VTextField", "props": {
                                    "model": "accel_url", "label": "PT-Accelerator 地址",
                                    "placeholder": "http://NAS的IP:23333"}}]},
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VTextField", "props": {
                                    "model": "router_url", "label": "路由器地址",
                                    "placeholder": "http://路由器IP"}}]},
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                                {"component": "VTextField", "props": {
                                    "model": "router_password", "label": "路由器管理密码",
                                    "type": "password"}}]},
                        ],
                    },
                ],
            }
        ], {
            "enabled": False,
            "notify": True,
            "onlyonce": False,
            "sync_mode": "pt",
            "cron": "20 7 * * *",
            "accel_url": "",
            "router_url": "",
            "router_password": "",
        }

    def get_page(self) -> Optional[List[dict]]:
        last = self.get_data("last_result") or {}
        if not last:
            return [{"component": "VRow", "content": [{"component": "VCol", "props": {"cols": 12}, "content": [
                {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "text": "还没有执行记录。"}}]}]}]
        lines = [f"{k}：{v}" for k, v in last.items()]
        return [{"component": "VRow", "content": [{"component": "VCol", "props": {"cols": 12}, "content": [
            {"component": "VCard", "props": {"variant": "tonal"}, "content": [
                {"component": "VCardTitle", "text": "上次同步结果"},
                {"component": "VCardText", "content": [
                    {"component": "div", "props": {"style": "white-space: pre-wrap; font-family: monospace;"},
                     "text": "\n".join(lines)}]},
            ]}]}]}]

    # ------------------------------------------------------------ 数据获取

    def _fetch_accel_hosts(self) -> List[str]:
        """从 PT-Accelerator API 拿 /etc/hosts 全量内容（免认证，实时）。"""
        url = self._accel_url.rstrip("/") + "/api/current-hosts"
        req = urllib.request.Request(url, headers={"User-Agent": settings.USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        lines = data.get("hosts") or []
        out: List[str] = []
        for ln in lines:
            out.extend(str(ln).splitlines())
        return out

    @staticmethod
    def _extract_pt_segment(lines: List[str]) -> List[str]:
        """只取「PT站点加速开始/结束」之间的内容，避免把 GitHub/TMDB 一起带出。"""
        got, inside = [], False
        for ln in lines:
            if SEG_PT_BEGIN in ln:
                inside = True
                continue
            if SEG_PT_END in ln:
                inside = False
                continue
            if inside:
                got.append(ln)
        return got

    def _parse_pairs(self, lines: List[str]) -> List[Tuple[str, str]]:
        pairs, seen = [], set()
        for raw in lines:
            s = raw.lstrip("\ufeff").strip()
            if not s or s.startswith("#"):
                continue
            parts = re.split(r"\s+", s)
            if len(parts) < 2:
                continue
            ip, dom = parts[0], parts[1]
            # 路由器只收 IPv4，且不支持带端口
            if not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", ip):
                continue
            dom = re.sub(r":\d+$", "", dom)
            if not dom or dom in SKIP_HOSTS:
                continue
            if (ip, dom) in seen:
                continue
            seen.add((ip, dom))
            pairs.append((ip, dom))
        return pairs

    # ------------------------------------------------------------ 路由器操作

    def _router(self):
        return _ZTERouter(self._router_url, self._router_password)

    # ------------------------------------------------------------ 主流程

    def sync_hosts(self) -> None:
        if not self._router_password:
            self._finish(False, "缺少路由器管理密码，未执行", {})
            return
        if not self._accel_url:
            self._finish(False, "缺少 PT-Accelerator 地址，未执行", {})
            return
        if not self._router_url:
            self._finish(False, "缺少路由器地址，未执行", {})
            return

        try:
            all_lines = self._fetch_accel_hosts()
        except Exception as e:
            self._finish(False, f"拉取 PT-Accelerator 优选失败：{e}", {})
            return

        src = self._extract_pt_segment(all_lines) if self._sync_mode != "all" else all_lines
        pairs = self._parse_pairs(src)
        if len(pairs) < 3:
            self._finish(False, f"解析到的有效条目只有 {len(pairs)} 条，疑似源异常，已放弃写入", {})
            return

        want = {dom: ip for ip, dom in pairs}

        try:
            rt = self._router()
            rt.login()
            current = rt.read_hosts()
        except Exception as e:
            self._finish(False, f"路由器登录/读取失败：{e}", {})
            return

        if len(current) < 20:
            self._finish(False, f"路由器回读只有 {len(current)} 条，疑似异常，已放弃写入", {})
            return

        cur_map = {dom: ip for ip, dom in current_pairs(current)}
        merged: List[Tuple[str, str]] = []
        handled = set()
        for line in current:
            parts = re.split(r"\s+", line.strip())
            if len(parts) < 2:
                continue
            ip, dom = parts[0], parts[1]
            if dom in want:
                merged.append((want[dom], dom))
                handled.add(dom)
            else:
                merged.append((ip, dom))

        added = [d for d in want if d not in handled]
        changed = []
        for d, newip in want.items():
            old = cur_map.get(d)
            if old is None:
                changed.append(f"{d}: 新增 -> {newip}")
            elif old != newip:
                changed.append(f"{d}: {old} -> {newip}")

        if not changed:
            ipset = sorted(set(want.values()))
            self._finish(True, f"无需更新，路由器已是优选 IP {'/'.join(ipset)}（{len(want)} 个域名）",
                         {"条目数": len(merged), "优选IP": "/".join(ipset)})
            return

        for d in added:
            merged.append((want[d], d))

        if len(merged) > MAX_ITEMS:
            merged = merged[:MAX_ITEMS]
            logger.warning(f"【{self.plugin_name}】条目超过 {MAX_ITEMS}，已截断")

        try:
            ok, msg = rt.submit(merged)
        except Exception as e:
            self._finish(False, f"写入路由器异常：{e}", {})
            return

        if not ok:
            self._finish(False, f"写入失败：{msg}", {})
            return

        # 回读校验
        try:
            rt.refresh_token()
            after = dict()
            for line in rt.read_hosts():
                parts = re.split(r"\s+", line.strip())
                if len(parts) >= 2:
                    after[parts[1]] = parts[0]
            missing = [d for d in want if after.get(d) != want[d]]
        except Exception as e:
            self._finish(False, f"写入返回成功但回读校验异常：{e}", {})
            return

        if missing:
            self._finish(False, f"回读校验不通过，{len(missing)} 个域名未生效：{', '.join(missing[:5])}", {})
            return

        ipset = sorted(set(want.values()))
        self._finish(True,
                     f"同步成功：{len(want)} 个域名 → {'/'.join(ipset)}，路由器共 {len(merged)} 条",
                     {"条目数": len(merged), "优选IP": "/".join(ipset),
                      "变更": "\n".join(changed[:15]) if changed else "—"})

    def _finish(self, ok: bool, summary: str, extra: Dict[str, Any]) -> None:
        rec = {"时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
               "结果": "✅ 成功" if ok else "❌ 失败",
               "说明": summary}
        rec.update({k: v for k, v in extra.items()})
        self.save_data("last_result", rec)

        if ok:
            logger.info(f"【{self.plugin_name}】{summary}")
        else:
            logger.error(f"【{self.plugin_name}】{summary}")

        if self._notify:
            title = f"【🛜 PT优选同步中兴Hosts】{'同步成功' if ok else '同步失败'}"
            self.post_message(title=title, text=summary)


def current_pairs(lines: List[str]) -> List[Tuple[str, str]]:
    out = []
    for line in lines:
        parts = re.split(r"\s+", line.strip())
        if len(parts) >= 2:
            out.append((parts[0], parts[1]))
    return out


class _ZTERouter:
    """中兴问天（ZXSLC SR7410 系）自定义 Hosts 读写客户端。

    protocol:
      GET  ?_type=loginsceneData&_tag=login_token_json  -> _sessionToken / logintoken
      POST ?_type=loginData&_tag=login_entry            -> Password=sha256(pw+logintoken)
      GET  ?_type=vueData&_tag=vue_hosts_data           -> WebString<N>/ParaValue XML
      POST ?_type=vueData&_tag=vue_hosts_data           -> IF_ACTION=Apply + 512 槽位 + _sessionTOKEN
    """

    TAG = "?_type=vueData&_tag=vue_hosts_data"

    def __init__(self, base_url: str, password: str, username: str = "admin"):
        self.base = base_url.rstrip("/") + "/"
        self.password = password
        self.username = username
        self.token = ""
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar))

    def _headers(self, req: urllib.request.Request) -> None:
        req.add_header("User-Agent", settings.USER_AGENT)
        req.add_header("Referer", self.base)
        req.add_header("Accept", "application/json, text/plain, */*")
        if self.token:
            req.add_header("X_XSRF_TOKEN", self.token)

    def _get(self, path: str) -> str:
        req = urllib.request.Request(self.base + path)
        self._headers(req)
        with self.opener.open(req, timeout=25) as r:
            t = r.headers.get("X_XSRF_TOKEN")
            if t:
                self.token = t
            return r.read().decode("utf-8", "replace")

    def _post(self, path: str, data: Dict[str, str]) -> str:
        d = dict(data)
        if self.token:
            d["_sessionTOKEN"] = self.token  # 必须，缺了报 e_csrf_check_fail
        req = urllib.request.Request(
            self.base + path, data=urllib.parse.urlencode(d).encode(), method="POST")
        self._headers(req)
        req.add_header("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
        req.add_header("X-Requested-With", "XMLHttpRequest")
        with self.opener.open(req, timeout=60) as r:
            t = r.headers.get("X_XSRF_TOKEN")
            if t:
                self.token = t
            return r.read().decode("utf-8", "replace")

    def refresh_token(self) -> dict:
        j = json.loads(self._get("?_type=loginsceneData&_tag=login_token_json"))
        self.token = j.get("_sessionToken") or self.token
        self._logintoken = j.get("logintoken", "")
        return j

    def login(self) -> dict:
        j = self.refresh_token()
        digest = hashlib.sha256((self.password + j.get("logintoken", "")).encode()).hexdigest()
        res = self._post("?_type=loginData&_tag=login_entry", {
            "Username": self.username,
            "Password": digest,
            "action": "login",
            "Frm_Logintoken": "",
            "captchaCode": "",
        })
        out = json.loads(res)
        if out.get("sess_token"):
            self.token = out["sess_token"]
        if str(out.get("loginErrType", "")) not in ("", "0", "None"):
            raise RuntimeError(f"登录失败：{out.get('loginErrType')}")
        return out

    def read_hosts(self) -> List[str]:
        xml = self._get(self.TAG)
        raw = "".join(v for _, v in re.findall(
            r"<ParaName>WebString(\d+)</ParaName><ParaValue>(.*?)</ParaValue>", xml, re.S))
        cur = html.unescape(raw)
        return [ln.strip() for ln in re.split(r"[\n\r]+", cur) if ln.strip()]

    def submit(self, pairs: List[Tuple[str, str]]) -> Tuple[bool, str]:
        if len(pairs) > MAX_ITEMS:
            return False, f"条目 {len(pairs)} 超过路由器上限 {MAX_ITEMS}"
        data = {"IF_ACTION": "Apply", "Count": str(len(pairs) + 1), "EmptyFlag": "0"}
        for i in range(MAX_ITEMS):
            if i < len(pairs):
                ip, dom = pairs[i]
                data[f"IPAddress{i}"] = ip
                data[f"HostName{i}"] = dom
            else:
                data[f"IPAddress{i}"] = ""
                data[f"HostName{i}"] = ""
        resp = self._post(self.TAG, data)
        err = re.search(r"<IF_ERRORSTR>(.*?)</IF_ERRORSTR>", resp)
        eid = re.search(r"<IF_ERRORID>(.*?)</IF_ERRORID>", resp)
        status = err.group(1) if err else ""
        if status == "SUCC" or (eid and eid.group(1) == "0"):
            return True, "SUCC"
        return False, status or (eid.group(1) if eid else "未知错误")
