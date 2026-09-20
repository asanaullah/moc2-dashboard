#!/usr/bin/env python3
"""Build data/analysis.js — everything derived from the issue tracker.

This is deliberately NOT run by the scheduled workflow. The workflow refreshes
what can be extracted mechanically from the configuration repositories; this
script covers the material that needs a person to read the tracker and decide
what it means. See ANALYSIS.md for the procedure.

It emits two kinds of content, kept distinct:

  extracted   RFC board, weekly throughput, recent activity, open/closed totals.
              Mechanical, but sourced from the tracker rather than a repo.

  analysed    decisions, discoveries, the programme timeline and the diagram
              blocks, all from data/curated.json. Written by a person; the
              generator only verifies the citations and reports drift.

Drift checking is the point. Every curated entry cites an issue and carries a
`reviewed_at` date. This script compares that date against the issue's current
state, so the dashboard can say which write-ups have been overtaken by events
instead of presenting stale analysis as current.

Usage:
  python3 tools/build_analysis.py --issues ../raw_issues.json
  python3 tools/build_analysis.py --github-token "$GH_TOKEN"
"""
import argparse, collections, datetime, json, os, re, sys

# The tracker predates MOC 2.0 by years. Everything here is scoped to the
# programme window by default so counts stay comparable and the weekly chart
# does not carry five years of unrelated history.
DEFAULT_SINCE = '2026-07-01'

ISSUES_REPO = 'CCI-MOC/MOC-issues'
RFC_RE = re.compile(r'RFC\s*(\d{1,2})\b', re.I)
EMAIL_RE = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}')


def fetch_paged(repo, path, token, label):
    import urllib.request
    out, page = [], 1
    while True:
        sep = '&' if '?' in path else '?'
        url = f'https://api.github.com/repos/{repo}/{path}{sep}per_page=100&page={page}'
        req = urllib.request.Request(url, headers={
            'Accept': 'application/vnd.github+json', 'User-Agent': 'moc2-dashboard',
            **({'Authorization': 'Bearer ' + token} if token else {})})
        with urllib.request.urlopen(req, timeout=60) as r:
            batch = json.load(r)
        if not batch:
            break
        out += batch
        if len(batch) < 100:
            break
        page += 1
    return out


def threads(issues, comments, limit=15):
    """Issues that have been discussed, most recently commented first.

    The comment count, the participants and the latest comment are extracted;
    what the thread *means* is not. A one-line summary can be supplied per issue
    in curated.json under `issue_summaries`, and is shown in preference to the
    raw excerpt.
    """
    by = collections.defaultdict(list)
    for c in comments:
        m = re.search(r'/issues/(\d+)$', str(c.get('issue_url', '')))
        if m:
            by[int(m.group(1))].append(c)
    keep = {i['number'] for i in issues}
    out = []
    for num, cs in by.items():
        if num not in keep:
            continue
        cs.sort(key=lambda c: c['created_at'])
        last = cs[-1]
        issue = next(i for i in issues if i['number'] == num)
        body = re.sub(r'\s+', ' ', (last.get('body') or '')).strip()
        # Comment text is incidental free text and occasionally names people by
        # email. The tracker is public, so this is not a disclosure, but the
        # dashboard has no reason to re-publish addresses -- the structured
        # `requester` on a project is where an address is actually the point.
        body = EMAIL_RE.sub('[email]', body)
        out.append({
            'num': num, 'title': issue['title'], 'state': issue['state'],
            'labels': [l['name'] for l in issue.get('labels', [])],
            'comments': len(cs),
            'participants': sorted({(c.get('user') or {}).get('login')
                                    for c in cs if (c.get('user') or {}).get('login')}),
            'opened': issue['created_at'][:10],
            'last_comment_at': last['created_at'][:10],
            'last_comment_by': (last.get('user') or {}).get('login'),
            'last_comment': body[:400] + ('…' if len(body) > 400 else ''),
        })
    out.sort(key=lambda t: t['last_comment_at'], reverse=True)
    return out[:limit]


