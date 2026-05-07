# Browser Debugging Notes

这份文档记录如何用前台 Chrome 登录百度贴吧，然后让脚本或调试程序接管浏览器分析页面结构。不要在日志里打印 Cookie。

## 1. 打开可调试 Chrome

Windows PowerShell:

```powershell
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$profile = "C:\Users\wu\Desktop\script\baidu\debug-chrome-profile"
New-Item -ItemType Directory -Force -Path $profile | Out-Null
Start-Process -FilePath $chrome -ArgumentList @(
  "--remote-debugging-port=18888",
  "--remote-allow-origins=*",
  "--user-data-dir=$profile",
  "--no-first-run",
  "--no-default-browser-check",
  "https://tieba.baidu.com/"
)
```

如果你已经开了浏览器但接管失败，确认 18888 是 Chrome DevTools，不是代理：

```powershell
Invoke-WebRequest -UseBasicParsing http://localhost:18888/json/version
```

返回里应该能看到 `Browser: Chrome/...`。

## 2. 本机代理注意事项

如果系统里有：

```text
http_proxy=http://127.0.0.1:18888
```

那么 `127.0.0.1:18888` 可能会被当成代理端口，导致 DrissionPage 或 curl 接错对象。调试时建议临时清空：

```powershell
$env:http_proxy=""
$env:https_proxy=""
$env:HTTP_PROXY=""
$env:HTTPS_PROXY=""
$env:NO_PROXY="localhost,127.0.0.1,::1"
```

## 3. 查看当前标签页

```powershell
$env:PYTHONIOENCODING="utf-8"
@'
import json, requests
s = requests.Session()
s.trust_env = False
tabs = s.get("http://localhost:18888/json/list", timeout=5).json()
print(json.dumps(
    [{k: tab.get(k) for k in ("type", "title", "url", "webSocketDebuggerUrl")} for tab in tabs],
    ensure_ascii=False,
    indent=2,
))
'@ | python -
```

## 4. 读取页面 DOM

下面例子会读取当前打开的贴吧页面，寻找新版签到按钮。

```powershell
$env:PYTHONIOENCODING="utf-8"
@'
import json, itertools, requests, websocket

s = requests.Session()
s.trust_env = False
tabs = s.get("http://localhost:18888/json/list", timeout=5).json()
tab = next(t for t in tabs if t.get("type") == "page" and "tieba.baidu.com/f?" in t.get("url", ""))

ws = websocket.create_connection(
    tab["webSocketDebuggerUrl"],
    timeout=10,
    suppress_origin=True,
    http_proxy_host=None,
    http_proxy_port=None,
)
counter = itertools.count(1)

def cdp(method, params=None):
    msg = {"id": next(counter), "method": method}
    if params is not None:
        msg["params"] = params
    ws.send(json.dumps(msg))
    while True:
        data = json.loads(ws.recv())
        if data.get("id") == msg["id"]:
            return data

expr = r'''
(() => {
  const visible = el => {
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
  };
  const buttons = [...document.querySelectorAll('.follow-sign, .operate-btn')]
    .filter(el => visible(el))
    .map(el => ({class: String(el.className || ''), text: (el.innerText || '').trim()}));
  return JSON.stringify({url: location.href, title: document.title, buttons});
})()
'''

result = cdp("Runtime.evaluate", {"expression": expr, "returnByValue": True})
print(result["result"]["result"]["value"])
ws.close()
'@ | python -
```

## 5. 本次调试结论

新版贴吧页面的签到按钮不是老版的：

```text
#signstar_wrapper
.j_signbtn
```

而是：

```text
.button-wrapper.operate-btn.follow-sign
```

未签到时按钮文字是：

```text
签到
```

点击成功后会变成：

```text
连签1天
```

旧版关注列表页仍然可用：

```text
https://tieba.baidu.com/i/i/forum
```

它的结构是：

```text
#like_pagelet table tbody tr
```

每个关注贴吧在表格行第一列，链接类似：

```text
/f?kw=%C3%F7%D4%C2%D7%AF%D6%F7
```

分页里有“尾页”链接，例如当前调试账号看到的是：

```text
/i/i/forum?&pn=6
```

这个 `6` 不是写死的。脚本会在每次运行时读取当前登录账号第一页里的“尾页”链接，从 `pn=...` 动态解析真实总页数，再按真实页数扫描关注贴吧。
