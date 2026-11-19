# DraftflowAI Assisted Apply Chrome extension

This Manifest V3 extension is an assisted-application companion for DraftflowAI Jobs.

## What it does

- Runs in the candidate's own Chrome tab on supported ATS pages.
- Stores candidate details and the selected PDF resume only in Chrome session storage for the current browser session.
- Fills common contact fields and attaches the resume.
- Detects visible human-verification/CAPTCHA indicators and stops.
- Lets the candidate complete verification manually in the same tab.
- Re-checks required fields before enabling submission.
- Never attempts to solve or bypass CAPTCHA, MFA, login walls, or other access controls.

## Supported ATS in v0.1

- Greenhouse
- Lever
- Ashby

## Install locally for testing

1. Open Chrome Extensions: `chrome://extensions`.
2. Turn on **Developer mode**.
3. Choose **Load unpacked**.
4. Select the `chrome-extension` folder from this repository.
5. Open a supported application page.
6. Click the DraftflowAI extension icon.
7. Enter candidate details, choose a PDF resume, and save it for the current session.
8. Click **Fill application**.
9. If human verification appears, complete it manually in that same tab.
10. Click **Re-check after verification**.
11. Review the application. Use **Submit application** only when the extension reports that detected required fields are complete.

## Privacy

The test extension intentionally uses `chrome.storage.session`. It does not upload the resume to GitHub or DraftflowAI servers, and session data is cleared when the browser session ends.
