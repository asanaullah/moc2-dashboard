# MOC 2.0 — Platform State dashboard

A static page showing the current state of the MOC 2.0 / Open Accelerator
platform: clusters and their node pools, which components are deployed where,
tenant projects, network isolation, VLANs, identity configuration, the RFC
board, decisions taken, discoveries, and capacity.

The page is `index.html` plus a stylesheet, three scripts and two data files:
`data/snapshot.js`, generated from the repositories, and `data/analysis.js`,
generated from the issue tracker and the curated file. There is no framework and
no build step, so it can be served by GitHub Pages or opened directly from disk.
A scheduled GitHub Actions workflow regenerates the snapshot every hour; the
analysis is refreshed by hand (see [ANALYSIS.md](ANALYSIS.md)).

## Sources

| Source | Provides |
|---|---|
| [`CCI-MOC/oac-apps`](https://github.com/CCI-MOC/oac-apps) | clusters, node pools, components per cluster, tenant projects, isolation tiers, the chart catalogue, MetalLB pools, storage networks |
| [`CCI-MOC/ansible-switches`](https://github.com/CCI-MOC/ansible-switches) | VLAN catalogue, switch inventory, which ports carry each VLAN |
| [`CCI-MOC/open-accelerator-infra`](https://github.com/CCI-MOC/open-accelerator-infra) | VLAN-to-CIDR map, per-node NIC assignments and BMC addresses, cluster membership, hub node counts |
| [`CCI-MOC/moc-keycloak`](https://github.com/CCI-MOC/moc-keycloak) | realm settings, identity providers, per-cluster OIDC clients, groups, authentication flows |
| [`CCI-MOC/MOC-issues`](https://github.com/CCI-MOC/MOC-issues) | RFC board, weekly throughput, recent activity, open/closed totals |
| `data/curated.json` | decisions, discoveries, the programme timeline, diagram blocks, hardware profiles |

All five repositories are public, so the workflow needs no secrets beyond the
default `GITHUB_TOKEN`.

### How the sources are joined

Cluster membership comes from the Ansible inventory in
`open-accelerator-infra`, which carries an explicit `cluster:` group variable.
Per-node networking comes from that repository's hardware document. The two are
joined on `node_name`.

A storage VLAN is attached to a cluster only when its CIDR exactly matches the
CIDR that Portworx declares for that cluster in `oac-apps`.

Where a node appears in one source and not the other, the fields that source
provides are kept and the rest are left empty. No value is inferred across a
join.

## What the dashboard does not know

It shows declared configuration, not live cluster state. Everything about a
cluster is read from Git, so "8 nodes" means the node-pool replicas committed in
`hosted-clusters/…/values.yaml`, not eight nodes currently `Ready`. Nothing here
contacts a cluster API server, and the page states this at the top.

Three specific gaps:

- **GPUs per node is not recorded in any of the repositories.** It is a property
  of the machine, so it lives in `data/curated.json` under `hardware_profiles`.
  Set `"gpus": null` when the number is unknown. The pool is then rendered as
  *needs data*, excluded from GPU totals, and the totals are labelled *partial*
  (for example `20+`). An earlier version assumed 8 GPUs per node for the H100s
  and reported double the real figure, which is why unknown values are left as
  hooks instead of being estimated.
- **Hub clusters do not declare their own nodes in `oac-apps`**; only hosted
  clusters have `nodePools`. The count comes from the `open-accelerator-infra`
  inventory instead (6 for prod, 3 for dev), and the cluster card names that
  source. The `hub_nodes` entry in `data/curated.json` is a fallback for when
  the inventory does not cover a hub.
- **There are no billing figures.** The metric invoices are derived from
  (`kube_pod_resource_request`) is published by the kube-scheduler, which under
  hosted control planes runs on the hub rather than in the workload cluster.
  See [MOC-issues#481](https://github.com/CCI-MOC/MOC-issues/issues/481). The
  Capacity section reports declared capacity instead.

## Hand-maintained data

`decisions` and `discoveries` in `data/curated.json` cannot be parsed from any
source. A decision and the alternative it was chosen over are recorded in issue
comments as prose, not in structured fields, so these entries are written by
hand. Each one cites an issue number, and `build_snapshot.py` prints a warning
if a cited issue is not present in the tracker.

The same file holds the programme timeline, the diagram blocks, and the
hardware profiles.

## Running the generator

```sh
pip install pyyaml

# from local checkouts (check that each is on main first)
python3 tools/build_snapshot.py \
  --oac-apps ../oac-apps \
  --ansible-switches ../ansible-switches \
  --infra ../open-accelerator-infra \
  --keycloak ../moc-keycloak

# or from fresh clones
for r in oac-apps ansible-switches open-accelerator-infra moc-keycloak; do
  git clone --depth 1 "https://github.com/CCI-MOC/$r" "/tmp/$r"
done
python3 tools/build_snapshot.py \
  --oac-apps /tmp/oac-apps \
  --ansible-switches /tmp/ansible-switches \
  --infra /tmp/open-accelerator-infra \
  --keycloak /tmp/moc-keycloak
```

`--oac-apps` is required. Omitting any other argument skips that parser; the
sections it feeds then report that the data is absent rather than failing.

`build_snapshot.py` does not read the issue tracker. The RFC board, issue
activity, decisions and discoveries come from `tools/build_analysis.py`, which
takes an issues dump (`--issues`) or reads the GitHub API (`--github-token`);
[ANALYSIS.md](ANALYSIS.md) describes that procedure.

The generator writes `data/snapshot.js` as a `window.MOC_DATA = {...}`
assignment rather than as JSON loaded at runtime, because a page opened over
`file://` cannot `fetch()` a local file.

To view the page, open `index.html`, or run `python3 -m http.server` and browse
to it.

## Deploying

`.github/workflows/update.yml` runs hourly at 17 minutes past the hour, on push
to `main`, and on demand. It checks out the four source repositories, regenerates the snapshot,
verifies that clusters, charts, issues, VLAN/CIDR rows and the Keycloak realm
all parsed, and publishes to GitHub Pages.

To enable Pages: **Settings → Pages → Source: GitHub Actions**. The default
`GITHUB_TOKEN` is sufficient for public repositories; for a private one, add a
PAT as a secret and uncomment the `token:` line on the relevant checkout step.

If any parser returns nothing the workflow fails instead of publishing, so a
broken source produces a failed build rather than a blank page.

## Layout

```
index.html                 page structure; all values are rendered by app.js
assets/style.css           design tokens, light and dark themes, components
assets/app.js              rendering, and the timeline, issues and capacity charts
assets/architecture.js     the architecture diagram
data/snapshot.js           generated from the repositories — do not edit, not in git
data/analysis.js           generated from issues + curated.json — committed, the only copy
data/curated.json          decisions, discoveries, timeline, diagram blocks, hardware
tools/build_snapshot.py    oac-apps parser and the top-level join
tools/parse_network.py     switches, VLANs, CIDRs, node inventory
tools/parse_identity.py    Keycloak realm, providers, OIDC clients, groups, flows
tools/build_analysis.py    RFC board, issue activity, curated-entry drift check
tools/fetch_issues.py      issues + comments dump, and a diff between two dumps
.github/workflows/update.yml  scheduled rebuild and Pages deployment
```

## Charts

The charts are generated as SVG by the page rather than drawn with a charting
library, which keeps the theming under the same CSS custom properties as the
rest of the page and avoids a runtime dependency.

Series colours are taken from a categorical palette validated for colour-vision
deficiency against both the light and dark surfaces. Sections are assigned
palette slots in the palette's fixed order, because that ordering is what keeps
adjacent pairs distinguishable; assigning slots out of order once produced two
greens next to each other. When adding a series, take the next slot rather than
choosing a colour by eye.

## Diagram conventions

The architecture diagram distinguishes three cases:

- Solid boxes and connectors are read from the repositories.
- Dashed boxes are described in the issue tracker and cite an issue number.
- Anything unknown is left blank and unconnected. Components whose connections
  are not recorded anywhere — the bastion host, for instance — are drawn without
  connectors rather than wired up speculatively.

`build_snapshot.py` drops any diagram block that cites neither a repository nor
an issue, and prints a warning naming it.
