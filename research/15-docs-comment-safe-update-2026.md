<!-- ABOUTME: Research spike on updating a Google Doc body while preserving anchored reviewer comments. -->
<!-- ABOUTME: Web research against Google primary sources plus a live test on a throwaway files.copy, dated 2026-06-21. -->

# Updating a Google Doc body while preserving anchored comments

## Verification Method

This is a mix of (1) web research against Google primary sources and (2) a live,
non-destructive test run against a throwaway `files.copy` duplicate. Dated
2026-06-21.

The two real documents were never mutated. The only writes happened on a
throwaway copy named "ZZ-THROWAWAY WIB doc1 comment-test DELETE ME"
(`1sF76R6GRZ9AiBEAmuVh9b-BmLcLOVKFwJc_qusMTV9Y`), which was trashed at the end
of the test (Drive returned HTTP 204 on delete). The OAuth access token used for
the test was exported to a temp file and deleted afterward.

Live access used the `gog` CLI account `michaelrishiforrester@gmail.com`, which
owns both target docs. The token carried both the `documents` and `drive`
scopes (confirmed via the OAuth2 tokeninfo endpoint).

API version strings, as published by Google at the time of writing:

- Google Docs API: `v1` (Java client artifact `v1-rev20260427-2.0.0`).
- Google Drive API: `v3` (Java client artifact `drive-rev20251210-2.0.0`).

Primary sources consulted:

- Manage comments and replies (Drive API): https://developers.google.com/workspace/drive/api/guides/manage-comments
- Comment resource reference (Drive API v3): https://developers.google.com/workspace/drive/api/reference/rest/v3/comments
- files.copy reference (Drive API v3): https://developers.google.com/workspace/drive/api/reference/rest/v3/files/copy
- Upload file data (Drive API): https://developers.google.com/drive/api/guides/manage-uploads
- documents.batchUpdate reference (Docs API v1): https://developers.google.com/workspace/docs/api/reference/rest/v1/documents/batchUpdate
- Insert, delete, and move text (Docs API how-to): https://developers.google.com/workspace/docs/api/how-tos/move-text
- Workspace Updates blog, "Copy comments and suggestions in Docs, Sheets, and Slides" (2017): https://workspaceupdates.googleblog.com/2017/11/copy-comments-and-suggestions-in-docs.html

## The single most important finding

