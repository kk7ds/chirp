# CHIRP PR Guidelines

The following must be true before PRs can be merged:

1. All tests must be passing. The "PR Checks" job is speculative and failure doesn't always indicate a critial problem, but generally it needs to pass as well.
1. Commits should be rebased (or simply rebase-able in the web UI) on current master. Do not put merge commits in a PR.
1. Commits in a single PR should be related. Squash intermediate commits into logical units (i.e. "fix tests" commits need not survive on their own). Keep cleanup commits separate from functional changes.
1. Major new features or bug fixes should reference a [CHIRP issue](https://chirpmyradio.com/projects/chirp/issues) _in the commit message_. Do this with the pattern `Fixes #1234` or `Related to #1234` so that the ticket system links the commit to the issue.
1. Please write a reasonable commit message, especially if making some change that isn't totally obvious (such as adding a new model, adding a feature, etc). The first line of every commit is emailed to the users' list after each build. It should be short, but meaningful for regular users (examples: "thd74: Fixed tone decoding" or "uv5r: Added settings support").
1. New drivers should be accompanied by a test image in `tests/images` (except for thin aliases where the driver is sufficiently tested already). All new drivers must use `MemoryMapBytes`.
1. All files must be GPLv3 licensed or contain no license verbiage. No additional restrictions can be placed on the usage (i.e. such as noncommercial).
1. Do not add new py2-compatibility code (No new uses of `six`, `future`, etc).
