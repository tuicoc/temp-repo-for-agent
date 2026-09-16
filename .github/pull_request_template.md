<!--
The title follows the same schema as a commit message, because on a squash
merge it becomes the subject on main:

    <type>(<scope>)!: <subject>

See CONTRIBUTING.md for the type and scope tables.
-->

## What changed

<!-- One or two sentences. The diff says what; say why. -->

## Why

<!-- The problem this solves, or the decision this records. -->

## Checklist

- [ ] The title follows the commit schema, and every commit does too
- [ ] The branch name follows `<type>/<short-description>`
- [ ] One concern only — a specification change and its implementation are separate pull requests
- [ ] A breaking change is marked with `!` and a `BREAKING CHANGE:` footer
- [ ] If this touches `docs/flow.md` or `docs/diagrams.md`: the type is `spec`, both files
      were updated together so section N still pairs with figure N, and the body
      states the decision and its reason
