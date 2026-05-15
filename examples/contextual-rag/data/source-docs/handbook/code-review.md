# Code review

Every change ships through a pull request. There are no direct pushes
to the `main` branch — the branch protection rule rejects them and the
`protect-main` pre-push hook catches the mistake before it reaches the
remote.

## Opening a pull request

Open a pull request as soon as the change compiles and the tests pass.
Draft pull requests are encouraged: opening early gives CI a chance to
catch problems while the change is still cheap to redirect.

The pull request title follows Conventional Commits: a type prefix
(`feat`, `fix`, `chore`, `docs`, `refactor`, `test`), an optional scope
in parentheses, and an imperative subject under 70 characters.

## Reviewer expectations

Every pull request needs one review from a maintainer of the touched
package. Two reviews are required for changes that cross package
boundaries or modify the deployment pipeline.

Reviewers focus on the change's interface, not its style — the
formatter and linter handle style. If style still drifts, open a
follow-up pull request against the linter configuration rather than
litigating it in the review.

## Merging

Pull requests use squash-merge. The squash commit takes its message
from the pull request title and body so the linear history stays
greppable.

Hot-fix branches are the only exception: they use rebase-merge so the
original commit timestamp is preserved for the post-incident report.
