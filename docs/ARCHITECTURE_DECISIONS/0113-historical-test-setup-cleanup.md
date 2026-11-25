# ADR 0113: restore historical migration tests after setup failure

Status: development-only test reliability, 24 November 2026.

## Problem and decision

Four historical catalog migration tests rolled the disposable test database back during `setUp`, but restored the graph only in `tearDown`. Python's unittest skips `tearDown` when `setUp` raises, so a setup failure could leave the schema downgraded as Django flushes it and cause misleading subsequent failures. Register graph restoration with `addCleanup` before starting each rollback. Unittest runs the registered cleanup even if setup fails, and Django's test wrapper subsequently performs post-test teardown.

## Evidence and limits

A disposable-PostgreSQL regression test injects an exception immediately after the first rollback in each of the four actual test classes. It confirms the expected setup error, checks that all migration graph leaves are recorded before Django's post-test flush, and restores the graph between probes. On the earlier candidate-test implementation the same probe observed a missing leaf before flush; the corrected test restores it. Ordinary migration tests are also exercised with shuffled order.

Cleanup is an attempt, not a guarantee: forward migration or the connection may fail, process termination can prevent cleanup, and recorded leaves don't prove schema or data correctness. This does not make destructive migration tests safe against valuable databases, and it is not a production rollback or recovery plan. Use a separately authorized disposable PostgreSQL cluster and synthetic data only.
