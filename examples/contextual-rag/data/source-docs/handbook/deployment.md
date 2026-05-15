# Deployment

Tlaltipac ships every weekday. The release pipeline is fully
automated; the only manual step is the release notes write-up that
the release captain posts to the customer changelog.

## Continuous delivery

Every merge to `main` triggers a build, a full test run, and a
deployment to the staging environment. The deploy job pins the image
SHA, so the build the team validates in staging is byte-identical to
the one that reaches production.

A deploy to production runs once the staging environment has been
green for thirty minutes. Engineers can promote earlier through the
release tooling if the change is urgent.

## Rolling back

A rollback is one command: `make rollback service=<name>` reverts the
named service to its previous image. The command also opens an
incident ticket automatically so the rollback is tracked alongside the
underlying bug.

Never rollback without flagging it in `#engineering`. Even if the
change looks isolated, another engineer may be waiting for the new
build to test their own change.

## Release captain

The release captain rotates weekly. The captain owns the morning
deploy review, writes the customer-facing release notes, and is the
primary point of contact for any incident that happens during their
shift.

The schedule lives in the team calendar; the engineer on rotation
receives a calendar invite for the week.
