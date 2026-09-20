/* Architecture illustration.
 *
 * Rules this diagram follows, deliberately:
 *   - Solid boxes and solid connectors are facts read out of oac-apps.
 *   - Dashed/muted boxes are curated context (data/curated.json): real, but
 *     sourced from design docs and issues rather than from the config repo.
 *   - Anything not known is drawn as a blank "?" slot with NO connector.
 *     Nothing is inferred to make the picture look complete.
 *
 * Laid out by hand rather than by a graph library: the shape is regular (one
 * column per hub) and hand-placement keeps the labels readable.
 */
(function () {
  'use strict';
  var D = window.MOC_DATA;
  var NS = 'http://www.w3.org/2000/svg';

  function n(t, a) {
    var e = document.createElementNS(NS, t);
    for (var k in a) if (a[k] != null) e.setAttribute(k, a[k]);
    return e;
  }
  function cssVar(v) {
    return getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  }

  function textEl(x, y, s, opts) {
    opts = opts || {};
    var t = n('text', {
      x: x, y: y, 'text-anchor': opts.anchor || 'start',
      class: opts.cls || null,
      style: 'font:' + (opts.font || '11px var(--sans)') + ';fill:' + (opts.fill || cssVar('--muted'))
    });
    t.textContent = s;
    return t;
  }

  /* a box with a title, optional subtitle, and a stack of small lines */
  function boxHeight(o) {
    var lines = (o.lines || []).filter(Boolean).length;
    return 17 + (o.kicker ? 13 : 0) + 14 + lines * 12.5 + 8;
  }
  function box(g, o) {
    if (o.h == null) o.h = boxHeight(o);
    var stroke = o.curated ? cssVar('--faint') : (o.accent || cssVar('--rule'));
    var r = n('rect', {
      x: o.x, y: o.y, width: o.w, height: o.h, rx: 7,
      fill: o.fill || cssVar('--surface'),
      stroke: stroke, 'stroke-width': o.curated ? 1 : 1.2,
      'stroke-dasharray': o.curated ? '4 3' : null
    });
    g.appendChild(r);
    var y = o.y + 17;
    if (o.kicker) {
      g.appendChild(textEl(o.x + 11, y, o.kicker,
        { font: '500 9.5px var(--mono)', fill: cssVar('--faint') }));
      y += 13;
    }
    g.appendChild(textEl(o.x + 11, y, o.title,
      { font: '600 12.5px var(--cond)', fill: cssVar('--ink') }));
    y += 14;
    (o.lines || []).forEach(function (l) {
      if (!l) return;
      g.appendChild(textEl(o.x + 11, y, l.text,
        { font: (l.mono ? '10px var(--mono)' : '10.5px var(--sans)'),
          fill: l.dim ? cssVar('--faint') : cssVar('--muted') }));
      y += 12.5;
    });
    return { x: o.x, y: o.y, w: o.w, h: o.h, cx: o.x + o.w / 2, cy: o.y + o.h / 2 };
  }

  /* orthogonal connector: down from a, into the top of b */
  function link(g, a, b, o) {
    o = o || {};
    var col = o.color || cssVar('--rule');
    var x1 = o.x1 != null ? o.x1 : a.cx, y1 = a.y + a.h;
    var x2 = o.x2 != null ? o.x2 : b.cx, y2 = b.y;
    var mid = o.lane != null ? o.lane : y1 + (y2 - y1) / 2;
    var d = 'M' + x1 + ',' + y1 + ' V' + mid + ' H' + x2 + ' V' + y2;
    g.appendChild(n('path', {
      d: d, fill: 'none', stroke: col, 'stroke-width': o.width || 1.2,
      'stroke-dasharray': o.dashed ? '4 3' : null, 'marker-end': 'url(#arrow' + (o.dashed ? 'D' : '') + ')'
    }));
    if (o.label) {
      var lx = (x1 + x2) / 2, ly = mid - 4;
      var t = textEl(lx, ly, o.label, { anchor: 'middle', font: '9.5px var(--mono)', fill: cssVar('--faint') });
      g.appendChild(t);
    }
  }

  /* horizontal connector: right edge of a, into left edge of b */
  function hlink(g, a, b, o) {
    o = o || {};
    var col = o.color || cssVar('--rule');
    var y = o.y || a.cy;
    var d = 'M' + (a.x + a.w) + ',' + y + ' H' + b.x;
    g.appendChild(n('path', {
      d: d, fill: 'none', stroke: col, 'stroke-width': o.width || 1.2,
      'stroke-dasharray': o.dashed ? '4 3' : null, 'marker-end': 'url(#arrow' + (o.dashed ? 'D' : '') + ')'
    }));
    if (o.label) {
      g.appendChild(textEl((a.x + a.w + b.x) / 2, y - 5, o.label,
        { anchor: 'middle', font: '9.5px var(--mono)', fill: cssVar('--faint') }));
    }
  }

  function zone(g, o) {
    g.appendChild(n('rect', {
      x: o.x, y: o.y, width: o.w, height: o.h, rx: 9,
      fill: 'none', stroke: cssVar('--rule'), 'stroke-width': 1,
      'stroke-dasharray': '2 4'
    }));
    g.appendChild(textEl(o.x + 12, o.y + 16, o.label,
      { font: '500 9.5px var(--mono)', fill: cssVar('--faint') }));
    if (o.sub) {
      g.appendChild(textEl(o.x + 12 + o.label.length * 6.2 + 12, o.y + 16, o.sub,
        { font: '10px var(--sans)', fill: cssVar('--faint') }));
    }
  }

  /* every block prints where it came from, so the diagram is checkable */
  function cite(b) {
    if (!b) return null;
    if (b.grounding === 'repo') return { text: b.issue ? 'oac-apps · #' + b.issue : 'oac-apps', dim: true };
    return b.issue ? { text: 'issue #' + b.issue, dim: true } : null;
  }
  function vlanLine(c, role) {
    var v = (c.vlans || []).filter(function (x) { return x.role === role; })[0];
    if (!v) return null;
    return { text: (role === 'storage' ? 'storage ' : '') + 'VLAN ' + v.vlan +
      (v.cidr ? ' ' + v.cidr : ''), mono: true };
  }
  function pick(list, id) {
    return (list || []).filter(function (b) { return b.id === id; })[0] || null;
  }

  window.drawArchitecture = function () {
    var host = document.getElementById('arch');
    if (!host) return;
    host.innerHTML = '';

    var hubs = D.clusters.filter(function (c) { return c.kind === 'hub'; });
    var COLW = 420, GAP = 40, PAD = 18;
    var hubRow = PAD * 2 + hubs.length * COLW + (hubs.length - 1) * GAP;
    var awsRow = PAD * 2 + 16 + 300 + 16 + 250 + 16 + 250 + 16 + 230 + 16;  /* 4 boxes + gaps */
    var W = Math.max(900, hubRow, awsRow);
    var H = 0;   /* set once the data-centre zone is measured */

    var svg = n('svg', { class: 'chart arch',
      role: 'img', 'aria-label': 'MOC 2.0 architecture: identity, AWS, edge, hubs, workload clusters and storage' });

    var defs = n('defs');
    ['arrow', 'arrowD'].forEach(function (id) {
      var m = n('marker', { id: id, viewBox: '0 0 8 8', refX: 7, refY: 4,
        markerWidth: 6, markerHeight: 6, orient: 'auto-start-reverse' });
      m.appendChild(n('path', { d: 'M0,1 L7,4 L0,7 z', fill: cssVar(id === 'arrow' ? '--rule' : '--faint') }));
      defs.appendChild(m);
    });
    svg.appendChild(defs);
    var g = n('g');
    svg.appendChild(g);

    var t = (window.MOC_ANALYSIS || {}).topology || {};
    var sh = D.shared || {};
    var accent = cssVar('--accent');

    /* ---------- identity row (curated: who federates in) ---------- */
    var idpBoxes = (t.external || []).map(function (e, i) {
      return box(g, { x: PAD + i * 210, y: 34, w: 190, curated: true,
        kicker: 'IDENTITY SOURCE', title: e.label,
        lines: [{ text: e.sub, dim: true }, cite(e)], block: e });
    });

    /* ---------- AWS zone ---------- */
    var awsY = 124;
    zone(g, { x: PAD, y: awsY, w: W - PAD * 2, h: 134, label: 'AWS · MOC ACCOUNT',
      sub: '' });

    var bKc = pick(t.aws, 'keycloak'), bSec = pick(t.aws, 'secrets'),
        bR53 = pick(t.aws, 'route53'), bCf = pick(t.aws, 'coldfront');

    var kcLines = (sh.idp_issuers || []).map(function (i) { return { text: i, mono: true }; });
    var keycloak = bKc ? box(g, { x: PAD + 16, y: awsY + 26, w: 300, h: 92, accent: accent,
      kicker: 'IDENTITY PROVIDER', title: bKc.label,
      lines: kcLines.concat([cite(bKc)]) }) : null;

    var secrets = bSec ? box(g, { x: PAD + 332, y: awsY + 26, w: 250, h: 92, accent: accent,
      kicker: 'SECRETS', title: bSec.label,
      lines: [{ text: bSec.sub, mono: true }, cite(bSec)] }) : null;

    var zones = [];
    hubs.forEach(function (h) {
      (h.dns || []).forEach(function (e) { zones = zones.concat(e.zones || []); });
    });
    if (bR53) {
      box(g, { x: PAD + 614, y: awsY + 26, w: 250, h: 92, accent: accent,
        kicker: 'DNS', title: bR53.label,
        lines: zones.slice(0, 2).map(function (z) { return { text: z, mono: true }; })
          .concat([cite(bR53)]) });
    }
    /* ColdFront is grounded but nothing describes what it talks to -> unconnected */
    if (bCf) {
      box(g, { x: PAD + 880, y: awsY + 26, w: 230, h: 92, curated: true,
        kicker: 'NO LINKS IN SOURCES', title: bCf.label,
        lines: [{ text: bCf.sub, dim: true }, cite(bCf)] });
    }

    idpBoxes.forEach(function (b, i) {
      if (!keycloak) return;
      link(g, b, keycloak, { dashed: true, label: 'federates', x2: keycloak.x + 40 + i * 22 });
    });

    /* ---------- edge ---------- */
    var edgeY = 274;
    zone(g, { x: PAD, y: edgeY, w: W - PAD * 2, h: 144, label: 'EDGE' });

    var edgeList = (t.datacenter && t.datacenter.edge) || [];
    var fw = pick(edgeList, 'haproxy');
    if (fw) {
      box(g, { x: PAD + 16, y: edgeY + 24, w: 300, h: 104, curated: true,
        kicker: 'TRACKER', title: fw.label,
        lines: [{ text: fw.sub, dim: true }, cite(fw)] });
    }

    box(g, { x: PAD + 332, y: edgeY + 24, w: 250, h: 104, accent: accent,
      kicker: 'PUBLIC ADDRESSES', title: 'From cluster values',
      lines: (sh.public_ips || []).map(function (ip) { return { text: ip, mono: true }; })
        .concat([{ text: 'oac-apps', dim: true }]) });

    /* bastion: real, but nothing in oac-apps describes what it connects to,
       so it is drawn unconnected rather than wired up speculatively */
    var bast = pick(edgeList, 'bastion');
    if (bast) {
      box(g, { x: PAD + 614, y: edgeY + 24, w: 250, h: 104, curated: true,
        kicker: 'NO LINKS IN SOURCES', title: bast.label,
        lines: [{ text: bast.sub, dim: true }, cite(bast)] });
    }

    /* ---------- data centre ---------- */
    var dcY = 452;
    /* the workload box is the variable-height element, so measure it first and
       size the data-centre zone around it rather than clipping the content */
    var wlH = 0;
    hubs.forEach(function (hub) {
      (hub.hosts || []).forEach(function (name) {
        var c = D.clusters.filter(function (x) { return x.name === name; })[0];
        if (!c) return;
        wlH = Math.max(wlH, boxHeight({ kicker: 1, lines:
          c.nodepools.map(function () { return 1; }).concat([
            1, 1, vlanLine(c, 'cluster'), vlanLine(c, 'storage'), c.idp ? 1 : null]) }));
      });
    });
    /* a hub can host more than one workload cluster, so the boxes stack */
    var maxHosted = Math.max(1, Math.max.apply(null, hubs.map(function (h) {
      return (h.hosts || []).length; })));
    var WL_Y = 268, WL_GAP = 14, ST_GAP = 26;
    var stackH = maxHosted * wlH + (maxHosted - 1) * WL_GAP;
    var dcH = WL_Y + stackH + ST_GAP + 70;
    zone(g, { x: PAD, y: dcY, w: W - PAD * 2, h: dcH,
      label: 'MGHPCC · MOC NETWORKS',
      sub: (t.datacenter && t.datacenter.sub) || '' });

    var workloadBoxes = [];
    hubs.forEach(function (hub, i) {
      var x = PAD + 16 + i * (COLW + GAP);
      var net = hub.network || {};
      var idp = hub.operators.indexOf('keycloak-oauth') >= 0 ? 'keycloak-oauth'
        : (hub.operators.indexOf('github-oauth') >= 0 ? 'github-oauth' : null);

      var hubLines = [
        net.metallb && net.metallb.length ? { text: 'MetalLB ' + net.metallb[0], mono: true } : null,
        net.hcp_router && net.hcp_router.length
          ? { text: 'HCP router ' + net.hcp_router[0], mono: true } : null,
        hub.endpoints && hub.endpoints.internal_domain
          ? { text: hub.endpoints.internal_domain, mono: true } : null,
        vlanLine(hub, 'cluster'),
        vlanLine(hub, 'storage'),
        { text: hub.nodes == null ? 'own nodes: ? (not in oac-apps)' : 'own nodes: ' + hub.nodes,
          dim: hub.nodes == null }
      ];
      var hubBox = box(g, { x: x, y: dcY + 30, w: COLW, accent: accent,
        kicker: 'HUB · ' + hub.env.toUpperCase(), title: hub.name, lines: hubLines });

      /* hosted control planes live here — namespace clusters-<name> */
      var hosted = hub.hosts || [];
      var cpBox = box(g, { x: x + 20, y: dcY + 178, w: COLW - 40,
        fill: cssVar('--surface-2'), accent: cssVar('--s1'),
        kicker: 'HOSTED CONTROL PLANES · ' + hosted.length + ' ON THIS HUB',
        title: 'API server · etcd · scheduler',
        lines: hosted.map(function (hn) {
          return { text: 'clusters-' + hn, mono: true }; }) });
      link(g, hubBox, cpBox, { color: accent, label: 'runs' });

      hosted.forEach(function (name, hi) {
        var c = D.clusters.filter(function (x2) { return x2.name === name; })[0];
        if (!c) return;
        var cn = c.network || {}, st = cn.storage || {};
        var pools = c.nodepools.map(function (p) {
          return { text: p.replicas + '× ' + p.name + '  ' + p.hardware +
            (p.needs_data ? '  · GPUs ?' : (p.gpus ? '  · ' + p.gpus + ' GPU' : '')),
            mono: true };
        });
        var wl = box(g, { x: x, y: dcY + WL_Y + hi * (wlH + WL_GAP), w: COLW, h: wlH,
          accent: cssVar('--s3'),
          kicker: 'WORKLOAD CLUSTER',
          title: c.name,
          lines: pools.concat([
            cn.metallb && cn.metallb.length ? { text: 'MetalLB ' + cn.metallb[0], mono: true } : null,
            c.endpoints && c.endpoints.api_internal
              ? { text: 'API ' + c.endpoints.api_internal + ' → ' + (c.endpoints.api_external || '?'), mono: true }
              : null,
            vlanLine(c, 'cluster'),
            vlanLine(c, 'storage'),
            c.idp ? { text: 'OIDC ' + c.idp.name + ' → Keycloak', mono: true } : null
          ]) });
        link(g, cpBox, wl, { color: cssVar('--s1'), label: 'manages' });
        workloadBoxes.push({ box: wl, cluster: c, storage: st });

        /* the OIDC relationship is stated in the box rather than drawn across
           the whole diagram, which produced unreadable crossings */
      });

      /* how the hub itself authenticates — from the drop-in apps, so it is real */
      if (idp && keycloak) {
        link(g, keycloak, hubBox, { dashed: true, color: cssVar('--faint'),
          x1: keycloak.x + 30 + i * 16, x2: hubBox.x + 36,
          lane: dcY - 26, label: idp });
      }
      if (secrets) link(g, secrets, hubBox, { dashed: true, color: cssVar('--faint'),
        x1: secrets.x + secrets.w - 30 - i * 16, x2: hubBox.x + COLW - 40,
        lane: dcY - 10, label: 'ExternalSecrets' });
    });

    /* ---------- storage ---------- */
    var stY = dcY + WL_Y + stackH + ST_GAP;
    var mgmt = (sh.storage_mgmt || [])[0];
    var pure = t.datacenter && t.datacenter.storage;
    if (!pure) return host.appendChild(svg);
    var stBox = box(g, { x: PAD + 16, y: stY, w: W - PAD * 2 - 32,
      accent: cssVar('--s4'),
      kicker: 'STORAGE',
      title: pure.label + (mgmt ? '  ·  ' + mgmt : ''),
      lines: [{ text: workloadBoxes.map(function (w) {
        return w.cluster.name + ' ' + (w.storage.cidr || '?') +
          (w.storage.routes && w.storage.routes[0] ? ' via ' + w.storage.routes[0].gw : '');
      }).join('    '), mono: true }, cite(pure)] });

    workloadBoxes.forEach(function (w) {
      if (!w.storage.cidr) return;                      /* unknown -> no connector */
      link(g, w.box, stBox, { color: cssVar('--s4'), x2: w.box.cx, label: 'NFS · S3' });
    });

    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + (stBox.y + stBox.h + 28));
    host.appendChild(svg);

    /* legend explains the two line weights, so nothing has to be guessed at */
    var lg = document.getElementById('archLegend');
    if (lg) {
      lg.innerHTML =
        '<span><b style="background:' + accent + '"></b>from the repos</span>' +
        '<span><b style="background:' + cssVar('--faint') + ';opacity:.6"></b>dashed: from the tracker, cited by issue</span>' +
        '<span><b style="background:transparent;border:1px dashed ' + cssVar('--faint') + '"></b>unknown: blank, unconnected</span>';
    }
  };
})();
