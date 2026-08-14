/* Lightweight UI renderer. Heavy calculations are performed in Python and
 * supplied in featureContext, so the panel does not issue extra API requests.
 */
export function renderPanel({ context }) {
  const React = globalThis.React;
  const h = React.createElement;
  const rows = (context && context.rows) || [];

  if (!rows.length) {
    return h('div', { style: { padding: '12px' } },
      'No assembly-risk conditions are currently flagged for this Build Order.'
    );
  }

  const badgeStyle = (severity) => ({
    display: 'inline-block',
    border: '1px solid currentColor',
    borderRadius: '999px',
    padding: '2px 8px',
    fontWeight: 600,
    whiteSpace: 'nowrap',
    opacity: severity === 'ok' ? 0.75 : 1,
  });

  const cell = { padding: '8px 10px', borderBottom: '1px solid var(--mantine-color-default-border, #ddd)', verticalAlign: 'top' };
  const head = { ...cell, fontWeight: 700, textAlign: 'left' };

  return h('div', { style: { overflowX: 'auto', padding: '4px' } },
    h('table', { style: { width: '100%', borderCollapse: 'collapse', fontSize: '0.9rem' } },
      h('thead', null,
        h('tr', null,
          h('th', { style: head }, 'Part'),
          h('th', { style: head }, 'Required'),
          h('th', { style: head }, 'Physical Buffer'),
          h('th', { style: head }, 'Planned Spillage'),
          h('th', { style: head }, 'On Order'),
          h('th', { style: head }, 'Assembly Risk'),
          h('th', { style: head }, 'Guidance')
        )
      ),
      h('tbody', null,
        ...rows.map((row) => h('tr', { key: `${row.part_id}-${row.part}` },
          h('td', { style: cell }, h('div', { style: { fontWeight: 600 } }, row.part), h('div', { style: { opacity: 0.75 } }, row.description || '')),
          h('td', { style: cell }, row.required_this_build),
          h('td', { style: cell }, row.physical_buffer),
          h('td', { style: cell }, row.planned_spillage),
          h('td', { style: cell }, row.on_order),
          h('td', { style: cell }, h('span', { style: badgeStyle(row.severity) }, row.risk)),
          h('td', { style: cell }, row.message)
        ))
      )
    )
  );
}
