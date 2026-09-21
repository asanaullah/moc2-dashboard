#!/usr/bin/env python3
"""Build data/snapshot.js for the MOC 2.0 dashboard from real sources.

Two parsers:

  repo parser    CCI-MOC/oac-apps working tree  -> clusters, node pools, charts,
                 which component lands on which cluster, tenant projects,
                 network-policy tiers, per-hub drop-in apps.

Everything here is mechanical extraction from configuration repositories, and
it is what the scheduled workflow refreshes. Anything that needs a person to
read the issue tracker and decide what it means lives in
tools/build_analysis.py instead; see ANALYSIS.md.

What this CANNOT know, and therefore does not claim: live cluster state. It
reads *declared* configuration from Git, so "nodes" means node-pool replicas as
committed, not nodes currently Ready. Anything needing a live API server or the
metrics stack (pod counts, real GPU availability, billing) is out of scope --
billing in particular is blocked upstream by MOC-issues#481.

Usage:
  python3 tools/build_snapshot.py --oac-apps ../oac-apps \
      --ansible-switches ../ansible-switches --infra ../open-accelerator-infra \
      --keycloak ../moc-keycloak
"""
import argparse, datetime, json, os, re, subprocess, sys, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_network, parse_identity

try:
    import yaml
except ImportError:
    sys.exit('pyyaml is required: pip install pyyaml')

APPS_REPO = 'CCI-MOC/oac-apps'

# Node-pool resource classes map to hardware. GPUs-per-node is a property of the
# machine, not of oac-apps, so it is recorded here with its source and surfaced
# as "from hardware profile" rather than presented as measured.
# Fallback only. The real table lives in data/curated.json under
# "hardware_profiles" so it can be corrected without editing code: GPUs-per-node
# is a property of the machine and is not recorded anywhere in oac-apps.
HARDWARE_FALLBACK = {
    'fc830': {'label': 'Dell FC830', 'gpus': 0, 'kind': 'cpu'},
    'fc430': {'label': 'Dell FC430', 'gpus': 0, 'kind': 'cpu'},
}
HARDWARE = dict(HARDWARE_FALLBACK)

HARDWARE_SOURCE = ('GPUs per node come from data/curated.json, not from oac-apps, which does not record it; node counts are node-pool replicas as committed.')


# --------------------------------------------------------------------------
# repo parser
# --------------------------------------------------------------------------
def load_yaml(path):
    try:
        with open(path) as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return {}
    except yaml.YAMLError as e:
        print(f'  ! skipping unparseable {path}: {e}', file=sys.stderr)
        return {}


def git_meta(root):
    def run(*a):
        try:
            return subprocess.run(['git', '-C', root] + list(a), capture_output=True,
                                  text=True, check=True).stdout.strip()
        except Exception:
            return None
    return {'repo': APPS_REPO, 'commit': (run('rev-parse', '--short', 'HEAD') or 'unknown'),
            'branch': run('rev-parse', '--abbrev-ref', 'HEAD') or 'unknown',
            'committed_at': run('log', '-1', '--format=%cI')}


def parse_component_lists(root):
    """Which components each ApplicationSet deploys, and to which placement."""
    out = {'hub': [], 'managed': {}}
    hub = os.path.join(root, 'applicationsets/templates/hub/hub-components.yaml')
    if os.path.exists(hub):
        txt = open(hub).read()
        out['hub'] = re.findall(r'-\s*component:\s*([\w.-]+)', txt)

    mdir = os.path.join(root, 'applicationsets/templates/managed')
    for fn in sorted(os.listdir(mdir)) if os.path.isdir(mdir) else []:
        txt = open(os.path.join(mdir, fn)).read()
        placement = re.search(r'placement:\s*([\w.-]+)', txt)
        comps = re.findall(r'^\s*-\s*component:\s*([\w.-]+)', txt, re.M)
        if not comps:
            # single-component sets name the chart in the template instead
            m = re.search(r'name:\s*"?\{\{`\{\{name\}\}`\}\}-([\w.-]+)"?', txt)
            if m:
                comps = [m.group(1)]
        key = placement.group(1) if placement else fn.replace('.yaml', '')
        out['managed'].setdefault(key, [])
        for c in comps:
            if c not in out['managed'][key]:
                out['managed'][key].append(c)
    return out


