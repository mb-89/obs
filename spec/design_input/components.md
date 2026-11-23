# Components

A component is a part obs builds with that does not live in obs's repository: an adapter, a style, or
any later kind. Every component is found, installed and named the same way, by the one command below.
The adapter once in `adapters/html` is one component like any other, in its own repository; obs has
no built-in adapter beside the components it finds, and keeps no adapter in its tree.

This note replaces the integrated adapter of the 5 Nov decision
([[architecture#Repository layout]]), `adapters.json` as the only adapter registry
([[cli#One-call build]]) and the style named by its repository address and commit
([[architecture#Declared style]]).

The component command, the build's adapter and style lookup and
[Recording what built a page](#recording-what-built-a-page) are implemented (`src/obs/components.py`).

## A component

Each component is its own Git repository, and the repository carries nothing that names obs or a host
(SE's design of components, `docs/components.md` in SE, and the person's decisions of 22 Nov 2026):

- **Its mark** is the repository topic `component`, one topic for every host: a component is supposed
  to be integrated into a system, and nothing in it says which.
- **Its name** is the repository's name, compared without case and written in lowercase: 1 to 32
  letters, digits and dashes, starting with a letter or digit. A document and a call name a component
  by its name alone. A marked repository whose name breaks this form is a warning naming it, and skipped.
- **Its releases** are its tags `v<major>.<minor>.<patch>`, ordered by their three numbers; the newest
  release is the highest. The release is the commit the tag points to.
- **Its kind** is what its release's tree holds at its root: `adapter.json` makes an adapter
  ([[architecture#Adapter call]]), a style module's files, its `style.css` among them, a style
  (the configuration note of the adapter once in `adapters/html`, Declared style).

A repository's other tags and its branches are none of obs's: a moving `v1`, a `v1.0` or a
`v4.1.2-shared` is no release, and neither is the earlier form `obs-component/<kind>/<name>/v<version>`.

Passing over a tag that breaks the release form was chosen over warning on it: component repositories
carry moving major tags, such as obs's own `v1` to `v8`, and a warning on each would bury what matters.

A tree that holds `adapter.json` is an adapter whatever else it holds. A tree that holds neither is not
a component of obs: the list shows it with that reason, and it cannot be installed.

Reading the name from the repository and the kind from the tree was chosen over a tag that names
both: one repository is one component, a tag holds only the version, and the component names none of
its hosts (the person's decision of 22 Nov 2026, work issue 878).

The earlier tags and topic are not read beside them, since no released component carries them any more.

A later kind obs learns names its own entry file at the root of the tree.

Finding releases by tag was chosen over an index repository that lists the components: an index is a
second file to keep in step with every release, while a tag is the release itself (the person's
choice, 22 Nov 2026).

Folding the adapter once in `adapters/html` into the components was chosen over keeping it built in
beside found components:
two mechanisms would find adapters two ways, and a second adapter would still need the first.

## The component command

`obs-components` is the one command. It needs a Git checkout of obs, the one the core runs from; run
from no checkout, it fails naming the folder and the remedy, to run it from a clone. Through RUNME
it is `RUNME.sh components` (or `RUNME.ps1 components`): `obs-document components ARGS` runs `obs-components
ARGS`, since RUNME, se's, starts one command.

Every Git call the command makes goes through its one Git door, `components.GIT`: the checkout's
folder and remotes, a repository's tags, the names at the root of a release's tree and the fetch of
that tree. Its tests answer them from a fake host of repositories in memory, and one contract test
runs real Git ([Testing boundaries](quality.md#testing-boundaries)).

### Listing

`obs-components` with no argument lists the components:

1. It reads the checkout's remotes from the checkout's own Git configuration, in the order Git
   lists them (`git remote`), each by its address as configured (`remote.<name>.url`). Nothing
   else names a remote: no committed file, no setting, no Document and no build record.
2. It takes each remote's host and owner, the account or organization, from its address
   (`https://host/owner/repository`, `ssh://user@host/owner/repository` or
   `user@host:owner/repository`), and asks the host for that owner's repositories that carry the
   repository topic `component`.

   Each found repository is reached the way the remote is: its address is the remote's with the
   repository's name in place of the remote's.
3. It reads the tags of each repository (`git ls-remote --tags <address>`), without fetching its
   objects, and keeps the `v` releases: for each remote, its own repository first where the host lists
   it among the marked ones, then the owner's other marked repositories by name. A repository reached
   twice is read once, at its first place.
4. It reads the kind from the tree of each repository's newest release, the names at its root only:
   one shallow fetch of that release that leaves out the files' contents where the host allows it
   ([A component](#a-component)). The older releases of a repository are listed as that kind; an
   install reads the kind again from the tree it installs.
5. It lists each component once, with its kind, its installed version or `not installed`, its newest
   offered version and the repository that offers it ([Several remotes](#several-remotes)). A
   component whose newest version is above its installed one is marked as an update; an installed
   component no repository offers is listed with no newest version.

The host lists an owner's repositories through its own interface: on `github.com`, its repository
search for the topic `component` and the owner, with the person's login where there is one (`GH_TOKEN`,
`GITHUB_TOKEN`, or the token `gh auth token --hostname github.com` prints), which a private owner
needs. Every remote's host is searched the same way, whichever host it is: no host is special and
none is left out. The search goes to the host's interface at `api.<host>`, with the login for that
host (on a host other than `github.com`, `GH_ENTERPRISE_TOKEN`, `GITHUB_ENTERPRISE_TOKEN`, or the
token `gh auth token --hostname <host>` prints). Two remotes are two searches, one per owner.

A host or owner
that cannot be listed (no login for a private owner, a host that does not answer, an owner the
host does not know) is one warning line naming the remote, the host, the owner and why; that
remote's own repository is still read.

A repository that cannot be read is a warning naming its address and Git's message; the list still
shows what the others offer. A repository that offers no release is not listed.

Reading the remotes was chosen over a configured list of component sources: a person already adds a
remote to reach a repository, and a remote lives in the checkout's Git configuration, which nothing
commits.

Searching each remote's owner was chosen over taking each remote as one component repository: a fresh
clone would find no component until someone added a remote for each, while a clone should find every
component of the owner it came from, and another owner's components once any repository of that owner is
a remote (the person's requirement, work issue 860, 22 Nov 2026).

The owner and host come only from the checkout's Git configuration; nothing committed names them.

Reading a remote's own repository only where its host lists it as marked, or where the host cannot
list its owner, was chosen over reading every remote's own repository: obs's own repository carries
`v` releases too, so every listing would show obs as not a component of obs (work issue 878).

### Choosing

The person chooses what to install, update or remove; the command never does it unasked:

- `obs-components install NAME` installs the component's newest offered release, or updates an installed
  one to it.
- `obs-components install NAME VERSION` installs that release, older or newer than the installed one;
  VERSION is written `<major>.<minor>.<patch>`.
- `obs-components update NAME` updates an installed component to its newest offered release; a component
  that is not installed fails naming the remedy, `obs-components install NAME`.
- `obs-components remove NAME` removes an installed component.

NAME is compared without case. A name or version no repository offers fails naming it and the versions
offered, and a name whose repository is not a component of obs fails naming the reason.

An install is complete or absent: the release's tree is fetched into a temporary folder in the machine folder and
checked against its kind's entry file, its kind read from that tree, and only then replaces the installed version, so a failed
install leaves the installed version as it was.

An adapter's entry file is `adapter.json`, which
must name the component.

### Installed components

Installs go to the machine, as local themes do (the configuration note of the adapter once in
`adapters/html`, Local themes): the folder `obs` in the user's configuration folder (`$XDG_CONFIG_HOME` or `~/.config` on
Linux, `~/Library/Application Support` on macOS, `%APPDATA%` on Windows), or the folder
`OBS_LOCAL_FOLDER` names where it is set and not empty.

- `components/<name>/` holds the installed release's tree, never a checkout inside obs's repository.
- `components.json` beside it is the machine-local list: for each installed component its `name`, `kind`,
  `version` and `commit`. It names no remote, owner, host or path, and no committed file names it.

One version of a component is installed at a time: installing another version replaces it, so the
list holds each name once.

Installing one version only was chosen over installing versions side by side: a build that finds
one version per name needs no rule for which one a document meant (the person's requirement).

## Several remotes

A component that several repositories offer, under the same name and kind, is one component: the list shows it
once, and the machine installs it in one version only.

The release offered is the newest any of these repositories offers. Where several offer that
same version, it is taken from the first of them in the reading order of [Listing](#listing), so
from the first remote in the checkout's order. The list shows which repository offers it, so the
person sees where an install would come from (decision of 22 Nov 2026 on the work issue).

The same name under two kinds is two releases that cannot both be the component: the list shows it as
a warning naming each repository and kind, and offers neither until one of them stops.

## Naming a component

A document names a component only by its name. A manifest declares its style as `obs.style: <name>`,
and a call chooses its adapter as `--adapter NAME`; neither names a repository, a remote, a version
or a path.

A build finds the named component among the installed ones. One that is not installed, or is installed
as another kind, fails the build naming the field (or the option), the component and the remedy, to
run `obs-components install NAME`. An adapter's commands run from its installed folder, and a style's
installed folder reaches the adapter in the Document ([[architecture#Declared style]]).

An adapter is named by its own repository's name, which its release's `adapter.json` repeats
([Choosing](#choosing)). The adapter once in `adapters/html` has a repository of its own:
`obs-components install obs-html` installs it, and `--adapter obs-html` builds with it.

A build installs and fetches nothing: components come only from the checkout's remotes, and only when
the person chooses them with the component command.

## Recording what built a page

Every built page records the components that built it: for the adapter, the style and every other
component the build used, the `name`, `kind`, `version` and `commit` as `components.json` lists them.

The core passes them in the Document, so the adapter writes them into its artifact without reading
the machine's list, and the source archive's build record carries the same list
([[architecture#Source archive]]).

The Document's `components` lists them in the order the build found them, the adapter first and
then the style; a build without an adapter, which writes only the Document, lists only the style
the manifest declares, if any.

A rebuild uses the versions installed on its machine: where one differs from the recorded version,
the build warns naming the component and both versions, and where a recorded component is not installed it
fails as any build naming an absent component does.

The rebuild names the record it rebuilds with `--recorded-components FILE`, a JSON file whose
`components` lists them as the Document does: a source archive's `build-config.json`, whose recorded
command passes it.

The failure names the option, the list index, the component and the remedy, to run
`obs-components install NAME`. A build without the option checks nothing, since it rebuilds no record.

Warning on another installed version was chosen over refusing the rebuild: one version is installed at
a time ([Installed components](#installed-components)), so a refusal could only be cured by installing
the recorded version, often a downgrade, while the warning lets the rebuild show what changed (work
issue 859, 22 Nov 2026).
