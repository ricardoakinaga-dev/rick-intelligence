# ADR-005 — Cookie vs Bearer precedence

Date: 2026-09-03. Status: Accepted.

When both arrive, the session cookie wins. Rationale: browsers attach cookies
automatically; letting a third-party-supplied Bearer override an authenticated
browser session enables session-confusion attacks. Bearer compatibility tokens
apply only when no cookie is present, and only on compat/external domains —
never as a privilege-escalation path for platform routes. Tested both directions.
