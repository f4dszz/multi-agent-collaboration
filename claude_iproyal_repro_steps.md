# Claude + IPRoyal 复现步骤

目标：
- `Claude Code CLI` 走 `IPRoyal` 静态 IP
- `Claude` 网页走 `IPRoyal` 静态 IP
- 其它普通流量继续走 `RioLU` 默认节点，不把整机流量压到 `IPRoyal`

当前思路：
- `Clash Verge` 用 `Rule` 模式
- `TUN` 关闭
- `System Proxy` 开启
- `Claude` 相关进程和域名单独指到 `IPRoyal Exit`
- `Claude Code` 通过官方 `HTTP_PROXY/HTTPS_PROXY` 配置走本地 Clash 端口

## 1. Clash Verge 基础状态

确认：
- `mixed-port` 是 `7897`
- 模式切到 `Rule`
- `System Proxy` 开
- `TUN` 关

说明：
- 不建议长期 `Global + IPRoyal`
- 原因是整机后台流量会一起压到静态代理上，容易超时

## 2. 在 Clash Verge 中保留 IPRoyal 出口组

需要有一个策略组：
- `IPRoyal Exit`

并且组内的最终出口是你的静态代理节点，例如：
- `SOCKS5 63.88.218.46:12324`

如果你用的是链式代理：
- 第一跳：`RioLU` 节点
- 第二跳：`IPRoyal` 静态节点

## 3. 给当前活动订阅加 Rule 增强

当前规则增强文件：
- `C:\Users\wondertek\AppData\Roaming\io.github.clash-verge-rev.clash-verge-rev\profiles\rkPrFSiLxsQC.yaml`

内容应为：

```yaml
# Profile Enhancement Rules Template for Clash Verge

prepend:
  - PROCESS-NAME,Claude.exe,IPRoyal Exit
  - PROCESS-NAME,cowork-svc.exe,IPRoyal Exit
  - DOMAIN-SUFFIX,claude.ai,IPRoyal Exit
  - DOMAIN-SUFFIX,anthropic.com,IPRoyal Exit
  - DOMAIN,anthropic.skilljar.com,IPRoyal Exit

append: []

delete: []
```

改完后：
- 在 Clash Verge 里重载当前 profile
- 然后切到 `Rule`

## 4. 给 Claude Code 配官方代理

文件：
- `C:\Users\wondertek\.claude\settings.json`

关键配置：

```json
{
  "env": {
    "HTTP_PROXY": "http://127.0.0.1:7897",
    "HTTPS_PROXY": "http://127.0.0.1:7897",
    "NO_PROXY": ""
  }
}
```

说明：
- 这是 `Claude Code` 官方支持的代理方式
- 不需要每次手动设环境变量

## 5. 网页版如何走静态 IP

不要用日常 Chrome，单独起一个专用实例：

```powershell
& 'C:\Program Files\Google\Chrome\Application\chrome.exe' `
  --proxy-server="http://127.0.0.1:7897" `
  --user-data-dir="$env:TEMP\chrome-claude"
```

然后在这个专用 Chrome 里打开：
- `https://claude.ai`

## 6. 如何验证现在是不是从静态 IP 出去

验证本地 Clash 口：

```powershell
curl.exe --proxy http://127.0.0.1:7897 http://ifconfig.me/ip
```

如果返回你的 IPRoyal IP，例如：

```text
63.88.218.46
```

说明：
- 凡是明确走到 `127.0.0.1:7897` 的请求，最终都会从这个静态 IP 出去

## 7. 为什么切到 Rule 后 Clash 显示的是精灵学院节点 IP

这是正常现象。

原因：
- `Rule` 模式下，只有命中上面这些 `Claude/Anthropic` 规则的流量才走 `IPRoyal Exit`
- 其它普通流量仍然走 `RioLU` 默认节点
- 所以 Clash 主界面上看到的“当前 IP”通常反映的是默认流量出口，不是所有规则分流后的真实结果

影响：
- 对 `Claude` 网页和 `Claude Code CLI` 没有直接负面影响
- 只要它们命中了上面的规则或本地代理口，仍然可以走静态 IP

正确验证方式：
- 不看 Clash 首页展示 IP
- 看定向验证命令和连接日志

## 8. 后续建议

如果只是要：
- `Claude Code CLI`
- `Claude` 网页

那么当前这套 `Rule + 专用 Chrome + Claude Code 官方代理` 就够了。

如果以后要让更多 Windows App 也稳定走静态 IP：
- 优先考虑按进程代理
- 不建议直接把整机 `Global` 压到 `IPRoyal`
