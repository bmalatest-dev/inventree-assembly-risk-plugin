/* InvenTree Assembly Risk UI.
 *
 * All inventory calculations are performed server-side. This file only renders
 * the context supplied by UserInterfaceMixin features.
 */

function resolveFeatureContext(props) {
  // InvenTree has used both direct ``context`` and nested feature payloads in
  // UI plugin renderers. Accept either shape to keep this plugin tolerant of
  // minor frontend-version differences.
  if (!props) return {};
  if (props.context && props.context.rows !== undefined) return props.context;
  if (props.featureContext) return props.featureContext;
  if (props.feature && props.feature.context) return props.feature.context;
  if (props.item && props.item.context) return props.item.context;
  return props.context || props;
}

function getReact() {
  return globalThis.React;
}

function severityColor(severity) {
  if (severity === 'critical') return 'var(--mantine-color-red-7, #c92a2a)';
  if (severity === 'warning') return 'var(--mantine-color-orange-7, #d9480f)';
  return 'var(--mantine-color-green-7, #2b8a3e)';
}

function riskBadge(h, row) {
  return h(
    'span',
    {
      style: {
        display: 'inline-block',
        color: severityColor(row.severity),
        border: '1px solid currentColor',
        borderRadius: '999px',
        padding: '2px 8px',
        fontWeight: 600,
        whiteSpace: 'nowrap',
      },
    },
    row.risk
  );
}

function renderError(h, text) {
  if (!text) return null;
  return h(
    'div',
    {
      style: {
        margin: '8px',
        padding: '10px 12px',
        border: '1px solid var(--mantine-color-red-6, #e03131)',
        borderRadius: '6px',
        color: 'var(--mantine-color-red-7, #c92a2a)',
        whiteSpace: 'pre-wrap',
      },
    },
    text
  );
}

function renderEmpty(h, mode) {
  return h(
    'div',
    { style: { padding: '12px' } },
    mode === 'global'
      ? 'No zero-buffer assembly-risk conditions are currently flagged across Production Build Orders.'
      : 'No assembly-risk conditions are currently flagged for this Build Order.'
  );
}

function renderTable(props, mode) {
  const React = getReact();
  if (!React) {
    return 'Assembly Risk UI could not access the InvenTree React runtime.';
  }
  const h = React.createElement;
  const context = resolveFeatureContext(props);
  const rows = Array.isArray(context.rows) ? context.rows : [];
  const error = context.error || '';
  const notice = context.notice || '';

  const cell = {
    padding: '8px 10px',
    borderBottom: '1px solid var(--mantine-color-default-border, #ddd)',
    verticalAlign: 'top',
  };
  const head = { ...cell, fontWeight: 700, textAlign: 'left', whiteSpace: 'nowrap' };

  if (!rows.length) {
    const noticeNode = notice
      ? h('div', { style: { padding: '12px', opacity: 0.8 } }, notice)
      : renderEmpty(h, mode);
    return h('div', null, renderError(h, error), noticeNode);
  }

  const headers = mode === 'global'
    ? ['Part', 'Open BO Demand', 'Physical Buffer', 'Planned Spillage', 'On Order', 'Affected BOs', 'Assembly Risk', 'Guidance']
    : ['Part', 'Required This BO', 'Physical Buffer', 'Planned Spillage', 'On Order', 'Affected BOs', 'Assembly Risk', 'Guidance'];

  return h(
    'div',
    { style: { overflowX: 'auto', padding: '4px' } },
    renderError(h, error),
    h(
      'table',
      { style: { width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem' } },
      h('thead', null, h('tr', null, ...headers.map((x) => h('th', { key: x, style: head }, x)))),
      h(
        'tbody',
        null,
        ...rows.map((row) =>
          h(
            'tr',
            { key: `${mode}-${row.part_id}-${row.part}` },
            h(
              'td',
              { style: cell },
              h('div', { style: { fontWeight: 600 } }, row.part),
              h('div', { style: { opacity: 0.7, fontSize: '0.82em' } }, row.description || '')
            ),
            h('td', { style: cell }, mode === 'global' ? row.open_demand : row.required_this_build),
            h('td', { style: cell }, row.physical_buffer),
            h('td', { style: cell }, row.planned_spillage),
            h('td', { style: cell }, row.on_order),
            h('td', { style: cell }, row.affected_builds || ''),
            h('td', { style: cell }, riskBadge(h, row)),
            h('td', { style: cell, minWidth: '260px' }, row.message || '')
          )
        )
      )
    )
  );
}

export function renderPanel(props) {
  return renderTable(props, 'build');
}

export function renderDashboardItem(props) {
  return renderTable(props, 'global');
}
