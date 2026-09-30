# Changelog

## 0.1.0.dev8

- Preserve safely cleaned Unicode metadata spelling in storage and public
  responses. NFKC is used for comparison, search, filtering, and tag identity;
  historical metadata is not rewritten.
- Apply a configurable Core semantic minimum score before merging search
  candidates, counting results, and paginating. The default is `0.42`;
  `semantic_min_score=0` retains the former positive-score behavior. Keyword
  matches survive low semantic scores, and empty search results remain valid.
- Generate and validate replacement embeddings before atomically updating the
  stored row. Provider failures and cancellation preserve the old row; batch
  counters and the existing MCP failure field reflect actual outcomes.
- Keep the existing SQLite schema, HTTP and MCP request/response schemas, and
  data compatibility identifier. The default null vector provider remains
  keyword-only. No historical data migration is included.
