#!/usr/bin/env python3
"""Parsers for the physical layer, used by build_snapshot.py.

  CCI-MOC/ansible-switches        -> switch inventory, the VLAN catalogue, and
                                     which ports actually carry each VLAN
  CCI-MOC/open-accelerator-infra  -> VLAN-to-CIDR map, per-node NIC assignments,
                                     BMC addresses, and cluster membership

Cluster membership comes from the Ansible inventory (which carries an explicit
`cluster:` group var); per-node networking comes from the hardware document.
They are joined on node_name. A node present in one but not the other keeps
whatever is known and leaves the rest blank -- nothing is inferred across the
join.
"""
import os, re, sys

try:
    import yaml
except ImportError:
    sys.exit('pyyaml is required: pip install pyyaml')


# ---------------------------------------------------------------- switches
def parse_switches(root):
    """VLAN catalogue + per-VLAN port usage + switch inventory."""
    out = {'vlans': {}, 'usage': {}, 'switches': [], 'stats': {}}
    if not root or not os.path.isdir(root):
        return out

    vf = os.path.join(root, 'group_vars/all/vlans.yaml')
    if os.path.exists(vf):
        for v in (yaml.safe_load(open(vf)) or {}).get('vlans', []) or []:
            try:
                vid = int(v['id'])
            except (KeyError, TypeError, ValueError):
                continue
            out['vlans'][vid] = {
                'id': vid, 'name': v.get('name'), 'description': v.get('description'),
                'fabrics': list(v.get('fabrics') or []),
            }

    # inventory: NAME ansible_host=IP ansible_network_os=OS, grouped by [group]
    hosts = os.path.join(root, 'hosts')
    group = None
    if os.path.exists(hosts):
        for line in open(hosts):
            line = line.strip()
            if line.startswith('[') and line.endswith(']'):
                group = line[1:-1]
                continue
            m = re.match(r'^([A-Za-z0-9\-]+)\s+ansible_host=(\S+)'
                         r'(?:\s+ansible_network_os=(\S+))?', line)
            if m:
                out['switches'].append({'name': m.group(1), 'address': m.group(2),
                                        'os': m.group(3) or None, 'group': group})

    hv = os.path.join(root, 'host_vars')
    ports = cfg_ports = 0
    usage = {}
    for sw in sorted(os.listdir(hv)) if os.path.isdir(hv) else []:
        f = os.path.join(hv, sw, 'interfaces.yaml')
        if not os.path.exists(f):
            continue
        for ifname, c in ((yaml.safe_load(open(f)) or {}).get('interfaces') or {}).items():
            if not isinstance(c, dict):
                continue
            ports += 1
            hit = False
            for mode, val in (('untagged', c.get('untagged')), ('tagged', c.get('tagged'))):
                vals = val if isinstance(val, list) else ([val] if val is not None else [])
                for x in vals:
                    try:
                        vid = int(x)          # ranges like "351:499" and "all" are skipped
                    except (TypeError, ValueError):
                        continue
                    hit = True
                    usage.setdefault(vid, {'untagged': [], 'tagged': []})[mode].append(
                        {'switch': sw, 'interface': ifname, 'description': c.get('description', '')})
            if hit:
                cfg_ports += 1

    out['usage'] = usage
    out['stats'] = {'switches_in_inventory': len(out['switches']),
                    'switches_with_config': len([d for d in os.listdir(hv)
                                                 if os.path.exists(os.path.join(hv, d, 'interfaces.yaml'))])
                    if os.path.isdir(hv) else 0,
                    'interfaces': ports, 'interfaces_with_vlan': cfg_ports,
                    'vlans_defined': len(out['vlans']), 'vlans_in_use': len(usage)}
    return out


# ---------------------------------------------------------------- infra repo
def _md_tables(text):
    """Yield (heading, [row-dicts]) for every pipe table in a markdown file."""
    heading, header, rows = None, None, []
    for line in text.splitlines():
        if line.startswith('#'):
            if header and rows:
                yield heading, header, rows
            heading, header, rows = line.lstrip('#').strip(), None, []
            continue
        if not line.strip().startswith('|'):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if set(''.join(cells)) <= set('-: '):
            continue                                   # separator row
        if header is None:
            header = cells
        else:
            rows.append(cells)
    if header and rows:
        yield heading, header, rows