The widely assumed model ("media-PATCH overwrite destroys comments, surgical
batchUpdate preserves them") is wrong at the data layer. In the live test, the
comment resource survived BOTH a full media-PATCH overwrite AND a
`deleteContentRange` that deleted the exact text the comment quoted. In every
case the comment stayed in the Drive comments collection, was not flagged
`deleted`, and kept its `quotedFileContent` and its replies.

What actually varies is whether the Docs editor UI still draws the comment
attached to a highlighted span, or shows it as orphaned ("Original content
deleted" / moved into the resolved/orphaned tray). That is a UI rendering
question, not a data-loss question. The comment thread, its author, its text,
and its replies are not lost by either method at the API level.

This reframes the whole task. The risk is not "the comment object disappears."
The risk is "the comment becomes visually orphaned and stops pointing at the
right sentence, so reviewers cannot tell what it referred to."

## Live test results (on the throwaway copy)

Setup: `files.copy` of doc1 to a throwaway, then exercised against it.

1. files.copy does NOT carry comments. The Drive API copy produced a doc with
   the full body but 0 comments. The "Copy comments and suggestions" toggle is a
   UI-only feature (File > Make a copy). There is no `copyComments` parameter on
   the `files.copy` REST method. Confirmed: the copied doc returned
   `comments: []`.

2. To test preservation we then created an anchored comment on the copy via the
   Drive API (`comments.create` with an `anchor` JSON string and a
   `quotedFileContent.value`). Drive accepted and stored the anchor string.

3. deleteContentRange over the anchored span. A `batchUpdate` with
   `deleteContentRange` covering the entire quoted paragraph (indices 1..185) ran
   successfully. After it, the comment still existed, `deleted=false`, and
   `quotedFileContent` was unchanged. The comment object was not removed.

4. media-PATCH full overwrite. A
   `PATCH /upload/drive/v3/files/{id}?uploadType=media` with
   `Content-Type: text/markdown` replaced the entire body (verified: the
   exported text became only the new markdown). After it, the comment STILL
   existed, `deleted=false`, `quotedFileContent` unchanged. The body was
   replaced but the comment object persisted.

Conclusion from the live test: at the Drive data layer neither operation
deletes comments. Confirmed for API-created comments. What could NOT be
measured headlessly is how the Docs editor UI renders each comment's anchor
after each operation (anchored vs orphaned). That requires a human opening the
doc, and it is the open item that the safe test plan below covers.

## Answers to the specific questions

### 1. How comments are anchored, and what "orphaned" means

Per the Drive "Manage comments and replies" guide, a comment is either anchored
or unanchored. An anchored comment is "associated with a specific location, such
as a sentence in a word-processing document, within a specific version of a
document." The anchor lives in the Comment resource's `anchor` field, which the
reference defines as "A region of the document represented as a JSON string."
The guide's own example uses a `region` object with a `line` and a `rev`
(`'head'` for the latest revision).

Two load-bearing statements from the guide:

- "Anchors are immutable, and their position relative to the content of a
  document cannot be guaranteed between revisions."
- "We recommend you use anchors in documents where the position doesn't change,
  such as image files or read-only documents."

And the decisive one for Workspace files: Google Workspace editor apps (Docs,
Sheets, Slides) "treat these comments as un-anchored comments." That is, the
`anchor` field you set through the API is saved but is not what the Docs editor
uses to render the highlight.

This is confirmed by the live data. Listing the 18 real comments on doc1 and the
2 on doc2 (read-only), NONE returned an `anchor` field, but 17 of 18 (doc1) and
2 of 2 (doc2) returned `quotedFileContent.value`. The native Docs UI anchors are
NOT surfaced as Drive `anchor` strings at all. The only machine-readable handle
the API gives you for "what text this comment is about" is
`quotedFileContent.value`, which is the snapshot of the quoted text, not a live
range.

"Orphaned" therefore means: the Docs editor can no longer find the span its
internal (kix) anchor pointed at, because that text was edited or deleted, so it
moves the comment to the orphaned/resolved area instead of highlighting a
sentence. The comment data still exists; it just stops pointing at live text.

What happens to the anchored span specifically:

- If the anchored text is deleted, the Docs UI orphans the comment (the thread
  survives, the highlight does not). The API still lists the comment.
- If text around it changes but the anchored span itself survives unedited, the
  Docs editor keeps the comment attached to that span. This is the behavior we
  want to exploit, but it depends on the editor's internal anchor, which the API
  does not expose and the live test could not directly observe headlessly.

### 2. Does batchUpdate preserve anchored comments for text that is not deleted?

At the data layer: the comment objects are never dropped by batchUpdate
(confirmed live, even when the quoted text was deleted). batchUpdate operates on
the same persistent document object and the same file ID, so file-level
attachments (comments, permissions, links, bookmarks) are retained. This is the
fundamental advantage over delete-and-recreate, which loses the file ID and
everything attached to it.

For the editor's internal anchor specifically: Google does not document
batchUpdate's effect on comment anchors. The reasonable, and standard,
expectation is that the Docs editor's anchor logic behaves the same whether a
human or the API edits the text: untouched spans keep their comments attached,
deleted spans orphan their comments. This is CONSISTENT with how Docs handles
live human editing, but it is NOT stated in Google's API docs and must be
eyeballed on a copy (see safe test plan). The `documents.batchUpdate` reference
says nothing about comments either way.

So: yes, surgical range-based edits on the same document object are the right
mechanism, and yes, you should avoid deleting any span that carries a comment.
The catch is that the API will not tell you which spans those are as live
ranges. You only get `quotedFileContent.value` (a text snapshot) to match
against.

### 3. Safest method to bring the body up to date, ranked

Ranking, safest first:

Rank 1 (RECOMMENDED). Surgical batchUpdate on the same document, never
deleting any span that carries a comment.
- Use the same file ID, so all 18 / 2 comments stay attached.
- Build the edit as targeted `replaceAllText`, `insertText`, and
  `deleteContentRange` requests that touch only changed regions.
- Before editing, list comments with `quotedFileContent` and treat each quoted
  string as a no-delete zone. Edit around them. Prefer inserting new/corrected
  content adjacent to a quoted span rather than replacing the quoted span
  itself.
- Tradeoff: more work to compute the diff; raw markdown inserted via insertText
  lands as literal markdown characters, not formatted headings/bold/tables. If
  formatting matters you must translate markdown to Docs styling requests
  (UpdateParagraphStyle, UpdateTextStyle, CreateParagraphBullets, InsertTable),
  which is substantial. For a runbook doc that is mostly prose this is usually
  acceptable.

Rank 2. "Don't touch anchored text" append/insert-only.
- A strict subset of Rank 1: only insert new sections and edit regions that
  carry no comment; never call deleteContentRange on a quoted span.
- This is the surest way to keep every comment visually anchored, at the cost of
  leaving stale sentences in place (you cannot rewrite a sentence that a comment
  quotes without risking that comment's anchor).
- There is no API call that returns "live ranges currently carrying anchored
  comments" for a Workspace doc. The only mapping available is:
  `comments.list` gives `quotedFileContent.value` (a text snapshot) which you
  string-match against the text you get from `documents.get`. That match is
  best-effort, since the quoted snapshot can be stale or appear multiple times.

Rank 3 (BASELINE, what to STOP doing for these docs). Drive media-PATCH
overwrite.
- Confirmed: per Google's upload guide, "When you upload and convert media
  during an update request to a Docs, Sheets, or Slides file, the full contents
  of the document are replaced." Confirmed live: the body was fully replaced.
- Surprising live finding: the comment objects survived the overwrite at the
  data layer (not deleted, replies intact, quotedFileContent intact). So
  media-PATCH does NOT destroy the comment threads.
- BUT: it replaces 100% of the body, so every editor anchor is invalidated and
  every comment will render as orphaned ("Original content deleted") in the Docs
  UI. The threads survive but nobody can tell which sentence each referred to
  except via the quoted-text snapshot. For 18 carefully placed reviewer comments
  this is unacceptable, which matches the concern in the task. Do not use this
  for these two docs.

Rank 4 (do not use). Delete-and-recreate, or any path that changes the file
ID. Loses the file ID and therefore all comments, permissions, and links.
Discard outright.

On the revisions / keepRevisionForever angle: revisions are body snapshots; they
are not a comment-preservation mechanism. Restoring or copying a revision does
not re-anchor comments. `keepRevisionForever` only pins a binary revision so it
is not garbage-collected. It is worth setting on a known-good revision before you
edit, purely as a rollback insurance policy, not as a comment-preservation tool.

### 4. Non-destructive test before doing it for real

files.copy via the API does not copy comments (confirmed live: copy had 0
comments). So an API copy is useless for testing comment preservation.

To get a copy that retains the original anchored comments you must use the Docs
UI: File > Make a copy, and tick "Copy comments and suggestions." That UI copy
carries the comments (per the 2017 Workspace Updates announcement). Run all
destructive experiments on that UI copy, then open it in the browser to eyeball
how the anchors render after each edit. This is the only way to confirm the
UI-anchor behavior that the API does not expose. See the safe test plan.

### 5. Rate limits, scopes, markdown round-trip

- Scopes. The full-access `https://www.googleapis.com/auth/drive` scope covers
  comments.list / files.copy / files media-PATCH. Docs batchUpdate needs
  `https://www.googleapis.com/auth/documents`. The token in use carries both
  (verified live via tokeninfo). The narrow `drive.file` scope only grants
  access to files the app created or the user opened with it, so it is the wrong
  scope for editing pre-existing docs you did not create through this app; use
  full `drive` + `documents`.
- Rate limits. batchUpdate is a single atomic call; batch many requests into one
  call rather than many small calls. Docs and Drive enforce per-minute,
  per-user quotas (HTTP 429 / 403 rateLimitExceeded). For a one-shot runbook
  update this is a non-issue; just retry with backoff on 429.
- Markdown round-trip. Inserting markdown text via insertText stores the literal
  markdown characters, not formatted content. Only the media-PATCH-with-
  conversion path interprets markdown into Docs formatting, and that path is the
  one that replaces the whole body. So you cannot get "markdown converted to rich
  formatting" AND "comments stay anchored" in the same operation. If rich
  formatting of the corrected text is required, you must emit Docs styling
  requests in the batchUpdate yourself.

## RECOMMENDED method (concrete)

Use surgical batchUpdate on the same document object. Never delete a span that a
comment quotes. Concrete flow:

Step 1. Snapshot the comments and their quoted text (read-only).

```
GET https://www.googleapis.com/drive/v3/files/{DOC_ID}/comments
    ?fields=comments(id,content,resolved,quotedFileContent/value,replies(id,content))
    &includeDeleted=false&pageSize=100
Authorization: Bearer {TOKEN}
```

Collect every `quotedFileContent.value`. These strings are your no-delete zones.

Step 2. Pull the current body with character indices.

```
GET https://docs.googleapis.com/v1/documents/{DOC_ID}
    ?fields=body/content(startIndex,endIndex,paragraph/elements(startIndex,endIndex,textRun/content))
Authorization: Bearer {TOKEN}
```

Reconstruct the full text and the index of every run. Locate each quoted string
in that text and mark its [startIndex, endIndex) as protected.

Step 3. Compute the edits so that no protected range is inside any
deleteContentRange or replaceAllText match. Edit only the regions between
protected spans, or insert new content adjacent to them.

Step 4. Pin a rollback point (optional but cheap).

```
# find the head revision
GET https://www.googleapis.com/drive/v3/files/{DOC_ID}/revisions?fields=revisions(id)
# pin it
PATCH https://www.googleapis.com/drive/v3/files/{DOC_ID}/revisions/{REV_ID}
Content-Type: application/json
{ "keepForever": true }
```

Step 5. Apply the edits in one atomic batchUpdate. Apply deletes/replacements in
descending index order so earlier edits do not shift later indices (or use
replaceAllText, which is index-independent).

```
POST https://docs.googleapis.com/v1/documents/{DOC_ID}:batchUpdate
Authorization: Bearer {TOKEN}
Content-Type: application/json
{
  "requests": [
    { "replaceAllText": {
        "containsText": { "text": "old phrasing that has NO comment on it", "matchCase": true },
        "replaceText": "corrected phrasing"
    }},
    { "insertText": {
        "location": { "index": 1234 },
        "text": "New paragraph inserted next to, not over, a commented span.\n"
    }},
    { "deleteContentRange": {
        "range": { "startIndex": 2000, "endIndex": 2080 }
    }}
  ],
  "writeControl": { "requiredRevisionId": "{REV_ID_FROM_DOCUMENTS_GET}" }
}
```

Notes on the body above:
- `requiredRevisionId` makes the call fail with 400 if someone edited the doc in
  the meantime, so you never apply a diff computed against stale indices. The
  revision id comes from the `revisionId` field of the `documents.get` response.
- Never put a protected (commented) substring in a `replaceAllText.containsText`
  or inside a `deleteContentRange` range.
- After the call, re-list comments and confirm the count is unchanged.

CONFIRMED vs MUST-VERIFY:
- CONFIRMED by docs + live test: comment objects survive batchUpdate and even a
  media-PATCH overwrite; files.copy (API) does not copy comments; the Drive API
  does not expose native Docs anchors (only quotedFileContent); media-PATCH
  replaces the full body.
- MUST VERIFY on a UI copy: that the Docs editor keeps each of the 18 / 2
  comments visually anchored to the right sentence after the surgical edits.
  Google does not document this, and it cannot be observed through the API.

## Safe test plan (validate on a copy before touching originals)

1. In a browser, open the real doc. File > Make a copy. Tick "Copy comments and
   suggestions." Name it clearly as a throwaway. This is the ONLY way to get a
   copy that has the comments (the API copy does not). Record the copy's file ID
   from its URL.

2. Confirm the copy carries the comments:
   `GET /drive/v3/files/{COPY_ID}/comments?fields=comments(id,quotedFileContent/value)`
   Expect 18 (or 2) comments.

3. Run the exact batchUpdate diff you intend to apply, but against {COPY_ID},
   with `writeControl.requiredRevisionId` set.

4. Re-list comments on the copy and assert the count is unchanged and none are
   `deleted`.

5. Open the copy in the browser and visually confirm each comment is still
   anchored to the intended sentence and none landed in the orphaned/resolved
   tray. This human eyeball is the step the API cannot do for you and is the real
   pass/fail gate.

6. Only after the copy passes step 5, repeat the identical batchUpdate against
   the real doc ID, having first pinned a rollback revision (keepForever) on the
   current head.

7. If any comment orphans on the copy, fall back to Rank 2 (insert-only around
   commented spans) for the sentences that carry comments, and rerun the test.

8. Trash the throwaway copy when done.

Hard rule for the real run: do not use media-PATCH on the two real docs. Even
though the threads survive it at the data layer, it orphans every anchor in the
UI, which defeats the purpose.
