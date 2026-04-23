/**
 * Win95 Window component — title bar + body.
 * No dragging, no resizing. Just tiled panels.
 */
export default function W95Window({ title, icon, children, className = '', bodyClass = '', maxHeight }) {
  const bodyStyle = maxHeight ? { maxHeight, overflowY: 'auto' } : {}

  return (
    <div className={`w95-window ${className}`}>
      <div className="w95-titlebar">
        {icon && <span style={{ fontSize: 11 }}>{icon}</span>}
        <span className="w95-titlebar-text">{title}</span>
        <button className="w95-titlebar-btn">_</button>
        <button className="w95-titlebar-btn">{'\u25a1'}</button>
        <button className="w95-titlebar-btn">{'\u00d7'}</button>
      </div>
      <div className={`w95-body ${bodyClass}`} style={bodyStyle}>
        {children}
      </div>
    </div>
  )
}
