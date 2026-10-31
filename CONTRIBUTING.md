# Contributing

Thanks for your interest. `stunt-reel` is a pre-alpha research project, so formats, APIs and
documentation still move; an issue before a large change saves us both time.

## Where the rules live

[`AGENTS.md`](AGENTS.md) is the developer guide for people and AI coding agents alike. It links
every source of truth: the glossary, the specification and its invariants `[I1]`–`[I8]`, the
architecture routing, and the research notes. Environment setup and the task list are in
[`docs/development.md`](docs/development.md).

## Before you open a pull request

- **No game files, ever.** Never commit Stunt Island assets, executables or disk images, or
  anything derived from them beyond the two tables documented in [`NOTICE.md`](NOTICE.md).
  `corpus/` is gitignored for that reason; tests run offline on the
  synthetic fixtures in [`tests/fixtures/`](tests/fixtures/README.md).
- **Run the gate.** `mise run check` (format, lint, typecheck and tests for Rust and Python)
  must pass. CI runs it on every pull request.
- **CodeRabbit comments are advisory.** A pull request also gets an AI review from
  [CodeRabbit](https://coderabbit.ai), configured in [`.coderabbit.yaml`](.coderabbit.yaml).
  It cannot block a merge: the gate and a person are the review, so decline a comment with a
  reason and move on. While the repository has fewer than ten stars CodeRabbit reviews on
  request, so comment `@coderabbitai review` on your pull request to get one.
- **Write the why.** Use a Conventional Commit subject and a body that explains the reason for
  the change, as described in
  [`AGENTS.md` § Commit Messages](AGENTS.md#commit-messages).
- **Research findings** go in the note that owns their subject, with an evidentiary tier;
  [`research/README.md`](research/README.md) has the routing.
- **Your email is published.** Commits land in the public history as written. If you would
  rather not expose your address, commit with your
  [GitHub noreply address](https://docs.github.com/en/account-and-profile/setting-up-and-managing-your-personal-account-on-github/managing-email-preferences/setting-your-commit-email-address).

## Licensing of contributions

By contributing, you agree that your code and schemas are licensed `MIT OR Apache-2.0` and your
documentation and research notes CC BY 4.0, the same terms as the rest of the repository (see
[README § License](README.md#license)). Do not contribute material you cannot license that way.

## Security

Report vulnerabilities privately as described in [`SECURITY.md`](SECURITY.md), not in an issue.