def parse_placements(root, hub):
    p = load_yaml(os.path.join(root, 'values', hub, 'local-cluster/acm-placements.yaml'))
    res = {}
    for pl in p.get('placements', []) or []:
        res[pl['name']] = pl.get('matchLabels', {}) or {}
    return res


def _merge(base, over):
    """Shallow-recursive merge of Helm values: later files win."""
    out = dict(base or {})
    for k, v in (over or {}).items():
        out[k] = _merge(out.get(k), v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def effective_values(root, chart, hub, cluster):
    """Chart defaults, then values/<hub>/<chart>.yaml, then the per-cluster file.

    This is the same layering the ApplicationSets apply, so the namespace and
    subscription reported here are what actually lands on that cluster rather
    than the chart's default.
    """
    v = load_yaml(os.path.join(root, 'charts', chart, 'values.yaml'))
    v = _merge(v, load_yaml(os.path.join(root, 'values', hub, chart + '.yaml')))
    v = _merge(v, load_yaml(os.path.join(root, 'values', hub, cluster, chart + '.yaml')))
    return v


def parse_known_issues(root):
    """The HyperShift defects the team hit, from oac-apps/docs/hypershift-issues.md.

    Distinct from the curated discoveries list: these are written by the team in
    their own repository, so they are parsed rather than transcribed.
    """
    p = os.path.join(root, 'docs/hypershift-issues.md')
    if not os.path.exists(p):
        return []
    out, cur = [], None
    for line in open(p):
        if line.startswith('## '):
            if cur:
                out.append(cur)
            cur = {'title': line[3:].strip(), 'body': ''}
        elif cur is not None and line.strip():
            if len(cur['body']) < 400:
                cur['body'] += (' ' if cur['body'] else '') + line.strip()
    if cur:
        out.append(cur)
    # the doc opens with a priority index, which is not itself a defect
    return [i for i in out if not i['title'].lower().startswith('issues by')]


def chart_catalogue(root):
    """Namespace and subscription each chart declares, before overrides."""
    cdir = os.path.join(root, 'charts')
    out = {}
    for name in sorted(os.listdir(cdir)) if os.path.isdir(cdir) else []:
        vp = os.path.join(cdir, name, 'values.yaml')
        if not os.path.isdir(os.path.join(cdir, name)):
            continue
        v = load_yaml(vp)
        sub = v.get('subscription') or {}
        out[name] = {
            'namespace': v.get('namespace'),
            'subscription': {k: sub.get(k) for k in
                             ('name', 'channel', 'source', 'installPlanApproval')} if sub else None,
        }
    return out


def parse_projects(root, hub, cluster):
    chart_defaults = load_yaml(os.path.join(root, 'charts/user-projects/values.yaml'))
    v = _merge(chart_defaults,
               load_yaml(os.path.join(root, 'values', hub, cluster, 'user-projects.yaml')))
    dq, dl = v.get('defaultQuota'), v.get('defaultLimitRange')
    out = []
    for pr in v.get('projects', []) or []:
        quota = pr.get('quota') or dq
        limits = pr.get('limitRange') or dl
        out.append({
            'name': 'project-' + pr['name'],
            'short_name': pr['name'],
            'requester': pr.get('requester'),
            'description': (pr.get('description') or '').strip(),
            'groups': [{'name': g.get('name'), 'role': g.get('role')}
                       for g in (pr.get('groups') or [])],
            'quota': (quota or {}).get('hard'),
            'quota_is_default': pr.get('quota') is None,
            'limits': (limits or {}).get('limits'),
            'limits_is_default': pr.get('limitRange') is None,
        })
    return out


def parse_networks(root, hub, cluster=None):
    """Real addressing from the values files: MetalLB pools, the hosted-cluster
    router address, and the Portworx storage network (including the route to the
    array's management endpoint)."""
    scope = os.path.join('values', hub, cluster or 'local-cluster')
    mb = load_yaml(os.path.join(root, scope, 'metallb.yaml'))
    pools = []
    for ap in mb.get('addressPools', []) or []:
        pools += list(ap.get('addresses', []) or [])

    net = {'metallb': pools}

    if cluster is None:
        hcp = load_yaml(os.path.join(root, scope, 'hcp-config.yaml'))
        ic = (hcp.get('ingressController') or {})
        net['hcp_router'] = list(ic.get('addresses', []) or [])
        net['hcp_router_domain'] = ic.get('domain')
    else:
        px = load_yaml(os.path.join(root, scope, 'portworx.yaml'))
        pn = px.get('network') or {}
        net['storage'] = {
            'cidr': pn.get('cidr'),
            'range': ((pn.get('range') or {}).get('start'), (pn.get('range') or {}).get('end')),
            'routes': [{'dst': r.get('dst'), 'gw': r.get('gw')}
                       for r in (pn.get('routes') or [])],
            'nodes': [{'name': n.get('name'), 'interface': n.get('interface')}
                      for n in (px.get('nodes') or [])],
        }
    return net


def parse_dns(root, hub):
    ed = load_yaml(os.path.join(root, 'values', hub, 'local-cluster/external-dns-operator.yaml'))
    out = []
    for e in ed.get('externaldns', []) or []:
        out.append({'name': e.get('name'),
                    'domains': [d.get('name') for d in (e.get('domains') or [])],
                    'zones': list(e.get('zones') or [])})
    return out


def parse_policies(root):
    """The tenant isolation tiers, read from the chart that creates them."""
    tdir = os.path.join(root, 'charts/restrict-tenant-networks/templates')
    tiers = []
    order = {'AdminNetworkPolicy': 1, 'NetworkPolicy': 2, 'BaselineAdminNetworkPolicy': 3}
    for fn in sorted(os.listdir(tdir)) if os.path.isdir(tdir) else []:
        txt = open(os.path.join(tdir, fn)).read()
        kind = re.search(r'^kind:\s*(\w+)', txt, re.M)
        name = re.search(r'^\s+name:\s*([\w.-]+)', txt, re.M)
        if not kind:
            continue
        prio = re.search(r'priority:\s*(\d+)', txt)
        tiers.append({'name': name.group(1) if name else fn.replace('.yaml', ''),
                      'tier': kind.group(1), 'scope': 'cluster',
                      'priority': int(prio.group(1)) if prio else None,
                      'file': 'charts/restrict-tenant-networks/templates/' + fn})
    # the per-namespace NetworkPolicy is created by user-projects, not this chart
    up = os.path.join(root, 'charts/user-projects/templates/networkpolicy.yaml')
    if os.path.exists(up):
        tiers.append({'name': 'allow-intra-namespace', 'tier': 'NetworkPolicy',
                      'scope': 'per project', 'priority': None,
                      'file': 'charts/user-projects/templates/networkpolicy.yaml'})
    tiers.sort(key=lambda t: (order.get(t['tier'], 9), t['name']))
    return tiers


def parse_charts(root, complists, dropins):
    cdir = os.path.join(root, 'charts')
    placement_of = {}
    for placement, comps in complists['managed'].items():
        for c in comps:
            placement_of.setdefault(c, []).append(placement)
    out = []
    for name in sorted(os.listdir(cdir)):
        cp = os.path.join(cdir, name, 'Chart.yaml')
        if not os.path.isdir(os.path.join(cdir, name)) or not os.path.exists(cp):
            continue
        meta = load_yaml(cp)
        targets = []
        if name in complists['hub']:
            targets.append('hub')
        targets += placement_of.get(name, [])
        if name in dropins:
            targets.append('drop-in')
        if meta.get('type') == 'library':
            targets.append('library')
        out.append({'name': name,
                    'description': (meta.get('description') or '').strip(),
                    'targets': targets or ['not referenced']})
    return out


def parse_dropins(root):
    adir = os.path.join(root, 'apps')
    out = {}
    for hub in sorted(os.listdir(adir)) if os.path.isdir(adir) else []:
        hp = os.path.join(adir, hub)
        if not os.path.isdir(hp):
            continue
        for fn in sorted(os.listdir(hp)):
            if fn.endswith(('.yaml', '.yml')):
                out.setdefault(fn.rsplit('.', 1)[0], []).append(hub)
    return out


def components_detail(root, hub, cluster, comps, catalogue):
    """Each deployed chart with the namespace and subscription it lands with."""
    out = []
    for c in comps:
        base = catalogue.get(c) or {}
        eff = effective_values(root, c, hub, cluster)
        sub = eff.get('subscription') or base.get('subscription') or None
        out.append({
            'chart': c,
            'namespace': eff.get('namespace') or base.get('namespace'),
            'operator': (sub or {}).get('name'),
            'channel': (sub or {}).get('channel'),
            'source': (sub or {}).get('source'),
            'approval': (sub or {}).get('installPlanApproval'),
        })
    return out


def namespace_inventory(cluster_rec, hosted=None):
    """Every namespace this cluster's own configuration declares.

    Three origins, kept distinct because they are governed differently: tenant
    projects are tracked in a values file, platform namespaces come from the
    chart that installs the component, and hosted-control-plane namespaces are
    created by HyperShift on a hub.
    """
    seen, out = set(), []

    def add(name, kind, declared_by, extra=None):
        if not name or name in seen:
            return
        seen.add(name)
        rec = {'name': name, 'kind': kind, 'declared_by': declared_by}
        if extra:
            rec.update(extra)
        out.append(rec)

    for p in cluster_rec.get('projects') or []:
        add(p['name'], 'tenant', 'values/.../user-projects.yaml',
            {'requester': p.get('requester'), 'description': p.get('description'),
             'groups': [g['name'] for g in p.get('groups') or []]})

    for c in cluster_rec.get('components') or []:
        if c.get('namespace'):
            add(c['namespace'], 'platform', 'charts/' + c['chart'],
                {'operator': c.get('operator')})

    for h in hosted or []:
        add('clusters-' + h, 'hosted control plane', 'hypershift')

    out.sort(key=lambda n: ({'tenant': 0, 'hosted control plane': 1, 'platform': 2}
                            .get(n['kind'], 3), n['name']))
    return out


def parse_clusters(root, curated=None):
    """Hubs from hosted-clusters/<hub>/, workload clusters from its subdirs."""
    curated = curated or {}
    complists = parse_component_lists(root)
    catalogue = chart_catalogue(root)
    dropins = parse_dropins(root)
    policies = parse_policies(root)
    hcdir = os.path.join(root, 'hosted-clusters')
    clusters = []

    for hub in sorted(os.listdir(hcdir)) if os.path.isdir(hcdir) else []:
        hubdir = os.path.join(hcdir, hub)
        if not os.path.isdir(hubdir):
            continue
        placements = parse_placements(root, hub)
        hub_defaults = load_yaml(os.path.join(hubdir, 'values.yaml'))

        hosted = []
        for cl in sorted(os.listdir(hubdir)):
            cdir = os.path.join(hubdir, cl)
            if not os.path.isdir(cdir):
                continue
            v = load_yaml(os.path.join(cdir, 'values.yaml'))
            name = v.get('clusterName', cl)
            labels = v.get('clusterLabels', {}) or {}

            pools = []
            for np in v.get('nodePools', []) or []:
                sel = np.get('agentLabelSelector', {}) or {}
                rc = sel.get('openstack/resource-class', 'unknown')
                hw = HARDWARE.get(rc)
                if hw is None:
                    print(f'  ! no hardware profile for resource class {rc!r}; '
                          f'marking it as needing data. Add it to data/curated.json.',
                          file=sys.stderr)
                    hw = {'label': rc, 'gpus': None, 'kind': 'unknown'}
                reps = int(np.get('replicas', 0) or 0)
                gpn = hw.get('gpus')          # None = genuinely not known
                pools.append({'name': np.get('name'), 'replicas': reps,
                              'resource_class': rc, 'hardware': hw['label'],
                              'kind': hw['kind'], 'gpus_per_node': gpn,
                              'gpus': None if gpn is None else gpn * reps,
                              'needs_data': gpn is None,
                              'profile_source': hw.get('source')})

            # components: every managed set whose placement labels the cluster carries
            comps = []
            for placement, want in placements.items():
                if want and all(labels.get(k) == val for k, val in want.items()):
                    for c in complists['managed'].get(placement, []):
                        if c not in comps:
                            comps.append(c)
            for c in complists['managed'].get('all-managed-clusters', []):
                if c not in comps:
                    comps.append(c)

            idp = None
            for p in (v.get('oauth', {}) or {}).get('identityProviders', []) or []:
                idp = {'name': p.get('name'), 'type': p.get('type'),
                       'issuer': (p.get('openID') or {}).get('issuer')}

            svc = (v.get('services', {}) or {}).get('APIServer', {}) or {}
            clusters.append({
                'name': name, 'kind': 'workload', 'hub': hub,
                'role': 'Tenant cluster' + (' (dev)' if 'dev' in hub else ''),
                'env': 'dev' if 'dev' in hub else 'prod',
                'labels': labels,
                'nodepools': pools,
                'nodes': sum(p['replicas'] for p in pools),
                'gpu_nodes': sum(p['replicas'] for p in pools if p['kind'] == 'gpu'),
                'gpus': sum(p['gpus'] for p in pools if p['gpus'] is not None),
                'gpus_partial': any(p['needs_data'] for p in pools),
                'nodes_pending_data': sum(p['replicas'] for p in pools if p['needs_data']),
                'operators': sorted(comps),
                'components': components_detail(root, hub, name, sorted(comps), catalogue),
                'rhoai': ((effective_values(root, 'rhoai', hub, name).get('dataScienceCluster')
                           or {}).get('components') if 'rhoai' in comps else None),
                'projects': parse_projects(root, hub, name),
                'policies': policies if any(c == 'restrict-tenant-networks' for c in comps) else [],
                'idp': idp,
                'endpoints': {
                    'api_internal': svc.get('ipAddress'),
                    'api_external': svc.get('externalIpAddress'),
                    'ingress': ((v.get('ingress', {}) or {}).get('externalIpAddress')),
                    'base_domain': v.get('baseDomain') or hub_defaults.get('baseDomain'),
                },
                'network': parse_networks(root, hub, name),
                'source': f'hosted-clusters/{hub}/{cl}/values.yaml',
            })
            hosted.append(name)

        hub_comps = complists['hub'] + [c for c, hubs in dropins.items() if hub in hubs]
        hn = (curated.get('hub_nodes') or {}).get(hub) or {}
        cp, wk = hn.get('control_plane'), hn.get('workers')
        clusters.append({
            'name': hub, 'kind': 'hub', 'hub': None,
            'control_plane_nodes': cp, 'worker_nodes': wk,
            'nodes_needs_data': cp is None and wk is None,
            'nodes_source': hn.get('source'),
            'role': 'Hub (' + ('development' if 'dev' in hub else 'production') + ')',
            'env': 'dev' if 'dev' in hub else 'prod',
            'labels': {}, 'nodepools': [],
            'nodes': None if (cp is None and wk is None) else (cp or 0) + (wk or 0),
            'gpu_nodes': 0, 'gpus': 0,
            'operators': sorted(hub_comps),
            'components': components_detail(root, hub, 'local-cluster', sorted(hub_comps),
                                            catalogue),
            'projects': [], 'policies': [], 'idp': None,
            'hosts': hosted,
            'endpoints': {'base_domain': hub_defaults.get('hcpExternalDomain'),
                          'internal_domain': hub_defaults.get('hcpInternalDomain')},
            'network': parse_networks(root, hub),
            'dns': parse_dns(root, hub),
            'source': f'hosted-clusters/{hub}/values.yaml',
        })

    for c in clusters:
        c['namespaces'] = namespace_inventory(c, c.get('hosts'))

    order = {'hub': 0, 'workload': 1}
    clusters.sort(key=lambda c: (c['env'] != 'prod', order[c['kind']], c['name']))
    return clusters, complists, dropins, policies


# --------------------------------------------------------------------------
# issue parser
# --------------------------------------------------------------------------
def fetch_issues_api(repo, token):
    import urllib.request
    issues, page = [], 1
    while True:
        url = (f'https://api.github.com/repos/{repo}/issues'
               f'?state=all&per_page=100&page={page}')
        req = urllib.request.Request(url, headers={
            'Accept': 'application/vnd.github+json',
            'User-Agent': 'moc2-platform',
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


RFC_RE = re.compile(r'RFC\s*(\d{1,2})\b', re.I)


def classify_rfc(issue):
    """Status of an RFC issue: approved when closed, otherwise open vs in review."""
    if issue.get('state') == 'closed':
        return 'approved'
    body = (issue.get('body') or '').lower()
    if 'draft' in body or 'under review' in body or issue.get('assignees'):
        return 'in-review'
    return 'open'


def parse_issues(issues):
    weekly = collections.defaultdict(lambda: {'opened': 0, 'closed': 0})
    for i in issues:
        weekly[week_of(i['created_at'])]['opened'] += 1
        if i.get('closed_at'):
            weekly[week_of(i['closed_at'])]['closed'] += 1
    weeks = sorted(weekly)
    issues_weekly = [{'week': w, 'opened': weekly[w]['opened'],
                      'closed': weekly[w]['closed']} for w in weeks]

    rfcs = []
    for i in issues:
        t = i['title']
        if not re.search(r'\bRFC\b', t, re.I):
            continue
        m = RFC_RE.search(t)
        if not m:
            continue
        num = int(m.group(1))
        title = re.sub(r'^.*?RFC\s*\d{1,2}\s*[-–—:]?\s*', '', t, flags=re.I)
        title = re.sub(r'\s*[-–—]?\s*(Creation and Sign off)\s*$', '', title, flags=re.I).strip()
        rfcs.append({'id': f'RFC {num:02d}', 'num': num, 'title': title or t,
                     'status': classify_rfc(i), 'issue': i['number'],
                     'updated': i['updated_at'][:10],
                     'owner': (i.get('assignee') or {}).get('login') if i.get('assignee') else None,
                     'labels': [l['name'] for l in i.get('labels', [])]})
    # one card per RFC number: prefer the furthest-along, then most recent
    rank = {'approved': 0, 'in-review': 1, 'open': 2}
    best = {}
    for r in sorted(rfcs, key=lambda r: (rank[r['status']], r['updated'])):
        best.setdefault(r['num'], r)
    rfcs = sorted(best.values(), key=lambda r: r['num'])

    recent = sorted(issues, key=lambda i: i['updated_at'], reverse=True)[:12]
    issues_recent = [{'num': i['number'], 'title': i['title'], 'state': i['state'],
                      'labels': [l['name'] for l in i.get('labels', [])],
                      'updated': i['updated_at'][:10]} for i in recent]

    labels = collections.Counter()
    for i in issues:
        for l in i.get('labels', []):
            labels[l['name']] += 1

    return {
        'issues_weekly': issues_weekly,
        'issues_recent': issues_recent,
        'rfcs': rfcs,
        'totals': {
            'open': sum(1 for i in issues if i['state'] == 'open'),
            'closed': sum(1 for i in issues if i['state'] == 'closed'),
            'count': len(issues),
            'window': (min(i['created_at'] for i in issues)[:10] + ' → ' +
                       max(i['updated_at'] for i in issues)[:10]),
        },
        'labels': [{'name': n, 'count': c} for n, c in labels.most_common(12)],
    }


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument('--oac-apps', required=True, help='path to an oac-apps checkout')
    ap.add_argument('--ansible-switches', help='path to an ansible-switches checkout')
    ap.add_argument('--infra', help='path to an open-accelerator-infra checkout')
    ap.add_argument('--keycloak', help='path to a moc-keycloak checkout')
    ap.add_argument('--curated', default=os.path.join(here, 'data', 'curated.json'))
    ap.add_argument('--out', default=os.path.join(here, 'data', 'snapshot.js'))
    a = ap.parse_args()

    curated = {}
    if os.path.exists(a.curated):
        curated = json.load(open(a.curated))
    profiles = {k: v for k, v in (curated.get('hardware_profiles') or {}).items()
                if not k.startswith('_')}
    if profiles:
        HARDWARE.update(profiles)

    print('repo parser  :', a.oac_apps)
    clusters, complists, dropins, policies = parse_clusters(a.oac_apps, curated)
    charts = parse_charts(a.oac_apps, complists, dropins)
    print(f'  {len(clusters)} clusters, {len(charts)} charts, {len(policies)} policy tiers')

    sw = parse_network.parse_switches(a.ansible_switches)
    infra = parse_network.parse_infra(a.infra)
    if a.ansible_switches or a.infra:
        print('network parser:', a.ansible_switches or '-', '|', a.infra or '-')
        st = sw.get('stats') or {}
        if st:
            print(f"  {st['switches_in_inventory']} switches, {st['interfaces']} interfaces "
                  f"({st['interfaces_with_vlan']} with a VLAN), "
                  f"{st['vlans_defined']} VLANs defined / {st['vlans_in_use']} in use")
        if infra.get('networks'):
            print(f"  {len(infra['networks'])} VLAN/CIDR rows, {len(infra['nodes'])} nodes in the "
                  f"hardware doc, {sum(len(v) for v in infra['clusters'].values())} inventory hosts")
    storage_cidrs = {c['name']: ((c.get('network') or {}).get('storage') or {}).get('cidr')
                     for c in clusters}
    orphan_vlans = parse_network.merge(clusters, sw, infra, storage_cidrs)
    if orphan_vlans:
        print('  VLANs provisioned but not tied to a declared cluster: ' +
              ', '.join(f"{o['vlan']} {o['name']}" for o in orphan_vlans))

    kc = parse_identity.parse_keycloak(a.keycloak)
    kc_unclaimed, kc_groups = parse_identity.merge(clusters, kc)
    if a.keycloak:
        st = kc.get('stats') or {}
        print('identity parser:', a.keycloak)
        print(f"  realm {(kc.get('realm') or {}).get('name')} · {st.get('providers',0)} providers, "
              f"{st.get('clients',0)} OIDC clients, {st.get('groups',0)} groups, "
              f"{st.get('flows',0)} auth flows")
        if kc_unclaimed:
            print('  OIDC clients with no cluster in oac-apps: ' +
                  ', '.join(c['cluster_name'] for c in kc_unclaimed))



    snapshot = {
        'generated_at': datetime.datetime.now(datetime.timezone.utc)
                        .replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
        'mock': False,
        'sources': {
            'apps': git_meta(a.oac_apps),
        },
        'caveats': {
            'declared_not_live': ('Everything about clusters is read from Git, so it is the '
                                  'declared configuration, not live cluster state.'),
            'hardware': HARDWARE_SOURCE,
            'billing': ('Billing figures are not published: the metric the invoices are '
                        'built from is unavailable on hosted control planes (see #481).'),
        },
        'shared': {
            'storage_mgmt': sorted({r['dst'].split('/')[0]
                                    for c in clusters for r in
                                    ((c.get('network') or {}).get('storage') or {}).get('routes', [])
                                    if r.get('dst')}),
            'idp_issuers': sorted({c['idp']['issuer'] for c in clusters
                                   if c.get('idp') and c['idp'].get('issuer')}),
            'public_ips': sorted({ip for c in clusters for ip in
                                  [(c.get('endpoints') or {}).get('api_external'),
                                   (c.get('endpoints') or {}).get('ingress')] if ip}),
        },
        'known_issues': parse_known_issues(a.oac_apps),
        'fleet': parse_network.fleet(infra),
        'clusters': clusters,
        'identity': {
            'realm': kc.get('realm'),
            'providers': kc.get('providers') or [],
            'clients': kc.get('clients') or [],
            'groups': kc_groups,
            'flows': kc.get('flows') or [],
            'stats': kc.get('stats') or {},
            'clients_without_cluster': kc_unclaimed,
        },
        'network': {
            'vlans': list((sw.get('vlans') or {}).values()),
            'cidrs': infra.get('networks') or [],
            'switches': sw.get('switches') or [],
            'stats': sw.get('stats') or {},
            'usage_counts': {str(k): {'untagged': len(v['untagged']), 'tagged': len(v['tagged']),
                                      'switches': sorted({p['switch'] for p in v['untagged'] + v['tagged']})}
                             for k, v in (sw.get('usage') or {}).items()},
            'unclaimed': orphan_vlans,
            'ports': {str(v): (sw.get('usage') or {}).get(v)
                      for v in sorted((sw.get('usage') or {}))
                      if str(((sw.get('vlans') or {}).get(v) or {}).get('name') or '')
                      .startswith(('OAC', 'MOCSEC'))},
            'bastion': infra.get('bastion'),
        },
        'charts': charts,
        'placements': {h: parse_placements(a.oac_apps, h)
                       for h in {c['hub'] for c in clusters if c['hub']}},
        'policies': policies,
    }

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, 'w') as fh:
        fh.write('/* Generated by tools/build_snapshot.py — do not edit by hand.\n'
                 f'   Repo-derived data only, generated {snapshot["generated_at"]}\n'
                 f'   from {APPS_REPO}@{snapshot["sources"]["apps"]["commit"]} and the\n'
                 '   switch, inventory and identity repositories. Issue-derived and\n'
                 '   curated content lives in analysis.js; see ANALYSIS.md. */\n')
        fh.write('window.MOC_DATA = ')
        json.dump(snapshot, fh, indent=1, ensure_ascii=False)
        fh.write(';\n')
    print('wrote', a.out, f'({os.path.getsize(a.out)/1024:.0f} KB)')


if __name__ == '__main__':
    main()
