# Mobile assisted apply — staged provider prototype

No Chrome extension is needed for an interactive hosted browser. Steel is an optional provider; its Launch plan advertises one-time credits, not unlimited free usage. The adapter is not yet called by the production worker and never submits. It never enables CAPTCHA solving, proxies, stealth, session recording, or profile persistence.

## Setup and test

1. Create a Steel project and project-scoped API key at https://app.steel.dev/settings/api-keys.
2. Store the key as GitHub Actions repository secret STEEL_API_KEY. Do not paste it into chat, frontend code or commits.
3. Run Mobile browser handoff prototype with live_smoke enabled once. The smoke test uses a synthetic form, reconnects and verifies state, and releases the browser without logging capability URLs; it consumes provider credits.
4. Implement and verify owner-only session storage, authenticated handoff and explicit per-candidate third-party data processing consent before enabling real applications.
5. Only then test the interactive viewer on mobile using a fresh supported job and verify a genuine employer confirmation.

## Proposed production lifecycle

Cloud browser created before filling → fill known answers and attach resume where safe → pause at verification or unresolved fields → owner-only Continue application link → user controls the same live browser and submits → reconcile genuine email / portal evidence → release. Active challenges can interrupt prefill; never promise all fields were completed. An expired session cannot retain unsaved form values: start a new prefill only when requested, not a duplicate submission.

The viewer URL is a short-lived bearer capability. Never log it or expose it in public build artifacts; use owner-specific authorization, separate session records, strict expiry, and release on completion. No automatic attempt for the same job while a handoff is active. Provider credentials, session data and resume must never be public. Mobile user interaction is unverified until the live test.
