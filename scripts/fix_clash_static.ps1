$ErrorActionPreference = 'Stop'

$root = 'C:\Users\wondertek\AppData\Roaming\io.github.clash-verge-rev.clash-verge-rev'
$clash = Join-Path $root 'clash-verge.yaml'
$check = Join-Path $root 'clash-verge-check.yaml'
$verge = Join-Path $root 'verge.yaml'
$dnsCfg = Join-Path $root 'dns_config.yaml'
$rulesTpl = Join-Path $root 'profiles\rkPrFSiLxsQC.yaml'
$mergeTpl = Join-Path $root 'profiles\m6RWCoXjag7C.yaml'
$proxyTpl = Join-Path $root 'profiles\p5UAbGTwKGDL.yaml'
$settings = 'C:\Users\wondertek\.claude\settings.json'
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'

$dnsBlock = @"
dns:
  enable: true
  ipv6: false
  enhanced-mode: fake-ip
  fake-ip-range: 198.18.0.1/16
  use-hosts: true
  respect-rules: true
  default-nameserver:
  - 1.1.1.1
  - 8.8.8.8
  proxy-server-nameserver:
  - https://1.1.1.1/dns-query
  - https://dns.google/dns-query
  nameserver:
  - https://1.1.1.1/dns-query
  - https://dns.google/dns-query
  fallback:
  - https://1.0.0.1/dns-query
  - https://dns.google/dns-query
  fallback-filter:
    geoip: false
"@

$listenersBlock = @"
listeners:
- name: terminal-static
  type: mixed
  listen: 127.0.0.1
  port: 7895
  proxy: IPRoyal Exit
"@

$ruleBlock = @"
- PROCESS-NAME,codex.exe,IPRoyal Exit
- PROCESS-NAME,powershell.exe,IPRoyal Exit
- PROCESS-NAME,pwsh.exe,IPRoyal Exit
- PROCESS-NAME,cmd.exe,IPRoyal Exit
- PROCESS-NAME,WindowsTerminal.exe,IPRoyal Exit
- PROCESS-NAME,OpenConsole.exe,IPRoyal Exit
- PROCESS-NAME,bash.exe,IPRoyal Exit
- PROCESS-NAME,wsl.exe,IPRoyal Exit
- PROCESS-NAME,wslhost.exe,IPRoyal Exit
- PROCESS-NAME,curl.exe,IPRoyal Exit
- PROCESS-NAME,git.exe,IPRoyal Exit
- PROCESS-NAME,ssh.exe,IPRoyal Exit
- PROCESS-NAME,node.exe,IPRoyal Exit
- PROCESS-NAME,npm.exe,IPRoyal Exit
- PROCESS-NAME,pnpm.exe,IPRoyal Exit
- PROCESS-NAME,yarn.exe,IPRoyal Exit
- PROCESS-NAME,deno.exe,IPRoyal Exit
- PROCESS-NAME,python.exe,IPRoyal Exit
- PROCESS-NAME,python3.exe,IPRoyal Exit
- PROCESS-NAME,uv.exe,IPRoyal Exit
- PROCESS-NAME,Claude.exe,IPRoyal Exit
- PROCESS-NAME,cowork-svc.exe,IPRoyal Exit
- DOMAIN-KEYWORD,claude,IPRoyal Exit
- DOMAIN-KEYWORD,anthropic,IPRoyal Exit
- DOMAIN,anthropic.skilljar.com,IPRoyal Exit
- DOMAIN,api-iam.intercom.io,IPRoyal Exit
- DOMAIN,widget.intercom.io,IPRoyal Exit
- DOMAIN,nexus-websocket-a.intercom.io,IPRoyal Exit
- DOMAIN,browser-intake-us5.datadoghq.com,IPRoyal Exit
- DOMAIN,logs.browser-intake-us5.datadoghq.com,IPRoyal Exit
- DOMAIN,http-intake.logs.us5.datadoghq.com,IPRoyal Exit
"@

function Backup-IfExists([string]$path) {
  if (Test-Path $path) {
    Copy-Item $path "$path.bak-$stamp" -Force
  }
}

