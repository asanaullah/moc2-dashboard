# MOC 2.0 — Platform State dashboard

A single static page showing the current state of the MOC 2.0 / Open Accelerator
platform: clusters and their node pools, which components land where, tenant
projects, network isolation, the RFC board, decisions taken, discoveries, and
capacity. It rebuilds itself daily from two upstream repositories.

No framework, no build step, no back end. It is `index.html`, one stylesheet,
one script and one generated data file, so it works on GitHub Pages and equally
well opened straight off disk.

## What it reads, and what it therefore knows

| Source | Gives |
|---|---|
| [`CCI-MOC/oac-apps`](https://github.com/CCI-MOC/oac-apps) | clusters, node pools, components per cluster, tenant projects, isolation tiers, the chart catalogue, MetalLB pools and storage networks |
| [`CCI-MOC/ansible-switches`](https://github.com/CCI-MOC/ansible-switches) | the VLAN catalogue, switch inventory, and which ports actually carry each VLAN |
| [`CCI-MOC/open-accelerator-infra`](https://github.com/CCI-MOC/open-accelerator-infra) | VLAN-to-CIDR map, per-node NIC assignments and BMC addresses, cluster membership, hub node counts |
| [`CCI-MOC/moc-keycloak`](https://github.com/CCI-MOC/moc-keycloak) | realm settings, identity providers, per-cluster OIDC clients, groups, authentication flows |
| [`CCI-MOC/MOC-issues`](https://github.com/CCI-MOC/MOC-issues) | RFC board, weekly throughput, recent activity, open/closed totals |
| `data/curated.json` | decisions, discoveries, the programme timeline, diagram blocks, hardware profiles |

The three repo parsers are joined conservatively: cluster membership comes from
the Ansible inventory, per-node networking from the hardware document, and a
storage VLAN is matched to a cluster only on an exact CIDR match with what
Portworx declares. A node in one source and not the other keeps what is known
and leaves the rest blank — nothing is inferred across a join.

**It shows declared configuration, not live cluster state.** Everything about a
cluster is read from Git, so "8 nodes" means the node-pool replicas committed in
`hosted-clusters/…/values.yaml`, not eight nodes currently `Ready`. Nothing here
talks to an API server. The page says this on its face rather than implying it is
monitoring.

Two consequences worth knowing:

- **GPUs per node is not in `oac-apps`.** It is a property of the machine, so it
  lives in `data/curated.json` under `hardware_profiles`. Set `"gpus": null` when
  the number is not known: the pool then renders as **needs data**, is excluded
  from GPU totals, and the totals are labelled *partial* (`20+`) rather than
  quietly reported as complete. An early version guessed 8 GPUs/node for the
  H100s and so reported double the real count — hence the rule: no guesses, a
  hook instead.
- **Hub clusters do not declare their own nodes** in `oac-apps` — only hosted
  clusters have `nodePools`. The count now comes from the
  `open-accelerator-infra` inventory (6 for prod, 3 for dev) and the card says
  so. The `hub_nodes` hook in `data/curated.json` remains as a fallback.
- **There are no billing figures.** The metric invoices are built from
  (`kube_pod_resource_request`) is unavailable on hosted control planes, because
  the scheduler that publishes it runs on the hub. That is
  [MOC-issues#481](https://github.com/CCI-MOC/MOC-issues/issues/481), not a gap in
  this dashboard. The Capacity section shows declared capacity instead.

## Why some of the data is hand-maintained

`decisions` and `discoveries` in `data/curated.json` cannot be parsed out of
anything. A decision and the alternative it beat live in issue comments, in prose.
So they are written by hand — but every entry cites an issue number, and the
generator warns if a cited issue is not in the tracker, so the citations cannot
rot silently.

## Running it

```sh
pip install pyyaml

# against local checkouts and an API dump
python3 tools/build_snapshot.py \
  --oac-apps ../oac-apps \
  --ansible-switches ../ansible-switches \
  --infra ../open-accelerator-infra \
  --keycloak ../moc-keycloak \
  --issues ../raw_issues.json

# or straight from GitHub
git clone --depth 1 https://github.com/CCI-MOC/oac-apps /tmp/oac-apps
GITHUB_TOKEN=... python3 tools/build_snapshot.py --oac-apps /tmp/oac-apps
```

That writes `data/snapshot.js`, which is a plain `window.MOC_DATA = {...}`
assignment rather than JSON fetched at runtime — so the page also works from
`file://`, where `fetch()` of a local file is blocked.

To view it: open `index.html`, or `python3 -m http.server` and browse to it.

## Deploying

`.github/workflows/update.yml` runs daily at 06:17 UTC, on push to `main`, and on
demand. It checks out both repos, regenerates the snapshot, sanity-checks that it
is not empty, and publishes to GitHub Pages.

To enable: **Settings → Pages → Source: GitHub Actions**. The default
`GITHUB_TOKEN` is enough for public repos; for private ones add a PAT and
uncomment the `token:` line in the workflow.

The workflow fails loudly rather than publishing an empty page if a parser
returns nothing — a silently blank dashboard is worse than a failed build.

## Layout

```
index.html              structure only; every value is rendered by app.js
assets/style.css        design tokens, light/dark, components
assets/app.js           rendering and the four charts (plain SVG, no chart library)
data/snapshot.js        generated — do not edit
data/curated.json       hand-maintained: decisions, discoveries, timeline, hardware
tools/build_snapshot.py the repo + issue parsers, and the join
tools/parse_network.py   switches, VLANs, CIDRs and the node inventory
tools/parse_identity.py  keycloak realm, providers, OIDC clients, groups, flows
```

### Notes on the charts

They are hand-drawn SVG rather than a charting library, for the same reason the
page has no framework: one fewer dependency to break, and full control of the
theming. Series colours come from a palette validated for colour-vision
deficiency against both surfaces; sections are assigned slots **in the palette's
fixed order**, because that ordering is what guarantees neighbouring pairs stay
distinguishable. If you add a series, take the next slot rather than picking a
colour you like.
