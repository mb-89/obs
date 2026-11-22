# Plugins

A plugin is a part obs builds with that does not live in obs's repository: an adapter, a style, or
any later kind. Every plugin is found, installed and named the same way, by the one command below.
The adapter in `adapters/html` is one plugin like any other; obs has no built-in adapter beside the plugins it
finds.

This note replaces the integrated adapter of the 5 Nov decision
([[architecture#Repository layout]]), `adapters.json` as the only adapter registry
([[cli#One-call build]]) and the style named by its repository address and commit
([[architecture#Declared style]]).

The plugin command and the build's adapter lookup are implemented (`src/obs/plugins.py`); naming a style by `obs.style` and
[Recording what built a page](#recording-what-built-a-page) are not yet, and until they land those
sections describe the build as it is.

## A plugin

Each plugin is its own Git repository. A release of it is a tag in that repository that names it a
plugin, its kind, its name and its version:

```text
obs-plugin/<kind>/<name>/v<major>.<minor>.<patch>
```

- `kind` is `adapter`, `style` or a later kind, in lowercase letters.
- `name` is the plugin's name, 1 to 32 lowercase letters, digits and dashes, starting with a letter
  or digit. The name, not the repository, is the plugin: a document and a call name a plugin by it
  alone.
- The version orders the releases by its three numbers; the newest release is the highest.
- The release is the commit the tag points to. A tag that starts with `obs-plugin/` but breaks this
  form is no release: the command lists it as a warning naming the repository and the tag, and skips
it.

A repository's other tags and branches are none of obs's. A repository may carry releases of one
plugin only; tags of two names or two kinds in one repository are each listed as a warning naming
the repository, and neither is offered from it.

What a release holds is its kind's: an adapter release holds its `adapter.json` at the root of its
tree ([[architecture#Adapter call]]), and a style release holds a style module's files at its root
(the configuration note of `adapters/html`, Declared style).

A later kind names its own entry file. A kind obs does not know is listed and installed like any
other; only a part that knows the kind uses it.

Finding releases by tag was chosen over an index repository that lists the plugins: an index is a
second file to keep in step with every release, while a tag is the release itself (the person's
choice, 22 Nov 2026).

Folding the adapter in `adapters/html` into the plugins was chosen over keeping it built in beside found plugins:
two mechanisms would find adapters two ways, and a second adapter would still need the first.

## The plugin command

`obs-plugins` is the one command. It needs a Git checkout of obs, the one the core runs from; run
from no checkout, it fails naming the folder and the remedy, to run it from a clone. Through RUNME
it is `RUNME.sh plugins` (or `RUNME.ps1 plugins`): `obs-document plugins ARGS` runs `obs-plugins
ARGS`, since RUNME, se's, starts one command.

### Listing

`obs-plugins` with no argument lists the plugins:

1. It reads the checkout's remotes from the checkout's own Git configuration, in the order Git
   lists them (`git remote`), each by its address as configured (`remote.<name>.url`). Nothing
   else names a remote: no committed file, no setting, no Document and no build record.
2. It takes each remote's host and owner, the account or organization, from its address
   (`https://host/owner/repository`, `ssh://user@host/owner/repository` or
   `user@host:owner/repository`), and asks the host for that owner's repositories that carry the
   repository topic `obs-plugin`.

   Each found repository is reached the way the remote is: its address is the remote's with the
   repository's name in place of the remote's.
3. It reads the tags of each repository (`git ls-remote --tags <address>`), without fetching its
   objects, and keeps the `obs-plugin/` releases: for each remote, its own repository first, then
   the owner's found repositories by name. A repository reached twice is read once, at its first
   place.
4. It lists each plugin once, with its kind, its installed version or `not installed`, its newest
   offered version and the repository that offers it ([Several remotes](#several-remotes)). A
   plugin whose newest version is above its installed one is marked as an update; an installed
   plugin no repository offers is listed with no newest version.

The host lists an owner's repositories through its own interface: on `github.com`, its repository
search for the topic and the owner, with the person's login where there is one (`GH_TOKEN`,
`GITHUB_TOKEN`, or the token `gh auth token` prints), which a private owner needs.

A host or owner
that cannot be listed (no login for a private owner, a host obs knows no listing for, an owner the
host does not know) is one warning line naming the remote, the host, the owner and why; that
remote's own repository is still read.

A repository that cannot be read is a warning naming its address and Git's message; the list still
shows what the others offer. A repository that offers no release is not listed.

Reading the remotes was chosen over a configured list of plugin sources: a person already adds a
remote to reach a repository, and a remote lives in the checkout's Git configuration, which nothing
commits.

Searching each remote's owner was chosen over taking each remote as one plugin repository: a fresh
clone would find no plugin until someone added a remote for each, while a clone should find every
plugin of the owner it came from, and another owner's plugins once any repository of that owner is
a remote (the person's requirement, work issue 860, 22 Nov 2026).

The owner and host come only from the checkout's Git configuration; nothing committed names them.

### Choosing

The person chooses what to install, update or remove; the command never does it unasked:

- `obs-plugins install NAME` installs the plugin's newest offered release, or updates an installed
  one to it.
- `obs-plugins install NAME VERSION` installs that release, older or newer than the installed one;
  VERSION is written `<major>.<minor>.<patch>`.
- `obs-plugins update NAME` updates an installed plugin to its newest offered release; a plugin
  that is not installed fails naming the remedy, `obs-plugins install NAME`.
- `obs-plugins remove NAME` removes an installed plugin.

A name or version no repository offers fails naming it and the versions offered. An install is
complete or absent: the release's tree is fetched into a temporary folder in the machine folder and
checked against its kind's entry file, and only then replaces the installed version, so a failed
install leaves the installed version as it was.

An adapter's entry file is `adapter.json`, which
must name the plugin.

### Installed plugins

Installs go to the machine, as local themes do (the configuration note of `adapters/html`, Local
themes): the folder `obs` in the user's configuration folder (`$XDG_CONFIG_HOME` or `~/.config` on
Linux, `~/Library/Application Support` on macOS, `%APPDATA%` on Windows), or the folder
`OBS_LOCAL_FOLDER` names where it is set and not empty.

- `plugins/<name>/` holds the installed release's tree, never a checkout inside obs's repository.
- `plugins.json` beside it is the machine-local list: for each installed plugin its `name`, `kind`,
  `version` and `commit`. It names no remote, owner, host or path, and no committed file names it.

One version of a plugin is installed at a time: installing another version replaces it, so the
list holds each name once.

Installing one version only was chosen over installing versions side by side: a build that finds
one version per name needs no rule for which one a document meant (the person's requirement).

## Several remotes

A plugin that several repositories offer, under the same name and kind, is one plugin: the list shows it
once, and the machine installs it in one version only.

The release offered is the newest any of these repositories offers. Where several offer that
same version, it is taken from the first of them in the reading order of [Listing](#listing), so
from the first remote in the checkout's order. The list shows which repository offers it, so the
person sees where an install would come from (decision of 22 Nov 2026 on the work issue).

The same name under two kinds is two releases that cannot both be the plugin: the list shows it as
a warning naming each repository and kind, and offers neither until one of them stops.

## Naming a plugin

A document names a plugin only by its name. A manifest declares its style as `obs.style: <name>`,
and a call chooses its adapter as `--adapter NAME`; neither names a repository, a remote, a version
or a path.

A build finds the named plugin among the installed ones. One that is not installed, or is installed
as another kind, fails the build naming the field (or the option), the plugin and the remedy, to
run `obs-plugins install NAME`. An adapter's commands run from its installed folder.

While the adapter in `adapters/html` still lives in obs's tree, a build finds it as the adapter
plugin `html` where no plugin `html` is installed: its manifest is `adapters/html/adapter.json` of
the checkout the core runs from, and its commands run from that checkout's root, as before. An
installed `html` is the person's choice and wins over it.

A build installs and fetches nothing: plugins come only from the checkout's remotes, and only when
the person chooses them with the plugin command.

## Recording what built a page

Every built page records the plugins that built it: for the adapter, the style and every other
plugin the build used, the `name`, `kind`, `version` and `commit` as `plugins.json` lists them.

The core passes them in the Document, so the adapter writes them into its artifact without reading
the machine's list, and the source archive's build record carries the same list
([[architecture#Source archive]]).

A rebuild uses the versions installed on its machine: where one differs from the recorded version,
the build warns naming the plugin and both versions, and where a recorded plugin is not installed it
fails as any build naming an absent plugin does.