function Set-Utf8File([string]$path, [string]$value) {
  $dir = Split-Path -Parent $path
  if (-not (Test-Path $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
  }
  Set-Content -Path $path -Value $value -Encoding UTF8
}

function Update-ClashFile([string]$path) {
  $text = Get-Content -Raw $path
  $text = [regex]::Replace($text, '(?m)^mode:\s*global\s*$', 'mode: rule')

  if ($text -notmatch '(?ms)name: SOCKS5 63\.88\.218\.46:12324.*?dialer-proxy:') {
    $text = [regex]::Replace(
      $text,
      '(?ms)(- type: socks5\r?\n  name: SOCKS5 63\.88\.218\.46:12324\r?\n  server: 63\.88\.218\.46\r?\n  port: 12324\r?\n  username: .*?\r?\n  password: .*?\r?\n)',
      "`$1  dialer-proxy: RioLU.443 精靈學院`r`n"
    )
  }

  $text = [regex]::Replace(
    $text,
    '(?ms)^dns:\r?\n(?:^[ ].*\r?\n)+?(?=^tun:)',
    $dnsBlock + "`r`n"
  )

  if ($text -match '(?m)^listeners:') {
    $text = [regex]::Replace(
      $text,
      '(?ms)^listeners:\r?\n(?:^- .*\r?\n|^  .*\r?\n)+?(?=^proxies:)',
      $listenersBlock + "`r`n"
    )
  } else {
    $text = [regex]::Replace(
      $text,
      '(?ms)(^tun:\r?\n(?:^[ ].*\r?\n)+?^  enable: false\r?\n)',
      "`$1`r`n$listenersBlock`r`n"
    )
  }

  if ($text -notmatch 'PROCESS-NAME,codex\.exe,IPRoyal Exit') {
    $text = [regex]::Replace($text, '(?m)^rules:\s*$', "rules:`r`n$ruleBlock")
  }

  Set-Utf8File $path $text
}

Backup-IfExists $clash
Backup-IfExists $check
Backup-IfExists $verge
Backup-IfExists $dnsCfg
Backup-IfExists $rulesTpl
Backup-IfExists $mergeTpl
Backup-IfExists $proxyTpl
Backup-IfExists $settings

Update-ClashFile $clash
Copy-Item $clash $check -Force

$vergeText = Get-Content -Raw $verge
$vergeText = [regex]::Replace($vergeText, '(?m)^enable_dns_settings:\s*false\s*$', 'enable_dns_settings: true')
Set-Utf8File $verge $vergeText

$dnsCfgText = @"
# Clash Verge DNS Config

dns:
  enable: true
  listen: :53
  enhanced-mode: fake-ip
  fake-ip-range: 198.18.0.1/16
  fake-ip-filter-mode: blacklist
  prefer-h3: false
  respect-rules: true
  use-hosts: true
  use-system-hosts: false
  fake-ip-filter:
  - '*.lan'
  - '*.local'
  - '*.arpa'
  - localhost.ptlogin2.qq.com
  - '*.msftncsi.com'
  - www.msftconnecttest.com
  default-nameserver:
  - 1.1.1.1
  - 8.8.8.8
  nameserver:
  - https://1.1.1.1/dns-query
  - https://dns.google/dns-query
  fallback:
  - https://1.0.0.1/dns-query
  - https://dns.google/dns-query
  nameserver-policy: {}
  proxy-server-nameserver:
  - https://1.1.1.1/dns-query
  - https://dns.google/dns-query
  direct-nameserver: []
  direct-nameserver-follow-policy: false
  fallback-filter:
    geoip: false
hosts: {}
"@
Set-Utf8File $dnsCfg $dnsCfgText

$rulesTplText = @"
# Profile Enhancement Rules Template for Clash Verge

prepend:
  - PROCESS-NAME,codex.exe,IPRoyal Exit
  - PROCESS-NAME,powershell.exe,IPRoyal Exit
  - PROCESS-NAME,pwsh.exe,IPRoyal Exit
  - PROCESS-NAME,cmd.exe,IPRoyal Exit
  - PROCESS-NAME,WindowsTerminal.exe,IPRoyal Exit
  - PROCESS-NAME,OpenConsole.exe,IPRoyal Exit
  - PROCESS-NAME,bash.exe,IPRoyal Exit
  - PROCESS-NAME,wsl.exe,IPRoyal Exit
  - PROCESS-NAME,wslhost.exe,IPRoyal Exit
  - PROCESS-NAME,curl.exe,IPRoyal Exit
  - PROCESS-NAME,git.exe,IPRoyal Exit
  - PROCESS-NAME,ssh.exe,IPRoyal Exit
  - PROCESS-NAME,node.exe,IPRoyal Exit
  - PROCESS-NAME,npm.exe,IPRoyal Exit
  - PROCESS-NAME,pnpm.exe,IPRoyal Exit
  - PROCESS-NAME,yarn.exe,IPRoyal Exit
  - PROCESS-NAME,deno.exe,IPRoyal Exit
  - PROCESS-NAME,python.exe,IPRoyal Exit
  - PROCESS-NAME,python3.exe,IPRoyal Exit
  - PROCESS-NAME,uv.exe,IPRoyal Exit
  - PROCESS-NAME,Claude.exe,IPRoyal Exit
  - PROCESS-NAME,cowork-svc.exe,IPRoyal Exit
  - DOMAIN-KEYWORD,claude,IPRoyal Exit
  - DOMAIN-KEYWORD,anthropic,IPRoyal Exit
  - DOMAIN,anthropic.skilljar.com,IPRoyal Exit
  - DOMAIN,api-iam.intercom.io,IPRoyal Exit
  - DOMAIN,widget.intercom.io,IPRoyal Exit
  - DOMAIN,nexus-websocket-a.intercom.io,IPRoyal Exit
  - DOMAIN,browser-intake-us5.datadoghq.com,IPRoyal Exit
  - DOMAIN,logs.browser-intake-us5.datadoghq.com,IPRoyal Exit
  - DOMAIN,http-intake.logs.us5.datadoghq.com,IPRoyal Exit

append: []

delete: []
"@
Set-Utf8File $rulesTpl $rulesTplText

$mergeTplText = @"
# Profile Enhancement Merge Template for Clash Verge

dns:
  enable: true
  ipv6: false
  enhanced-mode: fake-ip
  fake-ip-range: 198.18.0.1/16
  use-hosts: true
  respect-rules: true
  default-nameserver:
    - 1.1.1.1
    - 8.8.8.8
  proxy-server-nameserver:
    - https://1.1.1.1/dns-query
    - https://dns.google/dns-query
  nameserver:
    - https://1.1.1.1/dns-query
    - https://dns.google/dns-query
  fallback:
    - https://1.0.0.1/dns-query
    - https://dns.google/dns-query
  fallback-filter:
    geoip: false

listeners:
  - name: terminal-static
    type: mixed
    listen: 127.0.0.1
    port: 7895
    proxy: IPRoyal Exit
"@
Set-Utf8File $mergeTpl $mergeTplText

$proxyTplText = @"
prepend:
  - type: 'socks5'
    name: 'SOCKS5 63.88.218.46:12324'
    server: '63.88.218.46'
    port: 12324
    username: '14a00462565ea'
    password: 'a1cb1edac3'
    dialer-proxy: 'RioLU.443 精靈學院'
append: []
delete: []
"@
Set-Utf8File $proxyTpl $proxyTplText

$json = Get-Content -Raw $settings | ConvertFrom-Json
if (-not $json.PSObject.Properties.Name.Contains('env')) {
  $json | Add-Member -NotePropertyName env -NotePropertyValue ([ordered]@{})
}
$json.env.HTTP_PROXY = 'http://127.0.0.1:7895'
$json.env.HTTPS_PROXY = 'http://127.0.0.1:7895'
$json.env.ALL_PROXY = 'http://127.0.0.1:7895'
$json.env.NO_PROXY = ''
$jsonText = $json | ConvertTo-Json -Depth 20
Set-Utf8File $settings $jsonText

[Environment]::SetEnvironmentVariable('HTTP_PROXY', 'http://127.0.0.1:7895', 'User')
[Environment]::SetEnvironmentVariable('HTTPS_PROXY', 'http://127.0.0.1:7895', 'User')
[Environment]::SetEnvironmentVariable('ALL_PROXY', 'http://127.0.0.1:7895', 'User')
[Environment]::SetEnvironmentVariable('NO_PROXY', $null, 'User')

$proc = Get-Process clash-verge -ErrorAction SilentlyContinue
if ($proc) {
  $proc | Stop-Process -Force
  Start-Sleep -Seconds 2
}

Start-Process 'C:\Program Files\Clash Verge\clash-verge.exe'
Start-Sleep -Seconds 8

Write-Output 'patched-and-restarted'
