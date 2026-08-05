# Git reference for this repository

A working reference for the commands this project actually needs, rather than a general git
tutorial. The repository is `https://github.com/kc2998/capm-portfolio.git`, history is linear on
`main`, and there are no branches.

## The daily loop

```bash
git status                      # what has changed, and what is staged
git add -A                      # stage everything, including new files
git add src/loaders/prices.py   # or stage one file at a time
git commit                      # opens an editor for the message
git push                        # local main already tracks origin/main
```

`git commit -m "..."` works for a one line message, but this repository's commits carry
explanatory bodies, so opening an editor is usually better. For a long message written outside
the editor:

```bash
git commit -F - <<'MSG'
Short summary in the imperative, under about 72 characters

Body explaining what changed and why, wrapped at about 80 columns. State what
was measured rather than what was felt.
MSG
```

**Never add a `Co-Authored-By` line or any other attribution**, per `CLAUDE.md`.

## Working across two machines

`data/` is gitignored and currently holds 451 MB across 117 cached `companyfacts` files, the
price parquets, and the universe tables. None of it travels with a push, by design: it is
regenerable vendor output, not source.

The consequence is that a fresh clone has code but no data, and every loader call returns
`None` until the caches are rebuilt:

```bash
git clone https://github.com/kc2998/capm-portfolio.git
cd capm-portfolio
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

python -m scripts.build_universe        # cheap, rebuilds from cached Wikipedia snapshots
python -m scripts.build_prices          # 15 to 20 minutes, one request per ticker
python -m scripts.build_fundamentals    # one request per CIK
```

If both machines are yours and the network cost is not worth paying twice, copying `data/`
directly is faster than rebuilding, and safe because the contents are immutable vendor
responses:

```bash
rsync -av --progress ~/path/to/capm-portfolio/data/ ~/other/capm-portfolio/data/
```

Before starting work on a machine you have not used for a while:

```bash
git pull            # fetch and merge whatever the other machine pushed
```

If both machines have commits the other has not seen, that pull creates a merge commit. Setting
this once keeps the history linear by replaying your local commits on top instead:

```bash
git config pull.rebase true
```

## Looking before acting

```bash
git fetch                       # update your view of the remote, touch nothing else
git log HEAD..origin/main       # commits the remote has that you do not
git log origin/main..HEAD       # commits you have that the remote does not
git status -sb                  # one line: branch, and how far ahead or behind

git diff                        # unstaged changes
git diff --staged               # what a commit would contain right now
git diff --stat                 # file by file summary rather than full text
git log --oneline -10           # recent history, compact
git log -p src/loaders/fundamentals.py   # every change to one file, with diffs
git show 7fb7535                # one commit in full
```

## Undoing

Ordered from safest to least safe.

```bash
git restore src/loaders/prices.py        # discard unstaged edits to one file
git restore --staged src/loaders/prices.py   # unstage, keep the edits
git commit --amend                       # rewrite the most recent commit, if not yet pushed
git revert 7fb7535                       # a new commit undoing an old one, safe after pushing
git reset --soft HEAD~1                  # undo the last commit, keep the changes staged
git reset --hard HEAD~1                  # undo the last commit and discard the changes
```

`git reset --hard` destroys uncommitted work with no recovery. `git revert` is the one to use on
anything already pushed, since it adds history rather than rewriting it.

## Notebooks

Jupyter writes execution counts and output into the `.ipynb` file, so re-running a notebook
without changing a line still shows as a diff. Two habits help:

```bash
git diff --stat notebooks/            # check the size of a notebook diff before staging
```

Committing outputs is the convention here, since the exploratory notebooks are kept as a record
of what was run. `notebooks/validating_fundamentals.ipynb` is the exception in spirit: its value
is that re-running it re-checks the loader, so its saved output matters less than its assertions
passing.

## One-time setup on a new machine

```bash
git config --global user.name "Kevin"
git config --global user.email "kevinchen145@gmail.com"
git config --global pull.rebase true
git config --global init.defaultBranch main
```

GitHub no longer accepts a password over HTTPS. Either install the `gh` CLI and run
`gh auth login`, which configures credentials for you, or create a personal access token and let
the credential helper store it:

```bash
git config --global credential.helper osxkeychain    # macOS
```