def fetch_issues_api(repo, token):
    import urllib.request
    issues, page = [], 1
    while True:
        url = (f'https://api.github.com/repos/{repo}/issues'
               f'?state=all&per_page=100&page={page}')
        req = urllib.request.Request(url, headers={
            'Accept': 'application/vnd.github+json',
            'User-Agent': 'moc2-dashboard',
            **({'Authorization': 'Bearer ' + token} if token else {})})
        with urllib.request.urlopen(req, timeout=60) as r:
            batch = json.load(r)
        if not batch:
            break
        issues += [i for i in batch if 'pull_request' not in i]
        if len(batch) < 100:
            break
        page += 1
    return issues


def week_of(iso):
    d = datetime.date.fromisoformat(iso[:10])
    return (d - datetime.timedelta(days=d.weekday())).isoformat()


def classify_rfc(issue):
    if issue.get('state') == 'closed':
        return 'approved'
    body = (issue.get('body') or '').lower()
    if 'draft' in body or 'under review' in body or issue.get('assignees'):
        return 'in-review'
    return 'open'


def extract(issues):
    weekly = collections.defaultdict(lambda: {'opened': 0, 'closed': 0})
    for i in issues:
        weekly[week_of(i['created_at'])]['opened'] += 1
        if i.get('closed_at'):
            weekly[week_of(i['closed_at'])]['closed'] += 1

    rfcs = []
    for i in issues:
        if not re.search(r'\bRFC\b', i['title'], re.I):
            continue
        m = RFC_RE.search(i['title'])
        if not m:
            continue
        title = re.sub(r'^.*?RFC\s*\d{1,2}\s*[-–—:]?\s*', '', i['title'], flags=re.I)
        title = re.sub(r'\s*[-–—]?\s*(Creation and Sign off)\s*$', '', title, flags=re.I).strip()
        rfcs.append({'id': f'RFC {int(m.group(1)):02d}', 'num': int(m.group(1)),
                     'title': title or i['title'], 'status': classify_rfc(i),
                     'issue': i['number'], 'updated': i['updated_at'][:10],
                     'owner': (i.get('assignee') or {}).get('login') if i.get('assignee') else None})
    rank = {'approved': 0, 'in-review': 1, 'open': 2}
    best = {}
    for r in sorted(rfcs, key=lambda r: (rank[r['status']], r['updated'])):
        best.setdefault(r['num'], r)

    recent = sorted(issues, key=lambda i: i['updated_at'], reverse=True)[:12]
    return {
        'issues_weekly': [{'week': w, **weekly[w]} for w in sorted(weekly)],
        'issues_recent': [{'num': i['number'], 'title': i['title'], 'state': i['state'],
                           'labels': [l['name'] for l in i.get('labels', [])],
                           'updated': i['updated_at'][:10]} for i in recent],
        'rfcs': sorted(best.values(), key=lambda r: r['num']),
        'issue_totals': {
            'open': sum(1 for i in issues if i['state'] == 'open'),
            'closed': sum(1 for i in issues if i['state'] == 'closed'),
            'count': len(issues),
            'window': (min(i['created_at'] for i in issues)[:10] + ' → ' +
                       max(i['updated_at'] for i in issues)[:10]),
        },
    }


def check_drift(entries, by_number, kind):
    """Compare each curated write-up against the issue it cites.

    Reports, never rewrites: the dashboard shows the badge and a person decides
    whether the analysis still holds.
    """
    out, stale = [], 0
    for e in entries:
        e = dict(e)
        n = e.get('issue')
        iss = by_number.get(n)
        d = {}
        if n and not iss:
            d['missing_issue'] = True
        elif iss:
            d['issue_state'] = iss['state']
            d['issue_updated'] = iss['updated_at'][:10]
            rev = e.get('reviewed_at')
            if rev and iss['updated_at'][:10] > rev:
                d['updated_since_review'] = True
            if kind == 'discoveries':
                says_done = e.get('status') in ('fixed', 'documented')
                if says_done and iss['state'] == 'open':
                    d['says_resolved_issue_open'] = True
                if e.get('status') == 'open' and iss['state'] == 'closed':
                    d['says_open_issue_closed'] = True
            if not rev:
                d['never_reviewed'] = True
        if any(d.get(k) for k in ('updated_since_review', 'says_resolved_issue_open',
                                  'says_open_issue_closed', 'missing_issue', 'never_reviewed')):
            stale += 1
        e['drift'] = d
        out.append(e)
    return out, stale


