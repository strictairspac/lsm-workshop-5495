Schema v1: users, audit, datasets (JSON write sequence), configs (bounded LSM parameters), trials (immutable input snapshot and JSON result). MySQL stores metadata only. Run python -m scripts.seed_demo for create-if-missing and natural-key seed; existing values are not overwritten.

Schema v2 (additive, same create_all bootstrap): prefix active-key quota tables —
- quota_sites: site natural key (code), monotonic next_seq counter.
- prefix_limits: per-site (prefix, limit_value), unique per site+prefix; nested prefixes are independent rows and each layer counts.
- write_batches: idempotency key (site_id, token), accepted/rejected verdict, reason, ordered operations and the projected live view; a rejected batch writes no key_write_logs row.
- key_write_logs: append-only LSM-style write log (seq, key, value, deleted tombstone, batch_id, level); compaction rewrites this table keeping only winning records plus tombstones, and asserts the live view is unchanged.
- quota_compactions: before/after row and live-key counts plus the rewrite detail, evidencing "合并搬表不改占用".
Concurrency: batch admission takes a SELECT ... FOR UPDATE row lock on quota_sites as the transaction's first statement, so same-site contenders serialize on the last slot; disjoint-prefix batches commit independently. Replaying a token returns the stored verdict and never reserves slots twice.
