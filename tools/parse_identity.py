#!/usr/bin/env python3
"""Parser for CCI-MOC/moc-keycloak (Terraform/OpenTofu).

Gives the identity layer as configured rather than as described: the realm and
its security-relevant settings, the federated identity providers, the per-cluster
OpenShift OIDC clients, the group list, and the authentication flows with their
ordered executions.

Terraform is read with regexes rather than a HCL parser to keep the dashboard
dependency-free. That is good enough here because the repo is generated/linted
and uses one attribute per line; anything unrecognised is skipped rather than
guessed at.
"""
import os, re

# realm attributes worth surfacing; everything else in the realm block is noise
REALM_KEYS = [
    'display_name', 'enabled', 'login_with_email_allowed', 'duplicate_emails_allowed',
    'edit_username_allowed', 'registration_allowed', 'registration_email_as_username',
    'reset_password_allowed', 'remember_me', 'verify_email', 'ssl_required',
    'access_token_lifespan', 'sso_session_idle_timeout', 'sso_session_max_lifespan',
    'browser_flow', 'first_broker_login_flow',
]

IDP_KEYS = ['alias', 'display_name', 'enabled', 'issuer', 'authorization_url',
            'default_scopes', 'sync_mode', 'trust_email', 'store_token',
            'first_broker_login_flow_alias', 'authenticate_by_default']


def _blocks(text, kind):
    """Yield (type, name, body) for every `resource "type" "name" { ... }`."""
    for m in re.finditer(r'^resource\s+"([\w-]+)"\s+"([\w-]+)"\s*\{(.*?)^\}',
                         text, re.S | re.M):
        if m.group(1) == kind or kind is None:
            yield m.group(1), m.group(2), m.group(3)


def _attrs(body):
    """key = value pairs, one per line. Values keep their raw form when they are
    references (keycloak_realm.moc.id) so the reader can see the wiring."""
    out = {}
    for line in body.splitlines():
        m = re.match(r'\s*([a-z0-9_]+)\s*=\s*(.+?)\s*$', line)
        if not m:
            continue
        v = m.group(2).strip()
        if v.startswith('"') and v.endswith('"') and len(v) > 1:
            v = v[1:-1]
        elif v in ('true', 'false'):
            v = (v == 'true')
        out[m.group(1)] = v
    return out


def _read(root, name):
    p = os.path.join(root, name)
    return open(p).read() if os.path.exists(p) else ''


def parse_keycloak(root):
    out = {'realm': None, 'providers': [], 'clients': [], 'groups': [],
           'flows': [], 'stats': {}}
    if not root or not os.path.isdir(root):
        return out

    files = [f for f in sorted(os.listdir(root)) if f.endswith('.tf')]
    blob = {f: _read(root, f) for f in files}

    # ---- realm -----------------------------------------------------------
    for fn, txt in blob.items():
        for _, name, body in _blocks(txt, 'keycloak_realm'):
            a = _attrs(body)
            out['realm'] = {'name': name, 'source': fn,
                            **{k: a[k] for k in REALM_KEYS if k in a}}
            break

    # ---- identity providers ---------------------------------------------
    for fn, txt in blob.items():
        for kind, name, body in _blocks(txt, None):
            if not kind.startswith('keycloak_') or 'identity_provider' not in kind:
                continue
            a = _attrs(body)
            rec = {'resource': name, 'kind': kind, 'source': fn,
                   **{k: a[k] for k in IDP_KEYS if k in a}}
            # the flow reference tells you which first-broker flow it runs
            fb = a.get('first_broker_login_flow_alias')
            if isinstance(fb, str) and fb.startswith('keycloak_'):
                rec['first_broker_login_flow_alias'] = fb.split('.')[1]
            out['providers'].append(rec)

    # ---- per-cluster OpenShift OIDC clients ------------------------------
    main = blob.get('main.tf', '')
    m = re.search(r'openshift_oidc_clusters\s*=\s*\{(.*?)\n  \}', main, re.S)
    if m:
        for entry in re.finditer(r'(\w+)\s*=\s*\{(.*?)\n    \}', m.group(1), re.S):
            a = _attrs(entry.group(2))
            out['clients'].append({
                'key': entry.group(1),
                'cluster_name': a.get('cluster_name'),
                'redirect_uri': a.get('openshift_redirect_uri'),
                'client_secret_name': a.get('client_secret_name'),
                'source': 'main.tf',
            })

    # ---- groups ----------------------------------------------------------
    g = re.search(r'keycloak_groups\s*=\s*toset\(\[(.*?)\]\)', blob.get('groups.tf', ''), re.S)
    if g:
        out['groups'] = re.findall(r'"([^"]+)"', g.group(1))

    # ---- authentication flows and their executions -----------------------
    flows = {}
    for fn, txt in blob.items():
        for kind, name, body in _blocks(txt, 'keycloak_authentication_flow'):
            a = _attrs(body)
            flows[name] = {'resource': name, 'alias': a.get('alias'),
                           'description': a.get('description'), 'source': fn,
                           'steps': []}
    subflows = {}
    for fn, txt in blob.items():
        for kind, name, body in _blocks(txt, 'keycloak_authentication_subflow'):
            a = _attrs(body)
            subflows[name] = {'alias': a.get('alias'),
                              'parent': str(a.get('parent_flow_alias', '')),
                              'requirement': a.get('requirement')}

    def owner(ref):
        """Resolve parent_flow_alias to a top-level flow resource name."""
        ref = str(ref)
        if ref.startswith('keycloak_authentication_flow.'):
            return ref.split('.')[1]
        if ref.startswith('keycloak_authentication_subflow.'):
            sub = subflows.get(ref.split('.')[1])
            return owner(sub['parent']) if sub else None
        return None

    for fn, txt in blob.items():
        for kind, name, body in _blocks(txt, 'keycloak_authentication_execution'):
            a = _attrs(body)
            f = owner(a.get('parent_flow_alias'))
            step = {'authenticator': a.get('authenticator'),
                    'requirement': a.get('requirement'),
                    'resource': name}
            parent = str(a.get('parent_flow_alias', ''))
            if parent.startswith('keycloak_authentication_subflow.'):
                sub = subflows.get(parent.split('.')[1]) or {}
                step['subflow'] = sub.get('alias')
            if f and f in flows:
                flows[f]['steps'].append(step)
            else:
                flows.setdefault('_unattached', {'resource': '_unattached',
                                                 'alias': str(a.get('parent_flow_alias')),
                                                 'source': fn, 'steps': []})['steps'].append(step)
    out['flows'] = list(flows.values())
    out['stats'] = {'tf_files': len(files), 'providers': len(out['providers']),
                    'clients': len(out['clients']), 'groups': len(out['groups']),
                    'flows': len([f for f in out['flows'] if f['resource'] != '_unattached'])}
    return out


def merge(clusters, kc):
    """Attach each cluster's Keycloak client; report clients with no cluster and
    groups that no declared project uses."""
    by_name = {c['name']: c for c in clusters}
    for cl in kc.get('clients') or []:
        c = by_name.get(cl.get('cluster_name'))
        if c:
            c['keycloak_client'] = {k: cl[k] for k in
                                    ('redirect_uri', 'client_secret_name') if cl.get(k)}

    unclaimed = [cl for cl in (kc.get('clients') or [])
                 if cl.get('cluster_name') not in by_name]

    used = set()
    for c in clusters:
        for p in c.get('projects') or []:
            for g in p.get('groups') or []:
                used.add(g)
    groups = [{'name': g, 'used_by_a_project': g in used} for g in kc.get('groups') or []]
    return unclaimed, groups