def _parse_terraform_networks(root):
    """OpenStack networks declared in infra/*.tf.

    The hardware doc lists the production VLANs; the Terraform additionally
    carries the ESI-era networks (including the dev workload storage net), so
    both are read and tagged with where they came from.
    """
    found = []
    d = os.path.join(root, 'infra')
    for fn in sorted(os.listdir(d)) if os.path.isdir(d) else []:
        if not fn.endswith('.tf'):
            continue
        txt = open(os.path.join(d, fn)).read()
        # network blocks carry a name + segmentation_id; the matching subnet
        # block repeats the name and carries the cidr
        for m in re.finditer(r'resource\s+"openstack_networking_network_v2"\s+"([\w.-]+)"\s*{(.*?)\n}',
                             txt, re.S):
            body = m.group(2)
            seg = re.search(r'segmentation_id\s*=\s*(\d+)', body)
            sub = re.search(r'resource\s+"openstack_networking_subnet_v2"\s+"' +
                            re.escape(m.group(1)) + r'"\s*{(.*?)\n}', txt, re.S)
            cidr = re.search(r'cidr\s*=\s*"([^"]+)"', sub.group(1)) if sub else None
            found.append({'name': m.group(1),
                          'vlan': int(seg.group(1)) if seg else None,
                          'cidr': cidr.group(1) if cidr else None,
                          'source': 'terraform:' + fn})
    return found


def parse_infra(root):
    """VLAN-to-CIDR, per-node networking, and cluster membership."""
    out = {'networks': [], 'nodes': {}, 'clusters': {}, 'bastion': None}
    if not root or not os.path.isdir(root):
        return out

    doc = os.path.join(root, 'docs/hardware-and-network-configuration.md')
    if os.path.exists(doc):
        for heading, header, rows in _md_tables(open(doc).read()):
            h = [c.lower() for c in header]
            if 'vlan id' in h and 'cidr' in h:
                for r in rows:
                    d = dict(zip(h, r))
                    try:
                        vid = int(d.get('vlan id', ''))
                    except ValueError:
                        continue
                    out['networks'].append({'name': d.get('network name'), 'vlan': vid,
                                            'cidr': d.get('cidr') or None,
                                            'source': 'hardware doc'})
            elif 'node name' in h and 'networking' in h:
                for r in rows:
                    d = dict(zip(h, r))
                    name = (d.get('node name') or '').strip()
                    if not name or name.startswith('??'):
                        continue                        # the doc's own unknowns
                    nics = {}
                    for m in re.finditer(r'NIC(\d+):\s*(\d+)', d.get('networking', '')):
                        nics['nic' + m.group(1)] = int(m.group(2))
                    note = (d.get('purpose') or '').strip()
                    out['nodes'][name.upper()] = {
                        'node_name': name,
                        'resource_class': d.get('resource class') or None,
                        'ipmi': d.get('ipmi address') or None,
                        'nics': nics,
                        'purpose': note if not note.startswith(('*', '?')) else None,
                        'flag': note if note.startswith(('*', '?')) else None,
                        'section': heading,
                    }

    have = {n['vlan'] for n in out['networks'] if n.get('vlan')}
    for n in _parse_terraform_networks(root):
        if n['vlan'] and n['vlan'] not in have:
            out['networks'].append(n)

    inv = os.path.join(root, 'infra/inventory/00hosts.yaml')
    if os.path.exists(inv):
        tree = yaml.safe_load(open(inv)) or {}

        def walk(node, inherited):
            if not isinstance(node, dict):
                return
            v = dict(inherited)
            v.update({k: val for k, val in (node.get('vars') or {}).items()
                      if k in ('cluster', 'network_name', 'bmc_type')})
            for hn, hv in (node.get('hosts') or {}).items():
                hv = hv or {}
                rec = {'inventory_name': hn,
                       'node_name': hv.get('node_name'),
                       'bmc': hv.get('bmc_addr'),
                       'cluster': v.get('cluster'),
                       'network_name': v.get('network_name'),
                       'bmc_type': v.get('bmc_type')}
                if hn == 'oac-dev-bastion':
                    out['bastion'] = rec
                    continue
                if rec['cluster']:
                    out['clusters'].setdefault(rec['cluster'], []).append(rec)
            for child in (node.get('children') or {}).values():
                walk(child, v)

        walk(tree.get('all') or {}, {})

    return out


