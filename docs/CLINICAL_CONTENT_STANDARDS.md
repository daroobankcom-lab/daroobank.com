# Clinical content and evidence standards

There is now a development-only private statement-draft and preliminary triage workflow; the clinical standards below remain release goals. There are no reviewed monographs or licensed interaction data. Original Persian patient content and professional clinical content require independent qualified review; AI-generated text is not evidence. Do not copy proprietary databases or imply that foreign labels establish Iranian product approval.

## Content model and evidence

Sections include identification, mechanism, indications, dosing by population, administration, contraindications, precautions, adverse reactions, interactions, overdose, pregnancy/lactation, renal/hepatic issues, kinetics, storage and patient counseling. Populate only if evidence is suitable for the indication, age, route and formulation. Link each material clinical statement to exact reference(s) and location, including title, authors, journal/organization, date, DOI/PMID, URL, type, access date and source version; capture evidence quality when appropriate and identify uncertainty, jurisdiction and gaps.

## Workflow

Draft → evidence attachment → qualified pharmacist/medical review → editorial approval → publication → scheduled re-review; rejection returns to draft. Author and final reviewer must be different people. Each action has actor, time, reason and version. The publication shows author/reviewer qualifications, last reviewed and next review policy; urgent regulatory changes trigger earlier review. Corrections create a new immutable version, link the prior version and log reason; urgent withdrawal immediately removes affected claims from public access while preserving controlled audit. Source/licence expiry or unresolved serious contradictions triggers review or withdrawal.

## Safety and future tools

No statement of a verified negative interaction unless supported by validated data and explicit coverage. Unknown, not assessed, and incomplete evidence must be distinct from verified negative. A checker needs licensed/legitimate structured pairs, severity, mechanism, recommendations, review and audit before release; free label prose alone is not a complete interaction dataset. High-risk calculators, pregnancy advice, dose support and pill identification need independent validation, defined intended use, usability and regulatory review. Patient pages provide clear direction to appropriate qualified help for concerning symptoms without making diagnoses. AI can draft or retrieve only for review; no autonomous publishing, prescribing, fabricated citations or silent uncertainty.


## Implemented development-only editorial slice

`clinical/` allows active staff with separate view/add/review permissions to create a synthetic text draft with one primary and up to ten supplementary asserted citations and record independent preliminary triage. The free-text subject is not linked to any ingredient, generic, product or package; no content is exposed publicly. Citation title, location and HTTPS URL are mandatory; author, version and Gregorian publication/access dates are optional, user-entered and unverified. The field is intended for one statement, but the software cannot enforce that it contains only one. It does not fetch or check references, establish permissions, assess evidence or verify reviewer qualifications. An exact-URL source claim hint for the primary citation is optional and independently permission-gated, not authorization.

A new version explicitly links an immediate parent, original parent fingerprint and reason; subject/audience stay exactly the same, branching is allowed and previous reviews do not carry over. Only the current draft and immediate parent payload are checked, not the full ancestry. A staff reviewer different from the draft author and every current supplementary-reference recorder can record a reasoned referral for more review, rejection or deferral; none is clinical approval, and there is no publish operation. This is not a monograph, clinical decision support or a safe source of patient advice. Use only fictional, non-sensitive values until governance, rights, review and production safeguards are established. See [ADR 0005](ARCHITECTURE_DECISIONS/0005-clinical-draft-triage.md).


Supplementary reference relationships (support, contradiction, context or unclear) are user assertions, not evidence-quality assessments or facts established from a source. The reference set is bound to one draft version and is not copied to revisions. New preliminary reviews snapshot the current validated set; older reviews have no such snapshot and are not backfilled. Changed-set and same-fingerprint labels are only consistency checks, not approval, source verification or proof of completeness. See [ADR 0006](ARCHITECTURE_DECISIONS/0006-clinical-evidence-assertions.md).
