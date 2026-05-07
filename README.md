# Baidu Tieba Browser Signer

基于 [1dyer/Tieba_auto_sign](https://github.com/1dyer/Tieba_auto_sign) 的浏览器 Cookie 签到思路重写和优化的百度贴吧自动签到脚本。  
This project is inspired by [1dyer/Tieba_auto_sign](https://github.com/1dyer/Tieba_auto_sign), with a rewritten browser-based implementation for GitHub Actions.

---

## 简体中文

### 这个项目做什么

这是一个适合 GitHub Actions 运行的百度贴吧每日自动签到工具。公开仓库只放脚本和说明，真正包含 Cookie 的 Action 仓库建议设为 private。

本项目保留了参考项目“导出浏览器 Cookie，然后在 GitHub Actions 里用浏览器签到”的思路，但做了这些调整：

- 去掉 Server 酱通知功能，避免额外第三方出口。
- 不依赖 BDUSS API 登录校验，优先使用浏览器 Cookie 方式。
- 通过旧版关注列表页读取真实尾页页码，不限制 39 个，默认最多扫描 100 页，可配置。
- 签到点击加入随机等待，默认每个吧间隔 2 到 4 秒。
- 签到按钮使用多套选择器，兼容更多贴吧页面结构。
- 兼容新版贴吧页面的 `.follow-sign` 签到按钮和“连签”状态。
- 支持 UTF-8 和 GBK 贴吧名解码，减少日志乱码。
- GitHub Actions 输出签到摘要到 Step Summary。

### 推荐仓库结构

建议准备两个仓库：

- public 仓库：上传本项目代码，不能放 Cookie。
- private 仓库：只放 GitHub Actions workflow，并在 Secrets 里保存 Cookie。

### 本地导出 Cookie

先安装依赖：

```bash
python -m pip install -r requirements.txt
```

运行 Cookie 导出工具：

```bash
python -m scripts.export_cookies
```

或者安装为命令后运行：

```bash
python -m pip install .
baidu-tieba-export-cookies
```

浏览器打开后登录百度贴吧，登录完成回到终端按回车。程序会生成 `tieba_cookies.json`。把整个 JSON 文件内容复制到 private Action 仓库的 Secret。

不要把 `tieba_cookies.json` 上传到 public 仓库。

### private Action 仓库怎么设置

在 private 仓库创建：

```text
.github/workflows/baidu-tieba-signin.yml
```

workflow 可以参考本项目配套的 action 文件夹。

然后进入 private 仓库：

```text
Settings -> Secrets and variables -> Actions -> Secrets -> New repository secret
```

添加：

```text
Name: TIEBA_COOKIES
Secret: tieba_cookies.json 的完整内容
```

可以直接粘贴多行格式的完整 JSON。  
如果有多个账号，请用 `###` 分隔多个完整 JSON，不要只用换行分隔。

### 可选 Variables

在：

```text
Settings -> Secrets and variables -> Actions -> Variables
```

可以添加这些变量：

| 名称 | 默认值 | 说明 |
| --- | --- | --- |
| `TIEBA_MAX_PAGES` | `100` | 最多扫描多少页关注贴吧列表。 |
| `TIEBA_MAX_FORUMS` | `0` | 最多签到多少个贴吧，`0` 表示不限制。 |
| `TIEBA_INTERVAL_SECONDS` | `2-4` | 每个贴吧之间的等待秒数。可以写固定值 `2`，也可以写随机范围 `2-4`。 |
| `TIEBA_SIGN_RETRIES` | `2` | 每个贴吧找按钮或点击失败时最多尝试次数。 |
| `TIEBA_EMPTY_PAGES_TO_STOP` | `1` | 连续多少个空列表页后停止扫描。默认遇到第一个空关注列表页就停止，减少无效翻页。 |

如果你在 Variables 里手动设置了同名变量，Variables 会覆盖 workflow 里的默认值。例如 `TIEBA_INTERVAL_SECONDS` 如果还显示 `3-8`，请把这个 Variable 改成 `2-4` 或删除它。

### 手动运行

在 private 仓库：

```text
Actions -> Baidu Tieba Sign In -> Run workflow
```

运行完成后看：

```text
Actions run -> Summary
```

### 注意

- Cookie 有效期取决于百度账号状态，失效后需要重新导出。
- 如果签到过快容易失败，请把 `TIEBA_INTERVAL_SECONDS` 调大，例如 `6-15`。
- 如果贴吧很多，请调大 `TIEBA_MAX_PAGES`，并给 workflow 保留足够时间。
- public 仓库不要上传 Cookie、截图里的 Cookie 或 Action Secret。

---

## 繁體中文

### 這個專案做什麼

這是一個適合在 GitHub Actions 執行的百度貼吧每日自動簽到工具。公開倉庫只放腳本與說明，真正包含 Cookie 的 Action 倉庫建議設為 private。

本專案參考了原專案「匯出瀏覽器 Cookie，然後在 GitHub Actions 裡用瀏覽器簽到」的思路，但重新整理了實作：

- 移除 Server 醬通知功能，減少第三方出口。
- 不依賴 BDUSS API 登入檢查，優先使用瀏覽器 Cookie。
- 透過舊版關注列表頁讀取真實尾頁頁碼，不限制 39 個，預設最多掃描 100 頁，可自行設定。
- 簽到點擊加入隨機等待，預設每個吧間隔 2 到 4 秒。
- 使用多組簽到按鈕選擇器，提高相容性。
- 相容新版貼吧頁面的 `.follow-sign` 簽到按鈕與「連簽」狀態。
- 支援 UTF-8 和 GBK 貼吧名稱解碼，減少日誌亂碼。
- GitHub Actions 會輸出簽到摘要到 Step Summary。

### 使用方式

先在本地安裝依賴並匯出 Cookie：

```bash
python -m pip install -r requirements.txt
python -m scripts.export_cookies
```

登入完成後，將產生的 `tieba_cookies.json` 完整內容複製到 private Action 倉庫的 `TIEBA_COOKIES` Secret。可以直接貼上多行 JSON；如果有多個帳號，請用 `###` 分隔多個完整 JSON。

不要將 `tieba_cookies.json` 上傳到公開倉庫。

### 可選參數

| 名稱 | 預設值 | 說明 |
| --- | --- | --- |
| `TIEBA_MAX_PAGES` | `100` | 最多掃描多少頁關注貼吧列表。 |
| `TIEBA_MAX_FORUMS` | `0` | 最多簽到多少個貼吧，`0` 表示不限。 |
| `TIEBA_INTERVAL_SECONDS` | `2-4` | 每個貼吧之間等待秒數，可用固定值或隨機範圍。 |
| `TIEBA_SIGN_RETRIES` | `2` | 每個貼吧失敗時最多重試次數。 |
| `TIEBA_EMPTY_PAGES_TO_STOP` | `1` | 連續多少個空列表頁後停止掃描。預設遇到第一個空關注列表頁就停止。 |

---

## English

### What This Project Does

This is a Baidu Tieba daily sign-in tool designed for GitHub Actions. Keep this code in a public repository, and keep your workflow repository private because it stores your Cookie in GitHub Secrets.

The project is based on the browser-cookie idea from [1dyer/Tieba_auto_sign](https://github.com/1dyer/Tieba_auto_sign), but the implementation has been rewritten with several changes:

- Removed ServerChan notification support to avoid extra third-party traffic.
- Uses browser cookies instead of relying on BDUSS API login checks.
- Reads the old followed-forum list tail page and scans beyond the old 39-forum limitation.
- Adds configurable random delays between forums.
- Uses multiple sign-button selectors for better page compatibility.
- Supports the newer `.follow-sign` button and streak sign-in state.
- Supports UTF-8 and GBK forum-name decoding.
- Writes a GitHub Actions Step Summary after each run.

### Export Cookies Locally

```bash
python -m pip install -r requirements.txt
python -m scripts.export_cookies
```

After logging in, copy the full content of `tieba_cookies.json` into your private workflow repository as the `TIEBA_COOKIES` secret. Multi-line JSON is supported. For multiple accounts, separate full JSON blocks with `###`.

Never commit `tieba_cookies.json` to a public repository.

### GitHub Actions Variables

| Name | Default | Description |
| --- | --- | --- |
| `TIEBA_MAX_PAGES` | `100` | Max followed-forum pages to scan. |
| `TIEBA_MAX_FORUMS` | `0` | Max forums to sign. `0` means unlimited. |
| `TIEBA_INTERVAL_SECONDS` | `2-4` | Delay between forums. Supports fixed values or ranges. |
| `TIEBA_SIGN_RETRIES` | `2` | Retry count per forum. |
| `TIEBA_EMPTY_PAGES_TO_STOP` | `1` | Stop after this many empty followed-forum pages. |

### License and Attribution

This project is not a direct copy of the reference repository. It is a rewritten implementation based on the same browser-cookie sign-in approach, with attribution to [1dyer/Tieba_auto_sign](https://github.com/1dyer/Tieba_auto_sign).
