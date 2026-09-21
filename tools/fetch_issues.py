#!/usr/bin/env python3
"""Fetch the issue tracker, and diff two fetches.

Pulls issues *and* comments, which are separate endpoints. The comments are the
point: an issue body states an intention, and the comments are where it gets
argued with, corrected or quietly dropped.

  python3 tools/fetch_issues.py --out /tmp/moc-issues.json
  python3 tools/fetch_issues.py --diff /tmp/moc-issues.prev.json /tmp/moc-issues.json

Unauthenticated is fine — roughly a dozen requests against a limit of 60 an
hour. Set GITHUB_TOKEN when iterating.
"""
import argparse, json, os, sys, time, urllib.error, urllib.request

REPO = 'CCI-MOC/MOC-issues'


def pages(repo, path, token, label):
    out, page = [], 1
    while True:
        sep = '&' if '?' in path else '?'
        url = f'https://api.github.com/repos/{repo}/{path}{sep}per_page=100&page={page}'
        req = urllib.request.Request(url, headers={
            'Accept': 'application/vnd.github+json', 'User-Agent': 'moc2-platform',
            **({'Authorization': 'Bearer ' + token} if token else {})})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                batch = json.load(r)
                remaining = r.headers.get('X-RateLimit-Remaining')
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                sys.exit(f'{label}: rate limited (HTTP {e.code}). Set GITHUB_TOKEN and retry.')
            sys.exit(f'{label} page {page}: HTTP {e.code} {e.reason}')
        if not batch:
            break
        out += batch
        print(f'  {label}: {len(out)} (rate remaining {remaining})', flush=True)
        if len(batch) < 100:
            break
        page += 1
        time.sleep(0.3)
    return out


def fetch(out_path, token):
    issues = [i for i in pages(REPO, 'issues?state=all', token, 'issues')
              if 'pull_request' not in i]
    comments = pages(REPO, 'issues/comments?sort=created&direction=asc', token, 'comments')
    with open(out_path, 'w') as fh:
        json.dump({'issues': issues, 'comments': comments}, fh)
    in_window = sum(1 for i in issues if i['created_at'] >= '2026-07-01')
    print(f'\nwrote {out_path}: {len(issues)} issues ({in_window} since 2026-07-01), '
          f'{len(comments)} comments')


def diff(a_path, b_path):
    """What actually moved, so a review reads the changes rather than the lot."""
    a, b = json.load(open(a_path)), json.load(open(b_path))
    ai = {i['number']: i for i in a['issues']}
    bi = {i['number']: i for i in b['issues']}

    added = sorted(set(bi) - set(ai))
    gone = sorted(set(ai) - set(bi))
    changed = [(n, ai[n]['state'], bi[n]['state'])
               for n in sorted(set(ai) & set(bi)) if ai[n]['state'] != bi[n]['state']]

    def counts(d):
        out = {}
        for c in d['comments']:
            n = str(c.get('issue_url', '')).rsplit('/', 1)[-1]
            if n.isdigit():
                out[int(n)] = out.get(int(n), 0) + 1
        return out
    ca, cb = counts(a), counts(b)
    # only issues present in both dumps: a issue new to this fetch has no prior
    # comment count to compare against, so "0 -> 3" there is scope, not activity
    both = set(ai) & set(bi)
    newly_commented = sorted(n for n in cb if n in both and cb[n] > ca.get(n, 0))

    print(f'issues {len(ai)} -> {len(bi)}   comments '
          f'{len(a["comments"])} -> {len(b["comments"])}')
    print(f'\nnew issues ({len(added)}):')
    for n in added:
        print(f'  #{n:<4} [{bi[n]["state"]:6}] {bi[n]["created_at"][:10]}  {bi[n]["title"][:64]}')
    if gone:
        print(f'\nabsent from the newer dump ({len(gone)}): {gone}')
    print(f'\nstate changed ({len(changed)}):')
    for n, was, now in changed:
        print(f'  #{n:<4} {was} -> {now}  {bi[n]["title"][:60]}')
    print(f'\nissues with new comments ({len(newly_commented)}), '
          f'among the {len(both)} present in both dumps:')
    for n in newly_commented:
        print(f'  #{n:<4} {ca.get(n, 0)} -> {cb[n]} comments  {bi[n]["title"][:56]}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default='/tmp/moc-issues.json')
    ap.add_argument('--diff', nargs=2, metavar=('OLD', 'NEW'))
    ap.add_argument('--github-token', default=os.environ.get('GITHUB_TOKEN'))
    a = ap.parse_args()
    if a.diff:
        diff(*a.diff)
    else:
        fetch(a.out, a.github_token)


if __name__ == '__main__':
    main()
