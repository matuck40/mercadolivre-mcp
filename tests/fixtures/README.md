# Test fixtures

## mcp-schema-2025-11-25.json

Official Model Context Protocol JSON Schema (JSON Schema 2020-12, definitions under `$defs`),
revision 2025-11-25. Used only by `tests/test_conformance.py`, offline.

- Source: https://github.com/modelcontextprotocol/modelcontextprotocol/blob/1155ca460e5097019f32769b38dcba194432e2fb/schema/2025-11-25/schema.json
- Raw URL: https://raw.githubusercontent.com/modelcontextprotocol/modelcontextprotocol/1155ca460e5097019f32769b38dcba194432e2fb/schema/2025-11-25/schema.json
- Commit SHA: `1155ca460e5097019f32769b38dcba194432e2fb` (main at 2026-10-18)
- License: the repository states that new contributions are licensed under Apache-2.0
  (documentation under CC-BY-4.0) and that older contributions remain under MIT during a
  relicensing transition. See
  https://github.com/modelcontextprotocol/modelcontextprotocol/blob/1155ca460e5097019f32769b38dcba194432e2fb/LICENSE
- The file is vendored unmodified.

Why not 2026-07-28: that revision is newer, but it removes the `initialize` handshake and adds
`server/discover` and a required `resultType` on every result. This server implements the
2025-11-25 lifecycle, so it validates against that revision.
