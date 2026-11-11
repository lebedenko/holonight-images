# Isolated source preview transaction

An opt-in synchronous `IsolatedClient::sourceTransaction` captures a caller-owned
seekable source once, validates the runtime once and launches one isolated helper.
The original one-operation APIs and version-1 operation records remain supported.

Transaction records explicitly carry `transactionVersion: 1`, a zero-based
`sequence` and a boolean `retainedSource`. Replies echo transaction version and
sequence in addition to the existing validated operation identity and layout.
The first request inspects the captured source with orientation and metadata.
At most four subsequent requests decode bounded cached PNGs; at most one final
request decodes the retained source. Acknowledgement ends the transaction.
Repeated inspection, reordered identities, extra cache attempts, and operations
after source decode terminate it. Non-PNG candidates remain cache misses.

`SourceTransaction` is noncopyable and callback-scoped. Its decode results and the
inspection passed to coordination are provisional. The callback must release
rejected pixels and must not publish or write caches. Only the selected result is
returned after normal helper exit and verified hierarchical cleanup; its
inspection is always the source inspection. Callback/transport exceptions poison
the transaction even when caught during coordination. Cancellation, protocol
failure and the shared 15-second post-launch deadline discard provisional output.
Cleanup retains its separate five-second budget and takes precedence over
cancellation. Runtime hashing and blocking caller reads retain their limitations.

The sandbox, full runtime verification, allocation ceilings and 2 GiB/no-swap
scope limits are unchanged. There is no helper reuse across calls.

The [Thumbnails contract](../../../../holonight-thumbnails/docs/sdd/source-preview-transaction/DESIGN.md)
keeps cache policy outside Images. The [umbrella note](../../../../docs/initiatives/source-preview-transaction.md)
records integration and evidence.
