/* MOC 2.0 dashboard — renders everything from window.MOC_DATA, which
   tools/build_snapshot.py generates from CCI-MOC/oac-apps and CCI-MOC/MOC-issues.
   No framework, no build step, no network calls: it must work as a plain static
   page on GitHub Pages and from file://.

   Framing that matters: cluster data is *declared* configuration read from Git,
   not live cluster state. The UI says so rather than implying it is monitoring. */
(function () {
  'use strict';
  var D = window.MOC_DATA;
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var el = function (t, cls, txt) {
    var n = document.createElement(t);
    if (cls) n.className = cls;
    if (txt != null) n.textContent = txt;
    return n;
  };
  var esc = function (s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  };
  var ISSUE_URL = 'https://github.com/CCI-MOC/MOC-issues/issues/';
  var APPS_URL = 'https://github.com/CCI-MOC/oac-apps/blob/main/';
  function issueLink(n) {
    return '<a class="iss" target="_blank" rel="noopener" href="' + ISSUE_URL + n + '">#' + n + '</a>';
  }
  function code(s) { return '<code>' + esc(s) + '</code>'; }

  /* ---------------- theme ---------------- */
  var THEME_KEY = 'moc.theme';
  function initTheme() {
    var saved = null;
    try { saved = localStorage.getItem(THEME_KEY); } catch (e) {}
    if (saved) document.documentElement.setAttribute('data-theme', saved);
    $('#themeBtn').addEventListener('click', function () {
      var cur = document.documentElement.getAttribute('data-theme');
      var next = cur ? (cur === 'dark' ? 'light' : 'dark')
        : (matchMedia('(prefers-color-scheme: dark)').matches ? 'light' : 'dark');
      document.documentElement.setAttribute('data-theme', next);
      try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
      redrawCharts();
    });
  }
  function cssVar(n) {
    return getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  }

  /* ---------------- tooltip ---------------- */
  var tip = el('div', 'tooltip');
  document.body.appendChild(tip);
  function showTip(html, ev) {
    tip.innerHTML = html;
    tip.classList.add('on');
    var pad = 14, r = tip.getBoundingClientRect();
    var x = ev.clientX + pad, y = ev.clientY + pad;
    if (x + r.width > innerWidth - 8) x = ev.clientX - r.width - pad;
    if (y + r.height > innerHeight - 8) y = ev.clientY - r.height - pad;
    tip.style.left = Math.max(8, x) + 'px';
    tip.style.top = Math.max(8, y) + 'px';
  }
  function hideTip() { tip.classList.remove('on'); }

  /* ---------------- svg ---------------- */
  var NS = 'http://www.w3.org/2000/svg';
  function svgEl(t, attrs) {
    var n = document.createElementNS(NS, t);
    for (var k in attrs) if (attrs[k] != null) n.setAttribute(k, attrs[k]);
    return n;
  }
  /* rounded on the data end only, square against the baseline */
  function barPath(x, y, w, h, r, horizontal) {
    r = Math.max(0, Math.min(r, horizontal ? w : h));
    if (horizontal) {
      return 'M' + x + ',' + y + ' H' + (x + w - r) + ' A' + r + ',' + r + ' 0 0 1 ' + (x + w) + ',' + (y + r) +
        ' V' + (y + h - r) + ' A' + r + ',' + r + ' 0 0 1 ' + (x + w - r) + ',' + (y + h) + ' H' + x + ' Z';
    }
    return 'M' + x + ',' + (y + h) + ' V' + (y + r) + ' A' + r + ',' + r + ' 0 0 1 ' + (x + r) + ',' + y +
      ' H' + (x + w - r) + ' A' + r + ',' + r + ' 0 0 1 ' + (x + w) + ',' + (y + r) + ' V' + (y + h) + ' Z';
  }
  function hoverable(svg, node, html) {
    node.setAttribute('tabindex', '0');
    function on(ev) { svg.classList.add('dim'); node.classList.add('hot'); showTip(html, ev); }
    function off() { svg.classList.remove('dim'); node.classList.remove('hot'); hideTip(); }
    node.addEventListener('mousemove', on);
    node.addEventListener('mouseleave', off);
    node.addEventListener('focus', function () {
      var b = node.getBoundingClientRect();
      on({ clientX: b.left + b.width / 2, clientY: b.top });
    });
    node.addEventListener('blur', off);
  }

  var charts = [];
  function redrawCharts() { charts.forEach(function (f) { try { f(); } catch (e) {} }); }

  /* ---------------- table ---------------- */
  var NUMCOL = /^(replicas|nodes|gpus|gpus\/node|opened|closed|count|priority|#)$/i;
  function table(headers, rows) {
    var w = el('div', 'tw'), t = el('table');
    var thead = el('thead'), tr = el('tr');
    headers.forEach(function (h) {
      tr.appendChild(el('th', NUMCOL.test(h) && h !== '#' ? 'num' : null, h));
    });
    thead.appendChild(tr); t.appendChild(thead);
    var tb = el('tbody');
    rows.forEach(function (r) {
      var row = el('tr');
      r.forEach(function (cell, i) {
        var td = el('td', NUMCOL.test(headers[i]) && headers[i] !== '#' ? 'num' : null);
        td.innerHTML = (cell == null || cell === '') ? '—' : String(cell);
        row.appendChild(td);
      });
      tb.appendChild(row);
    });
    t.appendChild(tb); w.appendChild(t);
    return w;
  }

  /* =========================================================
     summary — rolled up from the clusters, never hard-coded
     ========================================================= */
  function deriveSummary() {
    var cs = D.clusters, ops = {}, projects = 0, nodes = 0, gpus = 0, gpuNodes = 0, pending = 0;
    var hubNodes = 0, wlNodes = 0;
    cs.forEach(function (c) {
      c.operators.forEach(function (o) { ops[o] = 1; });
      projects += (c.projects || []).length;
      nodes += c.nodes || 0;
      if (c.kind === 'hub') hubNodes += c.nodes || 0; else wlNodes += c.nodes || 0;
      gpus += c.gpus || 0;
      gpuNodes += c.gpu_nodes || 0;
      pending += c.nodes_pending_data || 0;
    });
    return {
      clusters: cs.length,
      hubs: cs.filter(function (c) { return c.kind === 'hub'; }).length,
      workload: cs.filter(function (c) { return c.kind === 'workload'; }).length,
      nodes: nodes, hub_nodes: hubNodes, workload_nodes: wlNodes,
      gpus: gpus, gpu_nodes: gpuNodes, projects: projects,
      nodes_pending: pending,
      operators: Object.keys(ops).length, charts: D.charts.length,
      tiers: (D.policies || []).length,
      open: D.issue_totals.open, closed: D.issue_totals.closed
    };
  }

  function renderTiles() {
    var s = deriveSummary();
    D.derived = s;
    [
      ['Clusters', s.clusters, s.hubs + ' hubs · ' + s.workload + ' workload'],
      ['Nodes', s.nodes, s.workload_nodes + ' workload · ' + s.hub_nodes + ' hub'],
      [s.nodes_pending ? 'GPUs (partial)' : 'GPUs',
        s.gpus + (s.nodes_pending ? '+' : ''),
        s.nodes_pending
          ? '<b>' + s.nodes_pending + ' nodes pending GPU data</b>'
          : s.gpu_nodes + ' GPU nodes'],
      ['Tenant projects', s.projects, ''],
      ['Components', s.operators, 'distinct charts'],
      ['Charts in repo', s.charts, 'under <code>charts/</code>'],
      ['Isolation tiers', s.tiers, 'per workload cluster'],
      ['Issues open', s.open, s.closed + ' closed of ' + D.issue_totals.count]
    ].forEach(function (d) {
      var t = el('div', 'tile');
      t.appendChild(el('dt', null, d[0]));
      t.appendChild(el('dd', null, String(d[1])));
      var sub = el('div', 'sub'); sub.innerHTML = d[2];
      t.appendChild(sub);
      $('#tiles').appendChild(t);
    });
  }

  /* =========================================================
     topology
     ========================================================= */
  function renderTopology() {
    var t = D.topology || {}, wrap = $('#topo');
    if (!t.datacenter) { wrap.appendChild(el('div', 'empty', 'No topology data.')); return; }

    function zone(title, sub, chips) {
      var z = el('div', 'zone');
      z.appendChild(el('h3', null, title));
      if (sub) z.appendChild(el('p', 'zsub', sub));
      var c = el('div', 'chips');
      chips.forEach(function (ch) {
        if (!ch) return;
        var b = el('div', 'chip ' + (ch.kind || 'edge'));
        b.appendChild(el('div', 't', ch.label));
        b.appendChild(el('div', 's', ch.sub));
        c.appendChild(b);
      });
      z.appendChild(c);
      return z;
    }

    var row1 = el('div', 'topo-row');
    row1.style.gridTemplateColumns = 'minmax(220px,1fr) minmax(320px,2fr)';
    row1.appendChild(zone('Where users come from', 'federated identity', t.external || []));
    row1.appendChild(zone('AWS · MOC account',
      'outside the data centre on purpose, so login survives a cluster outage', t.aws || []));
    wrap.appendChild(row1);

    var dc = el('div', 'zone');
    dc.appendChild(el('h3', null, t.datacenter.label));
    dc.appendChild(el('p', 'zsub', t.datacenter.sub));
    var edge = el('div', 'chips');
    (t.datacenter.edge || []).concat([t.datacenter.storage]).forEach(function (e) {
      if (!e) return;
      var b = el('div', 'chip ' + (e.id === 'pure' ? 'store' : 'edge'));
      b.appendChild(el('div', 't', e.label));
      b.appendChild(el('div', 's', e.sub));
      edge.appendChild(b);
    });
    dc.appendChild(edge);

    var hg = el('div', 'hubgrid');
    hg.style.marginTop = '14px';
    D.clusters.filter(function (c) { return c.kind === 'hub'; }).forEach(function (hub) {
      var box = el('div', 'hubbox');
      var h = el('div');
      h.style.display = 'flex'; h.style.alignItems = 'center'; h.style.gap = '9px';
      h.appendChild(el('h4', null, hub.name));
      var e = el('span', 'env' + (hub.env === 'prod' ? ' prod' : ''), hub.env);
      e.style.marginLeft = 'auto';
      h.appendChild(e);
      box.appendChild(h);
      box.appendChild(el('div', 'meta', hub.operators.length + ' components · ' +
        (hub.endpoints.base_domain || '')));
      var hosted = el('div', 'hosted');
      (hub.hosts || []).forEach(function (name) {
        var c = D.clusters.filter(function (x) { return x.name === name; })[0];
        if (!c) return;
        var a = el('a', 'hosted-item');
        a.href = '#cluster-' + c.name;
        a.appendChild(el('span', 'arrow', '└─'));
        a.appendChild(el('span', 'nm', c.name));
        a.appendChild(el('span', 'ct', c.nodes + ' nodes · ' + c.gpus +
          (c.gpus_partial ? '+' : '') + ' GPU · ' + (c.projects || []).length + ' projects'));
        hosted.appendChild(a);
      });
      box.appendChild(hosted);
      hg.appendChild(box);
    });
    dc.appendChild(hg);
    wrap.appendChild(dc);
  }

  /* =========================================================
     clusters
     ========================================================= */
  function renderClusters() {
    var wrap = $('#clusters');
    D.clusters.forEach(function (c) {
      var card = el('article', 'cl');
      card.id = 'cluster-' + c.name;

      var head = el('div', 'cl-head');
      var left = el('div');
      left.appendChild(el('h3', 'nm', c.name));
      left.appendChild(el('p', 'ro', c.role + (c.hub ? ' · control plane runs on ' + c.hub : '')));
      head.appendChild(left);
      var right = el('div', 'right');
      right.appendChild(el('span', 'env' + (c.env === 'prod' ? ' prod' : ''), c.env));
      head.appendChild(right);
      card.appendChild(head);

      if (c.nodepools && c.nodepools.length) {
        var bar = el('div', 'nodebar');
        c.nodepools.forEach(function (p) {
          if (!p.replicas) return;
          var seg = el('i', p.kind === 'gpu' ? 'gpu' : '');
          seg.style.flex = p.replicas;
          seg.title = p.name + ': ' + p.replicas + '× ' + p.hardware;
          bar.appendChild(seg);
        });
        card.appendChild(bar);
        var lg = el('div', 'nodelegend'), seen = {};
        c.nodepools.forEach(function (p) {
          if (!p.replicas || seen[p.kind]) return;
          seen[p.kind] = 1;
          var s = el('span'), b = el('b');
          b.style.background = p.kind === 'gpu' ? 'var(--s3)' : 'var(--s1)';
          s.appendChild(b);
          s.appendChild(document.createTextNode(p.kind === 'gpu' ? 'GPU pool' : 'CPU pool'));
          lg.appendChild(s);
        });
        card.appendChild(lg);
      }

      var stats = el('div', 'cl-stats');
      stats.style.marginTop = '12px';
      (c.kind === 'hub'
        ? [['Components', c.operators.length],
           ['Hosted clusters', (c.hosts || []).length],
           ['Own nodes', c.nodes == null ? '?' : c.nodes],
           ['GPUs', '—']]
        : [['Nodes', c.nodes],
           [c.gpus_partial ? 'GPUs (partial)' : 'GPUs', c.gpus + (c.gpus_partial ? '+' : '')],
           ['Components', c.operators.length],
           ['Projects', (c.projects || []).length]]
      ).forEach(function (p) {
        var d = el('div');
        d.appendChild(el('div', 'k', p[0]));
        d.appendChild(el('div', 'v', String(p[1])));
        stats.appendChild(d);
      });
      card.appendChild(stats);

      var det = el('details', 'more');
      det.appendChild(el('summary', null, 'Node pools, components, projects, policies'));
      var body = el('div', 'more-body');

      if (c.kind === 'hub') {
        body.appendChild(el('div', 'subhead', 'Own nodes'));
        if (c.nodes != null && c.nodes_source) {
          var ok = el('p', 'note');
          ok.innerHTML = c.nodes + ' nodes · source: <code>' + esc(c.nodes_source) + '</code>';
          body.appendChild(ok);
        } else if (c.nodes_needs_data) {
          var hk = el('p', 'note');
          hk.innerHTML = '<span class="status warn"><i class="g"></i>needs data</span> ' +
            'set <code>hub_nodes</code> in <code>data/curated.json</code>';
          body.appendChild(hk);
        } else {
          body.appendChild(table(['Control plane', 'Workers', 'Total'],
            [[c.control_plane_nodes, c.worker_nodes, c.nodes]]));
        }
        body.appendChild(el('div', 'subhead', 'Hosts these clusters'));
        body.appendChild(table(['Cluster', 'Nodes', 'GPUs'],
          (c.hosts || []).map(function (n) {
            var t = D.clusters.filter(function (x) { return x.name === n; })[0] || {};
            return [code(n), t.nodes, (t.gpus || 0) + (t.gpus_partial ? '+' : '')];
          })));
      }

      if (c.nodepools && c.nodepools.length) {
        body.appendChild(el('div', 'subhead', 'Node pools'));
        body.appendChild(table(['Pool', 'Replicas', 'Hardware', 'Resource class', 'GPUs/node', 'GPUs'],
          c.nodepools.map(function (p) {
            if (p.needs_data) {
              var hook = '<span class="status warn" title="' +
                esc(p.profile_source || 'not recorded in oac-apps') +
                '"><i class="g"></i>needs data</span>';
              return [code(p.name), p.replicas, esc(p.hardware), code(p.resource_class),
                hook, hook];
            }
            return [code(p.name), p.replicas, esc(p.hardware), code(p.resource_class),
              p.gpus_per_node || '—', p.gpus || '—'];
          })));
      }

      if ((c.vlans || []).length) {
        body.appendChild(el('div', 'subhead', 'Networks (VLAN → CIDR)'));
        body.appendChild(table(['VLAN', 'Name', 'CIDR', 'Role', 'Cross-check'],
          c.vlans.map(function (v) {
            var chk = v.matches_portworx === true
              ? '<span class="status ok"><i class="g"></i>matches portworx</span>'
              : (v.matches_portworx === false
                 ? '<span class="status warn"><i class="g"></i>differs from portworx</span>' : '');
            return [v.vlan, esc(v.name || '—'), v.cidr ? code(v.cidr) : '—', v.role, chk];
          })));
      }

      if ((c.inventory_nodes || []).length) {
        body.appendChild(el('div', 'subhead', 'Machines (' + c.inventory_nodes.length + ')'));
        body.appendChild(table(['Inventory name', 'Node', 'BMC', 'Class', 'NICs', 'Purpose'],
          c.inventory_nodes.map(function (nd) {
            var nics = nd.nics ? Object.keys(nd.nics).map(function (k) {
              return k.toUpperCase() + ':' + nd.nics[k]; }).join(' ') : null;
            return [code(nd.inventory_name), nd.node_name ? code(nd.node_name) : '—',
              nd.bmc ? code(nd.bmc) : '—', nd.resource_class || '—',
              nics ? code(nics) : '<span class="status idle"><i class="g"></i>not in hardware doc</span>',
              nd.flag ? '<span class="status warn"><i class="g"></i>' + esc(nd.flag) + '</span>'
                      : (nd.purpose || '—')];
          })));
      }

      if (c.idp || c.keycloak_client) {
        body.appendChild(el('div', 'subhead', 'Identity'));
        var kc = c.keycloak_client || {};
        body.appendChild(table(['Provider', 'Type', 'Issuer', 'Redirect URI', 'Client secret'],
          [[c.idp ? code(c.idp.name) : '—', c.idp ? esc(c.idp.type) : '—',
            c.idp ? code(c.idp.issuer) : '—',
            kc.redirect_uri ? code(kc.redirect_uri) : '—',
            kc.client_secret_name ? code(kc.client_secret_name) : '—']]));
      }

      var ep = c.endpoints || {};
      if (ep.api_internal || ep.api_external || ep.base_domain) {
        body.appendChild(el('div', 'subhead', 'Endpoints'));
        body.appendChild(table(['API (internal)', 'API (external)', 'Ingress', 'Base domain'],
          [[code(ep.api_internal || '—'), code(ep.api_external || '—'),
            code(ep.ingress || '—'), code(ep.base_domain || '—')]]));
      }

      body.appendChild(el('div', 'subhead', 'Components (' + c.operators.length + ')'));
      var ops = el('div', 'chips');
      c.operators.forEach(function (o) {
        var b = el('div', 'chip');
        b.appendChild(el('div', 't', o));
        ops.appendChild(b);
      });
      body.appendChild(ops);

      if ((c.projects || []).length) {
        body.appendChild(el('div', 'subhead', 'Tenant projects'));
        body.appendChild(table(['Project', 'Groups', 'What it is'],
          c.projects.map(function (p) {
            return [code(p.name), p.groups.map(code).join(' '), esc(p.description)];
          })));
      }

      if ((c.policies || []).length) {
        body.appendChild(el('div', 'subhead', 'Network isolation (evaluated in order)'));
        body.appendChild(table(['#', 'Policy', 'Kind', 'Scope', 'Priority', 'Defined in'],
          c.policies.map(function (p, i) {
            return [String(i + 1), code(p.name), esc(p.tier), esc(p.scope),
              p.priority == null ? '—' : p.priority,
              '<a class="iss" target="_blank" rel="noopener" href="' + APPS_URL + p.file + '">' +
                esc(p.file.replace('charts/', '')) + '</a>'];
          })));
      }

      var src = el('p', 'note');
      src.innerHTML = '<a class="iss" target="_blank" rel="noopener" href="' +
        APPS_URL + c.source + '">' + esc(c.source) + '</a>';
      body.appendChild(src);
      det.appendChild(body);
      card.appendChild(det);
      wrap.appendChild(card);
    });
  }

  /* =========================================================
     gantt
     ========================================================= */
  /* Sections take categorical slots in the palette's fixed order, so the pairs
     that end up adjacent (in the legend and as neighbouring rows) are the pairs
     the palette was validated on. */
  var SECTION_SLOT = {
    'Deciding': '--s1', 'Clearing': '--s2', 'Stage 1 (dev)': '--s3',
    'Stage 2 (prod)': '--s4', 'Operating': '--s5', 'In parallel': '--s6'
  };
  function day(s) { return new Date(s + 'T00:00:00Z').getTime() / 86400000; }

  function drawGantt() {
    var host = $('#gantt');
    if (!host || !(D.timeline || []).length) return;
    host.innerHTML = '';
    var rows = D.timeline, W = host.clientWidth || 900;
    var padL = Math.min(250, Math.max(140, W * 0.25)), padR = 18, padT = 26, rowH = 21, padB = 44;
    var H = padT + rows.length * rowH + padB;
    var t0 = day('2026-07-06'), t1 = day('2026-09-22');
    var x = function (d) { return padL + (d - t0) / (t1 - t0) * (W - padL - padR); };

    var svg = svgEl('svg', { class: 'chart', viewBox: '0 0 ' + W + ' ' + H, role: 'img',
      'aria-label': 'Programme timeline, July to September 2026' });

    var g = svgEl('g', { class: 'grid' });
    for (var d = t0; d <= t1; d += 7) {
      g.appendChild(svgEl('line', { x1: x(d), x2: x(d), y1: padT - 8, y2: padT + rows.length * rowH + 4 }));
      var lab = svgEl('text', { x: x(d), y: padT + rows.length * rowH + 20, 'text-anchor': 'middle' });
      lab.textContent = new Date(d * 86400000)
        .toLocaleDateString('en-GB', { month: 'short', day: '2-digit', timeZone: 'UTC' });
      g.appendChild(lab);
    }
    svg.appendChild(g);

    if (D.timeline_marker) {
      var mx = x(day(D.timeline_marker.date)), red = cssVar('--st-critical');
      svg.appendChild(svgEl('line', { x1: mx, x2: mx, y1: padT - 12, y2: padT + rows.length * rowH + 4,
        stroke: red, 'stroke-width': 1.2, 'stroke-dasharray': '4 3' }));
      var mt = svgEl('text', { x: mx + 5, y: padT - 14, style: 'fill:' + red });
      mt.textContent = D.timeline_marker.label;
      svg.appendChild(mt);
    }

    rows.forEach(function (r, i) {
      var y = padT + i * rowH, col = cssVar(SECTION_SLOT[r.section] || '--s1');
      var lab = svgEl('text', { x: padL - 10, y: y + 13, 'text-anchor': 'end', class: 'rowlab' });
      lab.textContent = r.label;
      svg.appendChild(lab);
      var node;
      if (!r.end) {
        node = svgEl('path', { class: 'mark', fill: col,
          d: 'M' + x(day(r.start)) + ',' + (y + 4) + ' l6,5.5 l-6,5.5 l-6,-5.5 Z' });
      } else {
        var xs = x(day(r.start)), xe = x(day(r.end));
        node = svgEl('path', { class: 'mark', fill: col,
          d: barPath(xs, y + 4, Math.max(3, xe - xs), 11, 4, true) });
      }
      hoverable(svg, node, '<div class="tt">' + esc(r.label) + '</div><div class="r"><b style="background:' +
        col + '"></b>' + esc(r.section) + '<span class="v">' +
        esc(r.end ? r.start + ' → ' + r.end : r.start) + '</span></div>');
      svg.appendChild(node);
    });
    host.appendChild(svg);

    var lg = $('#ganttLegend');
    lg.innerHTML = '';
    Object.keys(SECTION_SLOT).forEach(function (k) {
      if (!rows.some(function (r) { return r.section === k; })) return;
      var s = el('span'), b = el('b');
      b.style.background = cssVar(SECTION_SLOT[k]);
      s.appendChild(b); s.appendChild(document.createTextNode(k));
      lg.appendChild(s);
    });
  }

  /* =========================================================
     issue throughput
     ========================================================= */
  function drawIssues() {
    var host = $('#issueChart');
    host.innerHTML = '';
    var data = D.issues_weekly, W = host.clientWidth || 900, H = 260;
    var padL = 38, padR = 12, padT = 14, padB = 40;
    var max = Math.max.apply(null, data.map(function (d) { return Math.max(d.opened, d.closed); }));
    max = Math.max(20, Math.ceil(max / 20) * 20);
    var bw = (W - padL - padR) / data.length;
    var y = function (v) { return padT + (1 - v / max) * (H - padT - padB); };
    var c1 = cssVar('--s1'), c2 = cssVar('--s2');

    var svg = svgEl('svg', { class: 'chart', viewBox: '0 0 ' + W + ' ' + H, role: 'img',
      'aria-label': 'Issues opened and closed per week' });
    var g = svgEl('g', { class: 'grid' });
    for (var v = 0; v <= max; v += 20) {
      g.appendChild(svgEl('line', { x1: padL, x2: W - padR, y1: y(v), y2: y(v) }));
      var tl = svgEl('text', { x: padL - 8, y: y(v) + 4, 'text-anchor': 'end' });
      tl.textContent = v;
      g.appendChild(tl);
    }
    svg.appendChild(g);

    data.forEach(function (d, i) {
      var cx = padL + i * bw, inner = bw * 0.62, each = (inner - 2) / 2;
      var x0 = cx + (bw - inner) / 2;
      var html = '<div class="tt">Week of ' + esc(d.week) + '</div>' +
        '<div class="r"><b style="background:' + c1 + '"></b>Opened<span class="v">' + d.opened + '</span></div>' +
        '<div class="r"><b style="background:' + c2 + '"></b>Closed<span class="v">' + d.closed + '</span></div>';
      [[d.opened, c1, x0], [d.closed, c2, x0 + each + 2]].forEach(function (s) {
        var h = (H - padT - padB) - (y(s[0]) - padT);
        var p = svgEl('path', { class: 'mark', fill: s[1], d: barPath(s[2], y(s[0]), each, h, 4, false) });
        hoverable(svg, p, html);
        svg.appendChild(p);
      });
      var lab = svgEl('text', { x: cx + bw / 2, y: H - padB + 18, 'text-anchor': 'middle' });
      lab.textContent = d.week.slice(5).replace('-', '/');
      svg.appendChild(lab);
    });
    svg.appendChild(svgEl('line', { class: 'axis', x1: padL, x2: W - padR, y1: y(0), y2: y(0) }));
    host.appendChild(svg);
  }

  /* =========================================================
     capacity — declared node pools per workload cluster
     ========================================================= */
  function drawCapacity() {
    var host = $('#capChart');
    host.innerHTML = '';
    var cls = D.clusters.filter(function (c) { return c.kind === 'workload'; });
    if (!cls.length) return;
    var W = host.clientWidth || 800;
    var padL = Math.min(210, Math.max(130, W * 0.24)), padR = 150, padT = 8, rowH = 42, padB = 16;
    var H = padT + cls.length * rowH + padB;
    var max = Math.max.apply(null, cls.map(function (c) { return c.nodes; }));
    var scale = function (v) { return v / max * (W - padL - padR); };
    var cCpu = cssVar('--s3'), cGpu = cssVar('--s4');

    var svg = svgEl('svg', { class: 'chart', viewBox: '0 0 ' + W + ' ' + H, role: 'img',
      'aria-label': 'Declared node pools per workload cluster' });

    cls.forEach(function (c, i) {
      var y0 = padT + i * rowH;
      var lab = svgEl('text', { x: padL - 10, y: y0 + 22, 'text-anchor': 'end', class: 'rowlab' });
      lab.textContent = c.name;
      svg.appendChild(lab);

      var cursor = padL;
      c.nodepools.forEach(function (p, j) {
        if (!p.replicas) return;
        var full = scale(p.replicas);
        var isLast = j === c.nodepools.length - 1;
        var col = p.kind === 'gpu' ? cGpu : cCpu;
        var node = svgEl('path', { class: 'mark', fill: col,
          d: barPath(cursor, y0 + 9, Math.max(3, full - 2), 16, isLast ? 4 : 0, true) });
        hoverable(svg, node,
          '<div class="tt">' + esc(c.name) + ' · pool ' + esc(p.name) + '</div>' +
          '<div class="r"><b style="background:' + col + '"></b>' + esc(p.hardware) +
          '<span class="v">' + p.replicas + ' nodes</span></div>' +
          (p.needs_data
            ? '<div class="r" style="color:var(--st-warning)">GPUs<span class="v">needs data</span></div>'
            : (p.gpus ? '<div class="r" style="color:var(--muted)">GPUs<span class="v">' +
                p.gpus + '</span></div>' : '')));
        svg.appendChild(node);
        cursor += full;
      });

      var vt = svgEl('text', { x: cursor + 8, y: y0 + 22, class: 'val' });
      vt.textContent = c.nodes + ' nodes · ' + c.gpus + ' GPUs' +
        (c.gpus_partial ? ' (+' + c.nodes_pending_data + ' nodes pending)' : '');
      svg.appendChild(vt);
    });
    host.appendChild(svg);
  }

  /* =========================================================
     governance
     ========================================================= */
  function renderGovernance() {
    var cols = [['approved', 'Signed off / closed'], ['in-review', 'Under review'], ['open', 'Open question']];
    cols.forEach(function (c) {
      var items = D.rfcs.filter(function (r) { return r.status === c[0]; });
      var col = el('div', 'col ' + c[0]);
      var h = el('h3');
      h.appendChild(document.createTextNode(c[1]));
      h.appendChild(el('span', 'n', String(items.length)));
      col.appendChild(h);
      items.forEach(function (r) {
        var card = el('div', 'rfc');
        card.appendChild(el('div', 'id', r.id));
        card.appendChild(el('div', 't', r.title));
        var f = el('div', 'f');
        f.innerHTML = issueLink(r.issue) + (r.owner ? ' <span>' + esc(r.owner) + '</span>' : '');
        var up = el('span'); up.style.marginLeft = 'auto'; up.textContent = r.updated;
        f.appendChild(up);
        card.appendChild(f);
        col.appendChild(card);
      });
      if (!items.length) col.appendChild(el('div', 'empty', 'None'));
      $('#board').appendChild(col);
    });

    $('#decisions').appendChild(table(
      ['Date', 'Decision', 'Area', 'Instead of', 'Why', 'Issue'],
      D.decisions.slice().sort(function (a, b) { return a.date < b.date ? 1 : -1; })
        .map(function (d) {
          return [d.date, '<b>' + esc(d.title) + '</b>', esc(d.area), esc(d.rejected),
            esc(d.why || ''), issueLink(d.issue)];
        })));
  }

  /* =========================================================
     discoveries
     ========================================================= */
  function renderDiscoveries() {
    D.discoveries.forEach(function (f) {
      var c = el('div', 'find ' + f.severity);
      var h = el('div', 'h');
      h.appendChild(el('h3', 't', f.title));
      var badge = { fixed: ['ok', 'Fixed'], open: ['warn', 'Open'], documented: ['idle', 'Documented'] }[f.status]
        || ['idle', f.status];
      var s = el('span', 'status ' + badge[0]);
      s.appendChild(el('i', 'g'));
      s.appendChild(document.createTextNode(badge[1]));
      h.appendChild(s);
      h.appendChild(el('span', 'meta', f.date + ' · ' + f.found_by));
      c.appendChild(h);
      c.appendChild(el('p', 'd', f.detail));
      if (f.issue) {
        var a = el('div');
        a.style.marginTop = '6px';
        a.innerHTML = issueLink(f.issue);
        c.appendChild(a);
      }
      $('#finds').appendChild(c);
    });
  }

  /* =========================================================
     reference
     ========================================================= */
  function renderReference() {
    var host = $('#chartTable'), input = $('#refSearch'), chips = $('#refChips');
    var targets = [];
    D.charts.forEach(function (c) {
      c.targets.forEach(function (t) { if (targets.indexOf(t) < 0) targets.push(t); });
    });
    var active = null;
    targets.sort().forEach(function (a) {
      var b = el('button', 'fchip', a);
      b.type = 'button';
      b.setAttribute('aria-pressed', 'false');
      b.addEventListener('click', function () {
        active = (active === a) ? null : a;
        Array.prototype.forEach.call(chips.children, function (ch) {
          ch.setAttribute('aria-pressed', String(ch.textContent === active));
        });
        draw();
      });
      chips.appendChild(b);
    });

    function draw() {
      var q = (input.value || '').toLowerCase().trim();
      var f = D.charts.filter(function (c) {
        if (active && c.targets.indexOf(active) < 0) return false;
        if (!q) return true;
        return (c.name + ' ' + c.description + ' ' + c.targets.join(' ')).toLowerCase().indexOf(q) >= 0;
      });
      host.innerHTML = '';
      $('#refCount').textContent = f.length + ' of ' + D.charts.length;
      if (!f.length) { host.appendChild(el('div', 'empty', 'No charts match that filter.')); return; }
      host.appendChild(table(['Chart', 'What it installs', 'Deployed to'],
        f.map(function (c) {
          return ['<a class="iss" target="_blank" rel="noopener" href="' + APPS_URL + 'charts/' +
            c.name + '">' + esc(c.name) + '</a>', esc(c.description || ''),
            c.targets.map(function (t) { return '<code>' + esc(t) + '</code>'; }).join(' ')];
        })));
    }
    input.addEventListener('input', draw);
    draw();
  }

  function renderIdentity() {
    var i = D.identity || {};
    var wrap = $('#idWrap');
    if (!wrap) return;
    if (!i.realm) {
      wrap.appendChild(el('div', 'empty', 'No identity data. Pass --keycloak to the generator.'));
      return;
    }
    var r = i.realm;
    var flags = ['registration_allowed', 'login_with_email_allowed', 'duplicate_emails_allowed',
                 'edit_username_allowed', 'reset_password_allowed', 'remember_me', 'verify_email'];
    $('#idRealmName').innerHTML = 'realm ' + code(r.name) + ' · ' + code(r.source || '');
    $('#idRealm').appendChild(table(['Setting', 'Value'],
      flags.filter(function (k) { return k in r; }).map(function (k) {
        var v = r[k];
        return [code(k),
          v === true ? '<span class="status ok"><i class="g"></i>true</span>'
            : (v === false ? '<span class="status idle"><i class="g"></i>false</span>' : esc(String(v)))];
      }).concat([[code('access_token_lifespan'), code(r.access_token_lifespan || '—')],
                 [code('sso_session_idle_timeout'), code(r.sso_session_idle_timeout || '—')],
                 [code('sso_session_max_lifespan'), code(r.sso_session_max_lifespan || '—')],
                 [code('ssl_required'), code(r.ssl_required || '—')]])));

    $('#idProviders').appendChild(table(
      ['Provider', 'Issuer', 'Enabled', 'Sync', 'Trust email', 'First-broker flow'],
      (i.providers || []).map(function (p) {
        var val = function (x) {
          if (x === undefined || x === null) return '—';
          if (typeof x === 'string' && x.indexOf('var.') === 0)
            return '<span class="status idle"><i class="g"></i>variable</span>';
          return typeof x === 'boolean'
            ? (x ? '<span class="status ok"><i class="g"></i>true</span>'
                 : '<span class="status idle"><i class="g"></i>false</span>')
            : code(x);
        };
        return [code(p.alias || p.resource), val(p.issuer), val(p.enabled),
          p.sync_mode ? code(p.sync_mode) : '—', val(p.trust_email),
          p.first_broker_login_flow_alias ? code(p.first_broker_login_flow_alias) : '—'];
      })));

    var names = {};
    D.clusters.forEach(function (c) { names[c.name] = 1; });
    $('#idClients').appendChild(table(['Cluster', 'Redirect URI', 'Secret', 'In oac-apps'],
      (i.clients || []).map(function (c) {
        return [code(c.cluster_name), code(c.redirect_uri || '—'),
          code(c.client_secret_name || '—'),
          names[c.cluster_name] ? '<span class="status ok"><i class="g"></i>yes</span>'
            : '<span class="status warn"><i class="g"></i>no cluster</span>'];
      })));

    var gp = el('div', 'chips');
    (i.groups || []).forEach(function (g) {
      var b = el('div', 'chip');
      b.appendChild(el('div', 't', g.name));
      b.appendChild(el('div', 's', g.used_by_a_project ? 'referenced by a project' : '—'));
      gp.appendChild(b);
    });
    $('#idGroups').appendChild(gp);

    (i.flows || []).filter(function (f) { return f.resource !== '_unattached'; })
      .forEach(function (f) {
        var h = el('div', 'subhead', (f.alias || f.resource) + ' · ' + f.steps.length + ' steps');
        $('#idFlows').appendChild(h);
        $('#idFlows').appendChild(table(['#', 'Requirement', 'Authenticator', 'Subflow'],
          f.steps.map(function (st, n) {
            return [String(n + 1),
              st.requirement === 'REQUIRED'
                ? '<span class="status ok"><i class="g"></i>REQUIRED</span>'
                : (st.requirement === 'DISABLED'
                   ? '<span class="status idle"><i class="g"></i>DISABLED</span>'
                   : code(st.requirement || '—')),
              code(st.authenticator || '—'), st.subflow ? esc(st.subflow) : '—'];
          })));
      });
  }

  function renderNetworks() {
    var nw = D.network || {};
    if (!nw.stats || !nw.stats.vlans_defined) {
      var host0 = $('#netWrap');
      if (host0) host0.appendChild(el('div', 'empty',
        'No switch data. Pass --ansible-switches and --infra to the generator.'));
      return;
    }
    var st = nw.stats;
    [['Switches', st.switches_in_inventory, st.switches_with_config + ' with port config'],
     ['Interfaces', st.interfaces, st.interfaces_with_vlan + ' carry a VLAN'],
     ['VLANs defined', st.vlans_defined, st.vlans_in_use + ' seen on a port'],
     ['VLAN/CIDR rows', (nw.cidrs || []).length, 'from the hardware doc']]
      .forEach(function (t) {
        var d = el('div', 'tile');
        d.appendChild(el('dt', null, t[0]));
        d.appendChild(el('dd', null, String(t[1])));
        d.appendChild(el('div', 'sub', t[2]));
        $('#netTiles').appendChild(d);
      });

    var counts = nw.usage_counts || {};
    var claimed = {};
    D.clusters.forEach(function (c) {
      (c.vlans || []).forEach(function (v) { claimed[v.vlan] = c.name; });
    });
    var rows = (nw.cidrs || []).map(function (n) {
      var u = counts[String(n.vlan)] || { untagged: 0, tagged: 0, switches: [] };
      return [n.vlan, esc(n.name), n.cidr ? code(n.cidr) : '—',
        claimed[n.vlan] ? code(claimed[n.vlan])
          : '<span class="status warn"><i class="g"></i>no declared cluster</span>',
        u.untagged, u.tagged];
    });
    $('#netTable').appendChild(table(
      ['VLAN', 'Network', 'CIDR', 'Used by', 'Untagged', 'Tagged'], rows));

    (nw.unclaimed || []).forEach(function (o) {
      var sev = /^MOCSEC/.test(o.name) ? 'warning' : 'warning';
      var c = el('div', 'find ' + sev);
      var h = el('div', 'h');
      h.appendChild(el('h3', 't', o.vlan + ' · ' + o.name));
      var s2 = el('span', 'status warn');
      s2.appendChild(el('i', 'g'));
      s2.appendChild(document.createTextNode('wired, not declared'));
      h.appendChild(s2);
      h.appendChild(el('span', 'meta', o.untagged_ports + ' untagged · ' +
        o.tagged_ports + ' tagged ports'));
      c.appendChild(h);
      c.appendChild(el('p', 'd', (o.description || '') +
        (o.cidr ? ' · ' + o.cidr : '') +
        ' · ' + o.switches.slice(0, 4).join(', ') +
        (o.switches.length > 4 ? ' +' + (o.switches.length - 4) + ' more' : '')));
      $('#netUnclaimed').appendChild(c);
    });
  }

  function renderRecentIssues() {
    $('#recentIssues').appendChild(table(
      ['#', 'Title', 'State', 'Labels', 'Updated'],
      D.issues_recent.map(function (i) {
        return [issueLink(i.num), esc(i.title),
          i.state === 'open' ? '<span class="status warn"><i class="g"></i>Open</span>'
            : '<span class="status ok"><i class="g"></i>Closed</span>',
          i.labels.map(function (l) { return '<code>' + esc(l) + '</code>'; }).join(' '),
          i.updated];
      })));
  }

  /* =========================================================
     chrome
     ========================================================= */
  function renderHeader() {
    $('#genAt').textContent = D.generated_at.replace('T', ' ').replace('Z', '').slice(0, 16) + ' UTC';
    var a = D.sources.apps;
    $('#srcApps').innerHTML = code(a.repo) + ' @ ' + code(a.commit) + ' (' + esc(a.branch) + ')';
    $('#srcIssues').innerHTML = code(D.sources.issues.repo) + ' · ' +
      D.sources.issues.count + ' issues, ' + esc(D.sources.issues.window);
    var b = $('#banner');
    if (D.mock) {
      $('#freshDot').classList.add('mock');
      b.innerHTML = '<span class="ico">●</span><div><b>Mock data.</b> Sample values, not read from the real sources.</div>';
    } else {
      b.innerHTML = '<span class="ico">●</span><div><b>Declared configuration, not live cluster state.</b> ' +
        'Read from Git. GPUs per node come from <code>data/curated.json</code>; ' +
        'node counts are node-pool replicas.</div>';
    }
    $('#capNote').innerHTML = esc(D.caveats.billing).replace('#481', issueLink(481));
  }

  /* section notes: on by default, remembered per viewer */
  var EXPLAIN_KEY = 'moc.explain';
  function initExplain() {
    var btn = $('#explainBtn');
    if (!btn) return;
    var off = false;
    try { off = localStorage.getItem(EXPLAIN_KEY) === 'off'; } catch (e) {}
    function apply() {
      document.documentElement.setAttribute('data-explain', off ? 'off' : 'on');
      btn.setAttribute('aria-pressed', String(!off));
      btn.textContent = off ? 'Notes off' : 'Notes';
    }
    apply();
    btn.addEventListener('click', function () {
      off = !off;
      try { localStorage.setItem(EXPLAIN_KEY, off ? 'off' : 'on'); } catch (e) {}
      apply();
    });
  }

  function initNav() {
    var links = Array.prototype.slice.call(document.querySelectorAll('.nav a'));
    var secs = links.map(function (a) { return document.querySelector(a.getAttribute('href')); });
    var obs = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (!e.isIntersecting) return;
        links.forEach(function (l, i) { l.classList.toggle('on', secs[i] === e.target); });
      });
    }, { rootMargin: '-90px 0px -70% 0px', threshold: 0 });
    secs.forEach(function (s) { if (s) obs.observe(s); });
  }

  function boot() {
    initTheme();
    initExplain();
    renderHeader();
    renderTiles();
    renderClusters();
    renderGovernance();
    renderDiscoveries();
    renderReference();
    renderIdentity();
    renderNetworks();
    renderRecentIssues();
    charts.push(drawGantt, drawIssues, drawCapacity);
    if (window.drawArchitecture) charts.push(window.drawArchitecture);
    redrawCharts();
    initNav();
    var rt;
    addEventListener('resize', function () { clearTimeout(rt); rt = setTimeout(redrawCharts, 140); });
    addEventListener('scroll', hideTip, { passive: true });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
