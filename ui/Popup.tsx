import { useEffect, useRef, type ReactNode } from 'react';

interface PopupProps {
  kicker?: string;
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  /** `tall`: opens at its full height, for content that loads after it opens -- growing
   *  from a line of "Loading…" to a page read as a jump (operator, 2026-10-23). */
  tall?: boolean;
}

/** Details over the page, never pushed into it (operator, 2026-10-23: "why not a popup
 *  with a close button ... same goes for everything, much better with all drill-downs").
 *  Fixed to the window, so it covers the page wherever it was opened from; Close, Escape
 *  or a click outside leaves the page exactly where it was. */
export function Popup({ kicker, title, onClose, children, tall = false }: PopupProps) {
  const panel = useRef<HTMLElement>(null);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => { if (event.key === 'Escape') onClose(); };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [onClose]);

  // Opening something else inside the popup starts it from its top.
  useEffect(() => { panel.current?.scrollTo({ top: 0 }); }, [title]);

  return (
    <div className="azure-cost-drill-backdrop" onClick={onClose}>
      <section ref={panel} className={`card azure-cost-card azure-cost-drill${tall ? ' azure-cost-popup-tall' : ''}`}
               role="dialog" aria-modal="true"
               aria-label={typeof title === 'string' ? title : kicker} onClick={(event) => event.stopPropagation()}>
        <header className="azure-cost-drill-header">
          <div>
            {kicker ? <span className="azure-cost-kpi-label">{kicker}</span> : null}
            <h3>{title}</h3>
          </div>
          <button type="button" className="azure-cost-popup-close" onClick={onClose} aria-label="Close"
                  title="Close (Esc)">✕</button>
        </header>
        {children}
      </section>
    </div>
  );
}

/** A popup opened from a table row. Screens may not portal (`react-dom` is not part of
 *  the host contract), and a table may hold only rows, so it sits in a row that takes
 *  no space; being fixed, it still covers the window. */
export function PopupRow(props: PopupProps) {
  return <tr className="azure-cost-popup-host"><td><Popup {...props} /></td></tr>;
}
