/**
 * Redesign window panel: 2px outset chrome, navy title bar with optional
 * right-aligned status, 2px inset body. No titlebar buttons (per handoff).
 */
export default function Panel({
  title,
  right,
  children,
  titleBg = '#000080',
  bodyBg = '#fff',
  bodyStyle = {},
  style = {},
  bodyPad = 6,
}) {
  return (
    <div style={{ border: '2px outset #dfdfdf', background: '#c0c0c0', display: 'flex', flexDirection: 'column', minHeight: 0, ...style }}>
      <div style={{ background: titleBg, color: '#fff', fontSize: 12, fontWeight: 'bold', padding: '2px 4px', display: 'flex', alignItems: 'center', fontFamily: 'Tahoma, sans-serif' }}>
        <span style={{ flex: 1 }}>{title}</span>
        {right && <span style={{ fontWeight: 'normal', fontSize: 10 }}>{right}</span>}
      </div>
      <div style={{ border: '2px inset #dfdfdf', margin: 2, background: bodyBg, padding: bodyPad, flex: 1, minHeight: 0, overflow: 'auto', ...bodyStyle }}>
        {children}
      </div>
    </div>
  )
}
