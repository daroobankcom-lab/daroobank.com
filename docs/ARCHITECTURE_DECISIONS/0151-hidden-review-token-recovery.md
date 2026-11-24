# ADR 0151: recover from invalid hidden review tokens

Status: development-only staff interface; synthetic tests. Extends ADRs 0028, 0139 and 0143 without changing authorization, CSRF, validation or review writes.

## Decision

Five private review forms (product, price, source, clinical and identity package) carry hidden concurrency or snapshot tokens that the user cannot correct as visible inputs. Previously source and clinical offered a GET restart only for an invalid latest-review ID; the other fields and three other forms only advised reopening the page, risking a browser refresh of the POST. For any of the currently defined hidden review fields with a validation error, a shared fixed alert now links to the corresponding same-origin detail GET. It explicitly warns that current form inputs are discarded. Multiple invalid hidden fields produce one link; visible-only errors do not offer it. A form unavailable due to permissions, actor separation, invalid state or conflict does not expose a broken form-specific recovery link. The link does not automatically resubmit, bypass checks or guarantee a later review will succeed.

## Evidence and limits

Synthetic authenticated HTTP tests cover every current hidden field individually in all five forms, multiple hidden errors, visible-only errors, unavailable self-review, correct named local GET route, privacy headers and no review writes. A Chromium smoke check manipulates one hidden token per form at 390px and uses the keyboard to follow the link, verifies restored token and cleared input, and checks selected layout and axe results. This is not comprehensive accessibility testing; some axe contrast results need manual inspection. Identity/general conflict recovery and other form types are separate behaviors; future hidden review fields must be added to the shared conditional and tests. GET re-reading is not a transactional snapshot, and no clinical, identity, rights or production approval follows from successful recovery.
