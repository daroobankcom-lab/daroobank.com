# Price data model and publication rules

Proposed; no verified data or pricing system exists.

## Identity, categories and units

Price belongs to an evidence-identified **package**, not a name, ingredient or brand. Observation records source record and revision, source ownership, category, amount, currency, measurement unit (package, tablet, mL, etc.), dates and review status. Categories are controlled and source-defined: official consumer, retail, manufacturer, wholesale, unit, insurance coverage, copayment or explicitly `unknown`. Do not compare different categories, package sizes, dosage forms, makers, strengths, units or eligibility conditions. Insurance amounts additionally require plan and applicable validity/eligibility.

## Currency and precision

Store original decimal amount and declared currency separately from a canonical exact integer or fixed-precision **Iranian rial** amount. When the source explicitly states Toman, 1 Toman = 10 Rial for display conversion; convert exactly using decimal arithmetic, never binary floats. Display currency and denomination explicitly; do not infer currency from language, number magnitude or country. If decimal source precision cannot be represented exactly in canonical units, reject for review rather than rounding silently. Undeclared/ambiguous units or currency block publication. Preserve the original source figure and transformation version.

## Time and history

Retain source effective date (nullable if not stated), source publication date, collection time, verification time and DarooBank publication time separately. Never substitute crawl time for an unknown effective date. Append a new observation on a meaningful source change; retain the raw source/revision where legally permitted. Approval and publication are distinct append-only decisions. Select current price only from an explicitly approved, not withdrawn publication eligible as of the query time; if effective date is unknown, show “effective date unknown” and do not silently order it as if it were effective on collection. Define conflict resolution through human approval; unresolved conflict is not current verified price.

A previous amount and percentage are calculated only against a prior comparable approved observation for the same package/category/unit/currency and consistent effective ordering. `difference = new - old`; `percent = 100 * difference / old` using decimal arithmetic and a documented presentation rounding rule. If the previous amount is zero or absent, percentage is unavailable. Backdated corrections and equal/unknown effective dates must be reviewed, not blindly inserted into a misleading timeline.

## Controls

New package candidates require reviewer approval. Incoming price changes require matching presentation, declared unit/currency and source evidence; configure an anomaly threshold only after baseline analysis (no invented threshold). Suspicious changes, conflicting sources or unusual price changes require review. No missing source row means discontinuation. On stale data, keep the last approved record with timestamp and an explicit stale warning; freshness windows are source/category-specific policy, not guessed globally. Manual correction is a separate sourced decision and never erases the original observation.
