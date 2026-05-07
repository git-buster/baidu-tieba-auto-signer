# Project Summary For Handoff

This file is a safe handoff note for another AI or maintainer. It intentionally contains no cookies, tokens, BDUSS values, GitHub PATs, or private user data.

## User Goal

Build a Baidu Tieba daily auto sign-in tool that can run on GitHub Actions.

The user wants two GitHub repositories:

- Public repository: code and documentation only, no private data.
- Private repository: GitHub Actions workflow and repository Secrets/Variables.

The local workspace is:

```text
C:\Users\wu\Desktop\script\baidu
```

The intended local folder layout is:

```text
baidu/
  action/   private workflow repository content
  public/   public package repository content
  source/   downloaded reference source project
```

## GitHub Repositories

Public repository:

```text
https://github.com/git-buster/baidu-tieba-auto-signer
```

Private action repository:

```text
git-buster/baidu-tieba-signer
```

The private repository may not be visible through some GitHub connector tools, but local `git push` has worked.

## Reference Project

The implementation is inspired by:

```text
https://github.com/1dyer/Tieba_auto_sign
```

The user downloaded that project under the local `source` folder. The new project should not directly copy it wholesale. It uses the same broad idea:

1. Export logged-in browser cookies.
2. Save those cookies as a GitHub Secret.
3. Use a headless Chromium browser in GitHub Actions to visit Tieba and sign in.

The reference project had issues or limitations:

- It used old Tieba selectors such as `#signstar_wrapper` and `.j_signbtn`.
- It may fail on newer Tieba pages.
- It used ServerChan notification. The user requested removing that feature.
- Some users reported partial signing or limits such as about 39 forums.
- It clicked quickly and could be brittle.

## Current Public Package

Important files:

```text
public/pyproject.toml
public/requirements.txt
public/README.md
public/BROWSER_DEBUG.md
public/PROJECT_SUMMARY.md
public/scripts/tieba_signer.py
public/scripts/export_cookies.py
public/tests/test_tieba_signer.py
```

Console scripts:

```text
baidu-tieba-auto-signer = scripts.tieba_signer:main
baidu-tieba-export-cookies = scripts.export_cookies:main
```

Dependencies:

```text
DrissionPage==4.1.0.18
beautifulsoup4==4.12.3
```

## Current Private Workflow

Important file:

```text
action/.github/workflows/baidu-tieba-signin.yml
```

The workflow installs the public package from:

```text
git+https://github.com/git-buster/baidu-tieba-auto-signer.git@main
```

Required GitHub Secret in the private action repository:

```text
TIEBA_COOKIES
```

Optional GitHub Variables:

```text
TIEBA_MAX_PAGES
TIEBA_MAX_FORUMS
TIEBA_INTERVAL_SECONDS
TIEBA_SIGN_RETRIES
TIEBA_EMPTY_PAGES_TO_STOP
```

Current default values:

```text
TIEBA_MAX_PAGES = 100
TIEBA_MAX_FORUMS = 0
TIEBA_INTERVAL_SECONDS = 2-4
TIEBA_SIGN_RETRIES = 2
TIEBA_EMPTY_PAGES_TO_STOP = 1
```

If the Action log still shows `TIEBA_INTERVAL_SECONDS: 3-8`, that is because the private repository has an old Variable overriding the workflow default. Update or delete that Variable.

## Cookie Format

The expected `TIEBA_COOKIES` value is the full JSON exported by DrissionPage, usually an array of objects like:

```json
[
  {
    "name": "BDUSS",
    "value": "...",
    "domain": ".baidu.com",
    "path": "/"
  }
]
```

Do not commit `tieba_cookies.json` to the public repository.

Multi-line JSON is supported. For multiple accounts, separate complete JSON blocks with:

```text
###
```

## Important Debugging Findings

### New Tieba Forum Page

The current Tieba forum page no longer always uses old selectors like:

```text
#signstar_wrapper
.j_signbtn
```

During live browser debugging, the user opened:

```text
https://tieba.baidu.com/f?kw=...
```

The visible new UI sign button was:

```text
.button-wrapper.operate-btn.follow-sign
```

Before signing, the text was:

```text
签到
```

After successful click, the text became:

```text
连签1天
```

The script now supports:

- New `.follow-sign` button.
- Old `.j_signbtn` / `#signstar_wrapper` selectors.
- Treating `连签`, `连续`, and `已签到` as signed states.
- A JS event-click fallback for Vue-style buttons.

### Followed Forum List

The user can switch Tieba to old UI and open:

```text
https://tieba.baidu.com/i/i/forum
```

This page contains the followed forum list in:

```text
#like_pagelet table tbody tr
```

Each followed forum is in the first column. Links look like:

```text
/f?kw=%C3%F7%D4%C2%D7%AF%D6%F7
```

The encoding can be GBK percent-encoding, so the script supports both UTF-8 and GBK/GB18030 decoding.

The page also has pagination links. The user saw a tail page link like:

```text
/i/i/forum?&pn=6
```

That `6` is not fixed. It is only the current user's example. The script should dynamically read the current account's `尾页` link and parse `pn=...` to determine the real total page count.

Current implementation:

- Opens page 1 of the old followed list.
- Parses the max `pn` from `#like_pagelet a[href*=pn]`.
- Scans only up to that dynamic total page count, capped by `TIEBA_MAX_PAGES`.
- Stops after empty pages according to `TIEBA_EMPTY_PAGES_TO_STOP`.

## Local Browser Debugging

See:

```text
public/BROWSER_DEBUG.md
```

Key points:

- Launch Chrome with `--remote-debugging-port=18888`.
- Use a separate user data directory.
- If Chrome rejects WebSocket connections, add `--remote-allow-origins=*` or use `websocket.create_connection(..., suppress_origin=True)`.
- The user's environment had `http_proxy` pointing at `127.0.0.1:18888`, which caused confusion because `127.0.0.1:18888` was also used as a proxy. Use `localhost:18888` and clear proxy env vars for debugging.
- Do not print cookies.

## Current Verification

The latest local checks before this handoff:

```text
python -m pytest tests
python -m compileall .
```

Tests passed. Sensitive scans were run for obvious patterns such as GitHub PATs, BDUSS, STOKEN, BAIDUID, and ServerChan strings.

## Things To Be Careful About

- Never include the user's pasted cookies or tokens in code, README, summaries, commits, or logs.
- Do not add ServerChan, Discord, Telegram, or other notification integrations unless the user explicitly asks.
- Do not upload `tieba_cookies.json` to the public repo.
- The private Action repo should stay private.
- If the workflow seems to use old variable values, check GitHub Actions Variables. Variables override defaults in workflow YAML.
- GitHub Actions install step uses public repo `main`, so changes to `public` are enough for code behavior changes.

## Likely Next Steps

1. Re-run the GitHub Action after pushing the latest public repo changes.
2. Confirm the log says something like:

```text
Followed forum list reports N page(s); scanning N.
```

3. Confirm forum scanning stops at the real tail page.
4. Confirm signing uses `.follow-sign` successfully on new Tieba pages.
5. If a specific forum still fails, debug that page live using `BROWSER_DEBUG.md`.
