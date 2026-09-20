# Refreshing the analysis

The dashboard has two halves with different refresh mechanisms.

| | Repo-derived | Issue-derived and analysed |
|---|---|---|
| File | `data/snapshot.js` | `data/analysis.js` |
| Built by | `tools/build_snapshot.py` | `tools/build_analysis.py` |
| Refreshed by | the hourly GitHub Actions workflow | a person, following this document |
| In git | no, it is a build artifact | **yes, it is the only copy** |
| Content | clusters, node pools, components, namespaces, projects, VLANs, hardware, identity, charts | RFC board, weekly activity, recent issues, decisions, discoveries, timeline, diagram blocks |

The split exists because the first half is extraction and the second half is
judgement. A scheduled job can re-read a values file correctly every hour. It
cannot decide that a particular issue thread describes a discovery, what its
severity is, or whether the thing it describes is still true.

## Why the analysis is not automated

This was measured rather than assumed. A keyword search of the tracker for
failure-analysis language (`root cause`, `turns out`, `the problem was`,
`regression`, `workaround`, and similar) over titles, bodies and all 787
comments returns 11 issues out of 352. Of the six discoveries currently written
up, that search finds **one**. Of the eleven it does find, most are not
discoveries at all — one is about how to split large issues, another is a
dashboard development task.

So the detector has poor precision and poor recall at the same time, and
shipping it would produce a list that looks authoritative and is not. The
machine does the part it is reliable at — checking that citations resolve and
reporting when an entry has been overtaken — and a person does the reading.

## What the generator checks for you

`build_analysis.py` never edits a curated entry. For each one it resolves the
cited issue and reports:

| Flag | Meaning |
|---|---|
| `missing_issue` | the cited number is not in the tracker |
| `never_reviewed` | the entry has no `reviewed_at` |
| `updated_since_review` | the issue changed after `reviewed_at` |
| `says_resolved_issue_open` | a discovery written up as `fixed`/`documented` whose issue is still open |
| `says_open_issue_closed` | a discovery written up as `open` whose issue has been closed |

The count appears in the page header as *N to review*, and each affected
discovery carries a badge. A flag is a prompt to re-read, not a verdict — an
issue can legitimately stay open after the thing it describes is fixed, which
is exactly the case for #441 and #491 today.

## The procedure

### 1. Pull the issues

```sh
cd moc2-dashboard

# either: a fresh dump (preferred — it can be diffed and kept)
python3 - <<'PY'
import json, urllib.request, os
issues, page = [], 1
while True:
    req = urllib.request.Request(
        f'https://api.github.com/repos/CCI-MOC/MOC-issues/issues'
        f'?state=all&per_page=100&page={page}',
        headers={'Accept': 'application/vnd.github+json',
                 'User-Agent': 'moc2-dashboard',
                 **({'Authorization': 'Bearer ' + os.environ['GITHUB_TOKEN']}
                    if os.environ.get('GITHUB_TOKEN') else {})})
    batch = json.load(urllib.request.urlopen(req))
    if not batch: break
    issues += [i for i in batch if 'pull_request' not in i]
    if len(batch) < 100: break
    page += 1
json.dump({'issues': issues}, open('/tmp/moc-issues.json', 'w'))
print(len(issues), 'issues')
PY

# or: straight from the API at build time
GITHUB_TOKEN=... python3 tools/build_analysis.py
```

Comments are a separate endpoint and are not in the issue payload. Pull them
too when doing a full review — most discoveries are described in comments
rather than in issue bodies.

### 2. See what changed

```sh
python3 tools/build_analysis.py --issues /tmp/moc-issues.json
```

Read the summary line. `N need review` is the work list. Then look at what is
new since the last dump: issues opened or closed, and anything whose
`updated_at` moved.

### 3. Read, and decide

For each flagged entry and each candidate, the questions are:

- **Is it a discovery?** Something was found that was not expected, and it
  changed what the team did. A planned task completing is not a discovery. A
  bug report with no consequence is not either.
- **Is it still true?** The most common drift is an entry describing a
  situation that has since been fixed, or a fix that has since regressed.
- **What is the severity?** `critical` (a security or correctness hole),
  `serious` (blocks or distorts something that matters, like the billing
  metric), `warning` (real but contained).
- **What is the status?** `fixed`, `open`, `documented`.

### 4. Validate against the repositories

This is the step that makes the analysis trustworthy, and it is why the two
halves live in the same project. Claims in issue threads can be checked against
configuration:

| A claim like… | Check |
|---|---|
| "tenant isolation is fixed" | `oac-apps/charts/restrict-tenant-networks/templates/` and the per-project NetworkPolicy in `charts/user-projects` |
| "egress was restored" | the `except` list on the namespace NetworkPolicy |
| "the proxy is only on one cluster" | which clusters get `object-storage-proxy` in the ApplicationSets and placements |
| "a cluster is being prepared" | `hosted-clusters/`, the Keycloak OIDC clients in `moc-keycloak/main.tf`, and the VLANs in `ansible-switches` |
| "the node is broken" | the flag column in `open-accelerator-infra/docs/hardware-and-network-configuration.md` |

Where a claim cannot be checked against configuration, say so in the entry
rather than implying it was verified.

### 5. Update `data/curated.json`

Entry shapes:

```jsonc
// discoveries[]
{
  "date": "2026-08-26",              // when it was found
  "title": "Cross-namespace isolation bypassed using FQDN",
  "severity": "critical",            // critical | serious | warning
  "status": "fixed",                 // fixed | open | documented
  "issue": 441,                      // must exist in the tracker
  "found_by": "UAT harness",
  "detail": "What was found, and what it forced.",
  "reviewed_at": "2026-09-20"        // bump this whenever you re-check
}

// decisions[]
{
  "date": "2026-08-17",
  "title": "Argo CD + Helm + ACM Placements instead of ai-ivp",
  "area": "Configuration",
  "rejected": "The consultants' Ansible-driven pattern",
  "why": "Simpler and offers more control over what is deployed",
  "issue": 51,
  "reviewed_at": "2026-09-20"
}
```

`reviewed_at` is the load-bearing field. Bump it when you have actually
re-read the thread, not when you edit the wording — it is what the drift check
measures against.

The same file also holds `timeline`, `timeline_marker`, `topology` (diagram
blocks, each needing `grounding: "repo"` or a valid `issue`), plus
`hardware_profiles` and `hub_nodes`, which are read by the **repo** generator
rather than this one.

### 6. Regenerate and commit

```sh
python3 tools/build_analysis.py --issues /tmp/moc-issues.json
git add data/analysis.js data/curated.json
git commit -m "Refresh analysis"
git push
```

Pushing triggers the workflow, which rebuilds `data/snapshot.js` from the repos
and publishes both halves together.

## If you are handing this to Claude

Point at this file and give it the issue dump. A workable prompt:

> Follow ANALYSIS.md. Here is a fresh issue dump at `/tmp/moc-issues.json`.
> Run the drift check, review the flagged entries against the repos in the
> parent directory, tell me what changed and what you propose to add or amend,
> then update `data/curated.json` and regenerate `data/analysis.js`.

Two expectations worth stating explicitly, because they are the ways this goes
wrong:

- **Propose before writing.** The curated file is the human-judgement half of
  the dashboard; changes to it should be reviewed, not applied silently.
- **No invention.** If a claim cannot be traced to an issue or a repository,
  it does not go in. An entry whose severity or status is a guess is worse than
  no entry, because the dashboard presents it with the same weight as a checked
  one.