def fleet(infra):
    """Every machine the hardware doc lists, with what it is assigned to.

    The cluster views only show machines that belong to a cluster. Most of the
    fleet does not: spares, machines held for RHOSO 18, and machines that are
    broken. That population is the capacity question, so it gets its own view.
    """
    assigned = {}
    for cname, recs in (infra.get('clusters') or {}).items():
        for r in recs:
            if r.get('node_name'):
                assigned[r['node_name'].upper()] = cname
    out = []
    for key, n in sorted((infra.get('nodes') or {}).items()):
        state = ('broken' if (n.get('flag') or '').startswith('*')
                 else 'reserved' if (n.get('flag') or '').startswith('?')
                 else 'assigned' if key in assigned
                 else 'idle')
        out.append({'node': n.get('node_name'), 'resource_class': n.get('resource_class'),
                    'ipmi': n.get('ipmi'), 'nics': n.get('nics') or None,
                    'purpose': n.get('purpose'), 'flag': n.get('flag'),
                    'cluster': assigned.get(key), 'state': state,
                    'section': n.get('section'), 'in_hardware_doc': True})

    # The hardware document covers the production side only -- rack R4PAC10 plus
    # the prod A100s and H100s. Machines that are in a cluster but absent from it
    # would otherwise vanish from the fleet view, making it look prod-only. They
    # are listed from the Ansible inventory instead, with the fields the document
    # would have supplied left empty rather than filled in from somewhere else.
    doc_keys = {k for k in (infra.get('nodes') or {})}
    for cname, recs in sorted((infra.get('clusters') or {}).items()):
        for r in recs:
            nn = (r.get('node_name') or '')
            if not nn or nn.upper() in doc_keys:
                continue
            out.append({'node': nn, 'resource_class': None, 'ipmi': r.get('bmc'),
                        'nics': None, 'purpose': None, 'flag': None,
                        'cluster': cname, 'state': 'assigned',
                        'section': 'not in hardware doc', 'in_hardware_doc': False})
    out.sort(key=lambda n: (not n['in_hardware_doc'], n['node'] or ''))
    return out


def merge(clusters, sw, infra, oac_storage_cidrs):
    """Attach physical facts to the clusters parsed from oac-apps.

    Only joins that the data supports: a node reaches its VLANs through the
    hardware document, a cluster reaches its nodes through the inventory. Where
    a node is in one source and not the other, the missing half stays None.
    """
    by_cluster = infra.get('clusters') or {}
    netmap = {n['vlan']: n for n in infra.get('networks') or []}

    for c in clusters:
        recs = by_cluster.get(c['name']) or []
        nodes = []
        vlans, storage_vlans = set(), set()
        for r in recs:
            hw = infra['nodes'].get((r.get('node_name') or '').upper()) or {}
            nics = hw.get('nics') or {}
            for k, vid in nics.items():
                (storage_vlans if vid >= 2300 else vlans).add(vid)
            nodes.append({
                'inventory_name': r['inventory_name'],
                'node_name': r.get('node_name'),
                'bmc': r.get('bmc'),
                'resource_class': hw.get('resource_class'),
                'ipmi': hw.get('ipmi'),
                'nics': nics or None,
                'purpose': hw.get('purpose'),
                'flag': hw.get('flag'),
                'in_hardware_doc': bool(hw),
            })
        if nodes:
            c['inventory_nodes'] = nodes
            c['inventory_node_count'] = len(nodes)
            # hubs declare no nodePools in oac-apps, so the inventory is the
            # only source for their node count
            if c['kind'] == 'hub' and c.get('nodes') is None:
                c['nodes'] = len(nodes)
                c['nodes_needs_data'] = False
                c['nodes_source'] = 'open-accelerator-infra inventory'
            # for workload clusters both sources have an opinion: record whether
            # they agree rather than silently preferring one
            if c['kind'] == 'workload' and c.get('nodes') is not None:
                c['node_count_agrees'] = (c['nodes'] == len(nodes))
        c['vlans'] = [dict(netmap.get(v, {'vlan': v}), role='cluster') for v in sorted(vlans)]
        c['vlans'] += [dict(netmap.get(v, {'vlan': v}), role='storage') for v in sorted(storage_vlans)]

        # cross-check: does a storage VLAN's CIDR match what portworx declares?
        declared = oac_storage_cidrs.get(c['name'])
        for v in c['vlans']:
            if v.get('role') == 'storage' and declared:
                v['matches_portworx'] = (v.get('cidr') == declared)

        # a cluster whose nodes are not in the hardware doc still has a storage
        # network: join it on the CIDR portworx declares, which is unambiguous
        if declared and not any(v.get('role') == 'storage' for v in c['vlans']):
            for n in infra.get('networks') or []:
                if n.get('cidr') == declared and n.get('vlan'):
                    c['vlans'].append(dict(n, role='storage', matches_portworx=True))
                    break

    # VLANs that exist on a port but belong to no cluster we know about
    used = sw.get('usage') or {}
    known = {v['vlan'] for c in clusters for v in (c.get('vlans') or [])}
    orphans = []
    for vid, u in used.items():
        meta = (sw.get('vlans') or {}).get(vid) or {}
        name = str(meta.get('name') or '')
        if not name.startswith(('OAC', 'MOCSEC')) or vid in known:
            continue
        orphans.append({'vlan': vid, 'name': name, 'description': meta.get('description'),
                        'cidr': (netmap.get(vid) or {}).get('cidr'),
                        'untagged_ports': len(u['untagged']), 'tagged_ports': len(u['tagged']),
                        'switches': sorted({p['switch'] for p in u['untagged'] + u['tagged']})})
    return sorted(orphans, key=lambda o: o['vlan'])
