# Owner DevTools Reconnaissance Guide

**Written Stage 10 (2026-08-07).** For OEMs where the storefront is a
client-rendered JavaScript app and no static/API access has been found
(ASUS is the current, and highest-priority, example — see
`docs/OEM_ATLAS.md` §5-6), OEM Radar cannot answer one question by
itself: **does the frontend call a public data endpoint that a plain
HTTP fetch could also call?** A person with a real browser can answer
this in about 20-30 minutes. This guide is written for that person —
assume no engineering background beyond "I can open DevTools."

This is not a general scraping tutorial. It captures one specific thing:
the shape of a real request the site's own JavaScript makes to load
product data, so a developer can decide whether OEM Radar could make that
same request itself (no browser, no JavaScript execution, ever — see
"What this is NOT for" below).

## Before you start

- Use a normal, logged-out browser session — no account, no saved
  payment info, no logged-in state. Product listing pages don't require
  login; if a step below seems to ask you to log in, stop and note that
  instead.
- You do not need to understand what any of the captured data means.
  Capturing it correctly matters more than understanding it.
- Budget 20-30 minutes for one OEM.

## Step by step (ASUS example — the same steps apply to any OEM this
guide is used for)

1. Open a real ASUS laptop category page, e.g.
   `https://www.asus.com/us/laptops/`, in Chrome or Firefox.
2. Open DevTools (`F12`, or right-click → Inspect).
3. Click the **Network** tab.
4. In the filter bar, filter to **Fetch/XHR**. If the browser offers a
   **GraphQL** or **JSON** filter/preset, enable that too — you want to
   hide images, fonts, ads, and analytics beacons, not the data requests.
5. **Reload the page** (`Ctrl+R` / `Cmd+R`) with the Network panel open,
   so the initial data-loading requests are captured from the start.
6. With the panel still open and recording, interact with the page the
   way a real visitor would:
   - Change the product category or subcategory.
   - Change the sort order (price, newest, etc.).
   - Apply a filter (screen size, CPU, price range — whatever the site
     offers).
   - Go to page 2 of results, if the page paginates.
   - Click into one individual laptop's detail page.
7. Watch the Network panel while you do each of these. You're looking
   for requests where the **Response** tab shows JSON-shaped data (not
   HTML) containing things like:
   - a list of products
   - a SKU, model number, or product ID
   - a price
   - specs (CPU, RAM, screen size)
   - stock/availability status
8. When you find one or more requests like that, for **each one**,
   record (see "What to preserve" below):
   - the endpoint URL
   - the HTTP method (almost always `GET` or `POST`)
   - the query parameters (the `?key=value&...` part of the URL, or the
     **Payload**/**Request** tab if it's a `POST`)
   - the **Response** tab's Content-Type (should say `application/json`
     or similar)
   - the response body itself (right-click the request → Copy → Copy
     response, or Save as, or export the whole session as a HAR — see
     below)

If you go through all of steps 6-7 and never see a JSON response
containing real product data — only HTML documents and static assets —
that itself is a real, useful, complete result. Write that down too (see
"If you find nothing" below). It answers the question either way.

## What to preserve

- Endpoint URL
- HTTP method
- Query parameters / request payload shape
- Response Content-Type
- A representative response body (one example is enough — you don't need
  to capture every single request, just one or two that clearly carry
  real product data)

## What NOT to capture

**Never capture or share:**

- Cookies
- `Authorization` headers or any bearer/session tokens
- Any personal information (your name, address, account details, saved
  payment methods)

If you export a full HAR file (see below), it will likely contain these
by default — that's expected, and it's exactly what the sanitizer step
below removes before anything gets used.

## Exporting: two ways, pick whichever is easier

### Option A — export the whole session as a HAR file (recommended)

In the Network panel, right-click anywhere in the request list → **Save
all as HAR** (Chrome) or the equivalent export button (Firefox has a
"gear" icon → "Save All As HAR"). This captures everything the panel
recorded, which is fine — nothing needs to be pre-filtered by hand.

**Before this file goes anywhere else** (a doc, a chat message, a
fixture), it must be run through the sanitizer:

```bash
oem-radar sanitize-har path/to/your-export.har
```

This produces `your-export.sanitized.har` with cookies, `Authorization`/
CSRF/API-key headers, bearer tokens, and session-shaped query
parameters/JSON fields redacted. Review the sanitized file yourself
before handing it off anyway — the sanitizer targets known-sensitive
shapes, it is not a guarantee that nothing sensitive survived.

### Option B — copy individual requests by hand

If exporting a full HAR feels like too much, right-click just the
specific request(s) that showed real product data → **Copy** → **Copy as
fetch** (or **Copy as cURL**, or **Copy response**). Paste each into a
plain text file. This is simpler but only captures what you explicitly
copy — make sure you get the endpoint URL, method, and one real response
body.

## A simple bundle format (optional — use if it's easier than one big file)

```
owner_probes/
  asus/
    README.txt       — one line: OEM name, date, page(s) visited
    endpoint.txt      — the URL(s) found
    request.json      — method + query params / payload shape
    response.json      — one representative sanitized response body
    notes.md          — anything else worth mentioning
```

This structure is a convenience, not a requirement — a single sanitized
HAR file (Option A above) is just as usable. Don't spend time forcing
data into this shape if it doesn't fit naturally.

## If you find nothing

Write down, in plain language:

- Which category/product pages you visited
- What the Network panel showed (e.g. "every request was either an HTML
  document, an image, or a script — no JSON response ever contained
  product data")

This is a complete, valuable result — it means the site's data genuinely
only exists inside rendered JavaScript, which OEM Radar will record as
`BLOCKED_JS` with real evidence behind it, rather than a guess.

## What this is NOT for

This guide produces evidence for a **human decision**, not an automation
trigger. Finding a real endpoint does not mean OEM Radar will
automatically start using it — a developer still evaluates whether an
existing engine can consume it, whether it needs new discovery-only
support, or (only after **three** independently-confirmed OEMs show the
same API shape) whether a new reusable engine is warranted. This project
does not execute JavaScript to render a page, and this guide does not
change that — you are the one opening the browser, not OEM Radar.
