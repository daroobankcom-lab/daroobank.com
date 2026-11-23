# ADR 0059: complete bounded reads before CSV staging

Status: development-only, 23 November 2026.

## Problem

A blocking binary stream may legally return fewer bytes than requested without reaching EOF. Previously, the product and price CSV parsers each made a single `read(limit + 1)` call. A synthetic stream that first returned a complete header and one valid row caused both parsers to accept that prefix and ignore a second row; receipt-backed staging also accepted a valid prefix despite a malformed later row. This was reproduced in direct service tests; it is not evidence that Django's normal upload objects lost bytes in practice.

## Decision

Both parsers now read a blocking binary stream repeatedly, up to EOF or one byte beyond the existing per-domain limit (1 MiB product, 2 MiB price). Short reads are joined before UTF-8 decoding and CSV validation; reaching the extra byte retains the existing oversized-file rejection. Price path inputs are opened as binary files and use the same helper. No candidates or receipts are created until parsing succeeds.

The helper requests at most 64 KiB per read and permits at most 8,192 calls. Exhausting the call budget without seeing EOF or the extra byte fails as a read error, so unusually fragmented but otherwise valid streams can be rejected. Empty bytes mean EOF; `None`, text and responses larger than requested are errors, as are ordinary read errors and closed files. Parsers translate these selected read failures to their existing nonreflecting validation errors. They do not retry, seek, close caller-owned streams or publish data.

## Evidence and limits

Synthetic tests reproduce the original partial-read failure, check two-row short-read staging and manifests, compare replay membership and parser results across seven fragment sizes, reject malformed CSV and UTF-8 tails without partial writes, and exercise byte and call limits, nonbinary/nonblocking or failed reads, split multibyte UTF-8, HTTP privacy and price CLI reporting. Existing validation, PostgreSQL and browser tests remain applicable. The HTTP failure test injects a read failure; it does not simulate every web server or file system.

The helper trusts a stream's empty-byte EOF signal; it cannot detect a source that falsely reports EOF or changes its contents during reading. It cannot interrupt a blocking or malicious `read()` call, control allocations inside the source, or provide an overall request time or memory guarantee. Django or its server may buffer uploads separately. Byte and call limits do not establish authenticity, authorization, complete source data or production availability. Continue using synthetic, non-sensitive files.
