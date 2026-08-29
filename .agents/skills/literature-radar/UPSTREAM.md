# Upstream attribution

Literature Radar V0 was designed with methodological reference to:

- Repository: `https://github.com/marciob/skill-research-papers`
- Upstream skill: `research-papers`
- Commit reviewed: `97131ba7007f62374cc689cf7a85fa8fead8bb2b`
- Commit date: 2026-05-10
- License: MIT

## Ideas adapted

The V0 workflow adapts the upstream project's approach to:

- framing a research question before searching;
- query expansion beyond literal keywords;
- using several source families for discovery and metadata cross-checking;
- normalizing identifiers and merging preprint/published versions;
- preferring canonical paper pages and primary evidence;
- separating discovery metadata from evidence-backed paper claims;
- screening before ranking;
- judging relevance, methodological/evidence value, and recency qualitatively;
- stating evidence depth and uncertainty rather than inventing missing details.

## Changes for this repository

- Replaced the general literature-review workflow with a narrow `Research Profile + Zotero context + recent external search` radar.
- Made read-only Zotero novelty and duplicate comparison a first-class ranking dimension.
- Added the repository-specific JSON and Markdown output contracts.
- Added a deterministic weighted overall score using the profile's four dimensions.
- Removed Workbench ingest, task execution, databases, scheduling, and all Zotero writes.
- Did not copy the upstream full-text fetcher, cache, virtual-environment bootstrap, Bash wrappers, Unix installer, smoke-test shell scripts, or source-specific API SDK code.
- Uses the existing zotero-cli plus Codex web/search tools so the workflow remains usable on Windows 11 and PowerShell without a new research framework; MCP remains an optional future backend.
- Full-text inspection is evidence-budgeted for serious finalists rather than requiring the upstream fetch-and-read protocol for every candidate.

No upstream source code or substantial verbatim documentation is vendored in this skill. The attribution is retained because the search and screening methodology materially informed the design.

## Upstream MIT license

```text
MIT License

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