def ground_topology(topo, known):
    def ok(b):
        if not isinstance(b, dict):
            return False
        if b.get('grounding') == 'repo' or b.get('issue') in known:
            return True
        print(f'  ! dropping ungrounded diagram block '
              f'{b.get("id") or b.get("label")!r}', file=sys.stderr)
        return False
    out = {}
    for k, v in (topo or {}).items():
        if k.startswith('_'):
            out[k] = v
        elif k == 'datacenter' and isinstance(v, dict):
            dc = {kk: vv for kk, vv in v.items() if kk not in ('edge', 'storage')}
            dc['edge'] = [b for b in (v.get('edge') or []) if ok(b)]
            st = v.get('storage')
            dc['storage'] = st if (st and ok(st)) else None
            out[k] = dc
        elif isinstance(v, list):
            out[k] = [b for b in v if ok(b)]
        else:
            out[k] = v
    return out


def main():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap = argparse.ArgumentParser()
    ap.add_argument('--issues', help='path to a MOC-issues API dump (json)')
    ap.add_argument('--github-token', default=os.environ.get('GITHUB_TOKEN'))
    ap.add_argument('--since', default=DEFAULT_SINCE,
                    help='only consider issues created on/after this date')
    ap.add_argument('--curated', default=os.path.join(here, 'data', 'curated.json'))
    ap.add_argument('--out', default=os.path.join(here, 'data', 'analysis.js'))
    a = ap.parse_args()

    if a.issues:
        raw = json.load(open(a.issues))
        issues = raw['issues'] if isinstance(raw, dict) and 'issues' in raw else raw
        comments = raw.get('comments', []) if isinstance(raw, dict) else []
        via = 'api dump: ' + os.path.basename(a.issues)
    else:
        issues = fetch_issues_api(ISSUES_REPO, a.github_token)
        comments = fetch_paged(ISSUES_REPO, 'issues/comments?sort=created&direction=asc',
                               a.github_token, 'comments')
        via = 'github api'
    total = len(issues)
    issues = [i for i in issues if i['created_at'] >= a.since]
    by_number = {i['number']: i for i in issues}
    print(f'issues: {len(issues)} in scope (since {a.since}) of {total} via {via}; '
          f'{len(comments)} comments')

    ex = extract(issues)
    disc = threads(issues, comments)
    print(f"  {len(ex['rfcs'])} RFCs, {len(ex['issues_weekly'])} weeks, "
          f"{ex['issue_totals']['open']} open / {ex['issue_totals']['closed']} closed")

    curated = json.load(open(a.curated)) if os.path.exists(a.curated) else {}
    summaries = curated.get('issue_summaries') or {}
    decisions, d_stale = check_drift(curated.get('decisions', []), by_number, 'decisions')
    discoveries, x_stale = check_drift(curated.get('discoveries', []), by_number, 'discoveries')
    print(f'  curated: {len(decisions)} decisions ({d_stale} need review), '
          f'{len(discoveries)} discoveries ({x_stale} need review)')

    out = {
        'generated_at': datetime.datetime.now(datetime.timezone.utc)
                        .replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
        'source': {'repo': ISSUES_REPO, 'via': via, 'count': len(issues)},
        'needs_review': d_stale + x_stale,
        'scope': {'since': a.since, 'in_scope': len(issues), 'tracker_total': total},
        'updated_issues': [dict(t, summary=summaries.get(str(t['num']), {}).get('summary'),
                                summary_reviewed=summaries.get(str(t['num']), {}).get('reviewed_at'))
                           for t in disc],
        **ex,
        'decisions': decisions,
        'discoveries': discoveries,
        'timeline': curated.get('timeline', []),
        'timeline_marker': curated.get('timeline_marker'),
        'topology': ground_topology(curated.get('topology', {}), set(by_number)),
    }
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, 'w') as fh:
        fh.write('/* Generated by tools/build_analysis.py — issue-derived and curated content.\n'
                 '   NOT refreshed by the scheduled workflow; see ANALYSIS.md. */\n'
                 'window.MOC_ANALYSIS = ')
        json.dump(out, fh, indent=1, ensure_ascii=False)
        fh.write(';\n')
    print('wrote', a.out, f'({os.path.getsize(a.out)/1024:.0f} KB)')


if __name__ == '__main__':
    main()
