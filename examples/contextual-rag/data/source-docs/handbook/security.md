# Security

Tlaltipac is SOC 2 Type I; the renewal audit lands in Q3. The rules
below are written to keep that audit clean and to keep the production
environment uneventful.

## Secrets handling

Every secret lives in the company password manager. There are no
secrets in the repository, in Slack messages, or in pull request
descriptions. The `gitleaks` pre-commit hook scans every staged change.

If a secret leaks anyway, treat it as an active incident: rotate the
credential first, then file the incident report. Do not wait for
guidance — rotation is always cheaper than the alternative.

## Single sign-on

Every internal tool sits behind the company identity provider. New
employees are enrolled on day one as part of the laptop pickup
process. Any tool that cannot be wired into single sign-on requires
written approval from the security lead before it is adopted.

## Incident response

A production incident is anything that takes a customer-facing surface
down, exposes data, or violates a contractual service level. Anyone
on the team can declare an incident; declaring early is preferred to
declaring late.

The first responder posts the incident in the `#incidents` Slack
channel, opens a runbook from the wiki, and pages the on-call engineer
for the affected service. A post-incident review is written within
five business days and published to the engineering channel.
