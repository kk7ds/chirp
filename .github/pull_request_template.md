# CHIRP PR Checklist

The following must be true before PRs can be merged:

* All tests must be passing.
* Commits should be squashed into logical units.
* Commits should be rebased (or simply rebase-able in the web UI) on current master. Do not put merge commits in a PR.
* Commits in a single PR should be related.
* Major new features or bug fixes should reference a [CHIRP issue](https://chirp.danplanet.com/projects/chirp/issues).
* New drivers should be accompanied by a test image in `tests/images` (except for thin aliases where the driver is sufficiently tested already).
* All files must be GPLv3 licensed or contain no license verbiage. No additional restrictions can be placed on the usage (i.e. such as noncommercial).

Please also follow these guidelines:

* Keep cleanups in separate commits from functional changes.
* Please write a reasonable commit message, especially if making some change that isn't totally obvious (such as adding a new model, adding a feature, etc).
* The first line of every commit is emailed to the users' list after each build. It should be short, but meaningful for regular users (examples: "thd74: Fixed tone decoding" or "uv5r: Added settings support").
* Do not add new py2-compatibility code (No new uses of `six`, `future`, etc).
* All new drivers should set `NEEDS_COMPAT_SERIAL=False` and use `MemoryMapBytes`.
* New drivers and radio models will affect the Python3 test matrix. You should regenerate this file with `tox -emakesupported` and include it in your commit.
