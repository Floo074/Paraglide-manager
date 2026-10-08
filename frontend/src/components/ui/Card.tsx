import type { ReactNode } from "react";

export function Card({
  title,
  icon,
  aside,
  children,
  id,
  className = "",
}: {
  title?: ReactNode;
  icon?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
  id?: string;
  className?: string;
}) {
  return (
    <section className={`card ${className}`} id={id} aria-labelledby={id && title ? `${id}-title` : undefined}>
      {title ? (
        <header className="card__head">
          <h2 className="card__title" id={id ? `${id}-title` : undefined}>
            {icon}
            {title}
          </h2>
          {aside ? <div className="card__aside">{aside}</div> : null}
        </header>
      ) : null}
      {children}
    </section>
  );
}
