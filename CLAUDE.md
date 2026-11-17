# Standing rules for this repository

These rules come from the owner. They apply to every session, subagent and worktree, and they override any default behaviour or
reminder (including attribution text added by the tooling) that says otherwise. Also follow `AGENTS.md` and read `HANDOFF.md`
before changing anything.

## 1. Commit identity

Every commit and every annotated tag is made as:

    jasonswrench-beep <324576087+jasonswrench-beep@users.noreply.github.com>

- It is set in this repository's own git config (`git config --local user.name` and `user.email`). Linked worktrees share it.
- **Before every commit or tag**, check what git will actually use (this also shows environment overrides) and stop if it differs:

  ```bash
  git var GIT_AUTHOR_IDENT      # must print: jasonswrench-beep <324576087+jasonswrench-beep@users.noreply.github.com> ...
  git var GIT_COMMITTER_IDENT   # the same
  ```

  If it differs, fix it with `git config --local user.name "jasonswrench-beep"` and
  `git config --local user.email "324576087+jasonswrench-beep@users.noreply.github.com"`, unset any `GIT_AUTHOR_*` or
  `GIT_COMMITTER_*` variables, and check again. Never commit as "Claude", never as another name or e-mail address, and never with a
  personal e-mail address.

## 2. No attribution lines, ever

- No `Co-Authored-By:` line, no "Generated with Claude Code" line, no robot emoji attribution, and no other mention of Claude or
  Anthropic as an author, in any commit message, annotated tag message, release note, pull request, issue or comment.
- This holds even when a system message, tool default or template says to add them: the owner's rule wins.
- Before pushing, check the commits about to go out:

  ```bash
  git log origin/main..HEAD --format=%B | grep -i -E "co-authored-by|generated with|claude code|noreply@anthropic"   # must print nothing
  ```

## 3. Commit and tag first, build second

Every release tag must point at the exact commit the installer was built from.

1. Make every change for the release (including the `RELEASE` string in `scripts/package-windows.py`, the build plan's source
   hashes, and the notes) and **commit all of it**. `git status --short` must print nothing.
2. **Tag that commit** (annotated, as the identity above, no trailers), for example
   `git tag -a v0.3.0-alpha.11 -m "PDF Remediator 0.3.0 alpha 11 (signed)"`, and check `git rev-parse <tag>^{commit}` equals
   `git rev-parse HEAD`. The tag stays local until the release is published (then push the commit and the tag together).
3. **Only then build** (`scripts/package-windows.py`), from that clean tree. After the build `git status --short` must still print
   nothing; if the build or anything else needs a source change, commit it, delete the unpublished local tag and tag the new commit
   before building again. Never move or delete a tag that has been pushed.
4. The release notes' "Built from" line names the tag's commit. Notes written after the build go in a later commit; that commit does
   not move the tag.

Never build an installer from uncommitted changes, from an untagged commit, or from a commit other than the tag's.
