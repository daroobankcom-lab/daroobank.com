# ADR 0034: current product and price stager-account presence

Status: development-only, 22 November 2026. Extends the selected creator-account checks in [ADR 0033](0033-missing-source-and-clinical-creators.md) to product and price review, not every ingestion actor or all relationships.

## Problem and decision

A selected synthetic test with a deferred foreign-key constraint showed that product and price review services could write reviews for candidates whose nonempty stager ID no longer resolved. A non-null product stager join also hid such candidates in the queue and detail. This corruption/bypass scenario is not the normal committed state with intact database constraints.

After locking the candidate and preserving existing permission and self-review rules, each writer now checks current stager-account existence on the candidate's database and returns its existing conflict without writing if the account is absent. Price's legitimately nullable stager remains a separate conflict. Inactive or non-staff stager accounts count as existing; this is not an authorization or qualification check. Product queue/detail no longer inner-join the account; each detail uses a separate current-account lookup, shows a missing-account notice and disables the form. A valid review POST still reaches the writer and returns 409. Queue listings do not check account presence. Product and price comparison classifiers and receipt manifest consistency/inspection still check payload and local consistency rather than candidate stager existence; their pages say so. A missing stager does not by itself suppress candidate content, comparison results, or receipt links.

## Evidence and limits

Synthetic PostgreSQL tests temporarily corrupt deferred FK IDs and restore them before transaction completion. They cover all review decisions, private GET/POST, queue visibility, permissions, self-review, nullable price stagers, existing inactive accounts, and comparison/manifest boundaries. Same-transaction test-only bypasses show that a subsequent nonparticipating mutation can invalidate the observed stager. A separate-connection test shows the account can be deactivated while either review is paused; it does not demonstrate concurrent deletion or every schedule.

Neither writer locks the account: existence may change after the SELECT, and neither the account lookup nor page reads constitute a single durable snapshot. This does not prove attribution, historical identity, qualifications, source rights, or correctness of payloads. Receipt actor integrity and unrelated FKs are not checked by this change. Foreign-key enforcement, direct database mutations, later changes, ABA and race cases remain limitations. No repair, audit, real source license, clinical approval, production hardening or publication is implied.
